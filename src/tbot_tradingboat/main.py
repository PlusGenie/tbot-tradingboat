# -*- coding: utf-8 -*-

"""
Tbot decodes TradingView webhook from Redis Pub/Sub and then send orders to ib_insyc
"""
__author__ = "Sangwook Lee"
__copyright__ = "Copyright (C) 2023 Plusgenie Ltd"
__license__ = "Dual-Licensing (GPL or Commercial License)"


import sys
import socket
import time
from time import perf_counter
from dataclasses import dataclass

from typing import Dict
from loguru import logger
import numpy as np
import redis
from tbot_tradingboat.pg_msg_apps.discord import DiscordObserver
from tbot_tradingboat.pg_msg_apps.telegram import TelegramObserver
from tbot_tradingboat.utils.tbot_watchdog import WatchObserver
from tbot_tradingboat.pg_redis.stream import TbotStream
from tbot_tradingboat.pg_redis.pub_sub import TbotSub
from tbot_tradingboat.pg_decoder.tbot_decoder import TBOTDecoder
from tbot_tradingboat.utils.tbot_log import tbot_initialize_log
from tbot_tradingboat.utils.tbot_env import shared
from tbot_tradingboat.utils.tbot_utils import strtobool


@dataclass
class TbotSubject:
    """
    The TbotSubject interface declares a set of methods
    for managing subscribers.
    """

    # List of subscribers.
    _observers = []

    def __init__(self):
        """Initialize a subscriber to redis"""
        self.redis = None
        self.connect_to_tbot_redis()
        self.event_loop_ms = 0.0
        self.profiler = strtobool(shared.profiler)

    def connect_to_tbot_redis(self):
        """
        Connects to Redis's subscriber
        """
        if strtobool(shared.r_is_stream):
            self.redis = TbotStream()
        else:
            self.redis = TbotSub()
        while True:
            try:
                self.redis.connect()
                break
            except KeyboardInterrupt:
                logger.info("got exception: KeyboardInterrupt")
                break
            except Exception as err:
                logger.warning(f"trying to redis..{err}")
                time.sleep(2)

    def attach(self, observer):
        """
        Subject attaches an observer
        """
        logger.trace("attaching an observer.")
        self._observers.append(observer)
        observer.open()

    def detach(self, observer):
        """
        Subject deataches an observer
        """
        self._observers.remove(observer)

    def notify(self, id_stream: str, data_dict: Dict, **kwargs):
        """
        Trigger an update in each IBKR subscriber.
        """
        # logger.debug("notifying observers...")
        for observer in self._observers:
            observer.update(self, id_stream, data_dict, **kwargs)

    def delete_event(self, msg_id: str = ""):
        """Deletes an event hanlded by a decoder"""
        if self.redis:
            self.redis.delete(msg_id)

    def handle_reconnect(self):
        """Handle re-connection during exceptions"""
        while True:
            time.sleep(12)
            logger.critical("Attempting to reconnect to Redis...")
            if self.redis.connect():
                break

    def handle_event(self):
        """Handles a new event from Server"""
        while True:
            time_s = perf_counter()
            try:
                # Entering the while loop
                (s_id, data, redis_msg_id) = self.redis.handle_event(self)
                self.notify(s_id, data, redis_msg_id=redis_msg_id)
            except KeyboardInterrupt:
                logger.info("got exception: KeyboardInterrupt")
                break
            except ConnectionRefusedError as err:
                logger.warning(f"Redis connection error: {err}")
                self.handle_reconnect()
            except redis.exceptions.ConnectionError as err:
                logger.warning(f"Redis connection error: {err}")
                self.handle_reconnect()
            except socket.error as err:
                logger.warning(f"got socket exception: {err}")
                logger.critical("ignoring socket err and continue..")
            except Exception as err:
                logger.critical(err)
                logger.exception(err)
                break
            self.event_loop_ms = (perf_counter() - time_s) * 1e3
            if self.profiler:
                if abs(np.random.normal(0.0, 3, 1)) > 9:
                    logger.debug(f"loop-time: {self.event_loop_ms:.2f}ms")
            logger.trace(f"loop-time: {self.event_loop_ms:.2f}ms")
        logger.debug("handle_e: finished")
        self.close()

    def close(self):
        """Closes observers"""
        for observer in self._observers:
            observer.close()
        if self.redis:
            self.redis.close()


def main() -> int:
    """Main entry of Tbot on Tradingboat"""
    tbot_initialize_log()

    subject = TbotSubject()
    observer_i = TBOTDecoder()
    observer_w = WatchObserver()
    observer_d = DiscordObserver()
    observer_t = TelegramObserver()

    try:
        subject.attach(observer_i)
        subject.attach(observer_w)
        subject.attach(observer_d)
        subject.attach(observer_t)
    except Exception as err:
        logger.error(f"Error while attaching observers: {err}")
        sys.exit(1)

    # Entering Event Looop
    subject.handle_event()

    # Closes the app
    subject.detach(observer_i)
    subject.detach(observer_w)
    subject.detach(observer_d)
    subject.detach(observer_t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
