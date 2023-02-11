#!/usr/bin/env python3
"""
Plusgenie(c) 2023 All rights reserved.
"""
# -*- coding: utf-8 -*-
__author__ = "Sangwook Lee"
__copyright__ = "Copyright (C) 2023 Plusgenie Ltd"
__license__ = "Dual-Licensing (GPL or Commercial License)"


from dataclasses import dataclass
from typing import Dict
import random
import redis
from loguru import logger

from tbot_tradingboat.pg_decoder.tbot_observer import TbotObserver
from tbot_tradingboat.utils.tbot_env import shared


@dataclass
class WatchObserver(TbotObserver):
    """
    Implement WatchDog for TBOT
    """

    def is_redis_alive(self) -> bool:
        """
        Checks if redis's connection is alive
        """
        is_connected: bool = False
        try:
            if shared.r_host:
                logger.trace(f"trying to connect {shared.r_host}:{shared.r_port}")
                con = redis.Redis(
                    host=shared.r_host,
                    port=int(shared.r_port),
                    password=shared.r_passwd,
                )
                is_connected = con.ping()
                logger.trace(f"get a ping resp = {is_connected}")
            else:
                logger.trace(f"trying to connect {shared.r_host_unix}")
                con = redis.Redis(
                    unix_socket_path=shared.r_host_unix, password=shared.r_passwd
                )
                is_connected = con.ping()
                logger.trace(f"get a ping resp = {is_connected}")
        except redis.ConnectionError as err:
            logger.error(f"Redis connection error {err}")
            is_connected = False
        except BaseException as err:
            logger.error(f"{err}")
        return is_connected

    def open(self):
        pass

    def update(
        self,
        caller: object = None,
        tbot_ts: str = None,
        data_dict: Dict = None,
        **kwargs,
    ):
        """
        Handle message from subject of Observer design pattern
        Args:
            caller (_type_, optional): Subject. Defaults to None.
            data_dict (List, optional): New data. Defaults to None.
        """
        # Watchdog will do its work if there is no data
        # ping around every 30 minutes
        if not data_dict and random.uniform(0, 360000) <= 2:
            if not self.is_redis_alive():
                logger.error("Failed to connect to Redis")

    def close(self):
        pass
