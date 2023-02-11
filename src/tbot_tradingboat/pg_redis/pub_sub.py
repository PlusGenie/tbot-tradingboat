# -*- coding: utf-8 -*-

"""
Tbot decodes TradingView webhook from Redis Pub/Sub and then send orders to ib_insyc
"""
__author__ = "Sangwook Lee"
__copyright__ = "Copyright (C) 2023 Plusgenie Ltd"
__license__ = "Dual-Licensing (GPL or Commercial License)"


import time
import json
from typing import Tuple
from dataclasses import dataclass

import redis
from loguru import logger

from tbot_tradingboat.utils.tbot_env import shared
from .valid_timestamp import RedisMessageValidator
from .listener import TbotListener


@dataclass
class TbotSub(TbotListener):
    """
    Suscriber as Redis PubSub
    """

    REDIS_CHANNEL = "REDIS_CH_"

    def __init__(self):
        """Initialize a subscriber to redis"""
        self.pool = None
        self.dbase = None
        self.chan_conn = None
        self.r_read_timeout_sec = max(float(shared.r_read_timeout_ms) / 1000, 0)
        self.validts = RedisMessageValidator()
        self.r_channel = self.REDIS_CHANNEL + shared.client_id

    def open(self):
        """Placeholder for Open"""
        logger.trace("open")

    def connect(self) -> bool:
        """Connects to Redis Channel"""
        try:
            tcp = {
                "host": shared.r_host,
                "port": int(shared.r_port),
                "password": shared.r_passwd,
                "decode_responses": True,
                "retry_on_timeout": True,
                "max_connections": 10,
            }
            unix = {
                "password": shared.r_passwd,
                "decode_responses": True,
                "retry_on_timeout": True,
                "max_connections": 10,
            }
            if shared.r_host:
                self.pool = redis.ConnectionPool(**tcp)
            else:
                redis_url = f"unix://{shared.r_host_unix}"
                self.pool = redis.ConnectionPool.from_url(redis_url, **unix)

            logger.debug(f"connecting to Redis:{self.pool}")
            self.dbase = redis.Redis(connection_pool=self.pool)
            # not interested in the (sometimes noisy) subscribe/unsubscribe
            self.chan_conn = self.dbase.pubsub(ignore_subscribe_messages=True)
            self.chan_conn.subscribe(self.r_channel)

            logger.success(f"connected successfully to Redis:{self.r_channel}")
        except ConnectionRefusedError as err:
            logger.error(err)
            return False
        except redis.exceptions.ConnectionError as err:
            logger.error(f"Failed to connect to Redis: {err}")
            return False
        except OSError as err:
            logger.error(err)
            return False
        return True

    def validate_message(self, msg) -> object:
        """
        Returns None if this is not valid pubsub messsage
        message (_type_): a message from Redis PubSub channel
        """
        # 'data' is the fixed property of redis's pubsub message
        msg = msg.get("data")
        ret = None
        if msg:
            data_dict = json.loads(msg)
            ret = self.validts.validate_message(data_dict)
        return ret

    def handle_event(self, caller) -> Tuple[str, str, str]:
        """
        Vadidates the message and then dispatch it to observers
        """
        if not self.dbase:
            return None, None, None
        id_stream, validated_message = None, None
        try:
            msg = self.chan_conn.get_message(timeout=self.r_read_timeout_sec)
        except redis.exceptions.ConnectionError as err:
            logger.warning(f"Redis connection error: {err}")
            logger.critical("Attempting to reconnect to Redis...")
            self.connect()  # try to reconnect to Redis
            return None, None, None
        if msg:
            validated_message = self.validate_message(msg)
            if validated_message:
                logger.debug(f"[Received validated message]: {validated_message}")
                id_stream = str(time.time_ns() // 1000000)
            else:
                logger.warning(f"Detecting invalid stream: {msg}")
        return id_stream, validated_message, None

    def delete(self, id_stream: str):
        """
        Deletes a Redis pub/sub
        """
        logger.trace(f"Deleting Redis message: {id_stream}")

    def close(self):
        """Closes connection to Redis"""
        if self.chan_conn:
            self.chan_conn.unsubscribe()
            self.chan_conn = None
