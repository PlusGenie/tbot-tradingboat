# -*- coding: utf-8 -*-

"""
Tbot decodes TradingView webhook from Redis Pub/Sub and then send orders to ib_insyc
"""
__author__ = "Sangwook Lee"
__copyright__ = "Copyright (C) 2023 Plusgenie Ltd"
__license__ = "Dual-Licensing (GPL or Commercial License)"


import json
from typing import Tuple, Union
from dataclasses import dataclass

import redis
from loguru import logger

from tbot_tradingboat.utils.tbot_env import shared
from tbot_tradingboat.pg_decoder.ib_api.tbot_api import mark

from .valid_timestamp import RedisMessageValidator
from .listener import TbotListener


@dataclass
class TbotStream(TbotListener):
    """
    Suscriber as Redis Stream
    """

    REDIS_STREAM_KEY = "REDIS_SKEY_"
    REDIS_STREAM_TB_KEY = "tradingboat"

    def __init__(self):
        """Initialize a subscriber to redis"""
        self.dbase = None
        self.validts = RedisMessageValidator()
        self.id_last = 0
        self.r_skey = self.REDIS_STREAM_KEY + shared.client_id
        self.r_tb_key = self.REDIS_STREAM_TB_KEY
        self.pool = None
        self.r_read_timeout_ms = max(int(shared.r_read_timeout_ms), 1)

    def open(self):
        """Placeholder for Open"""
        logger.trace("open")

    def connect(self) -> bool:
        """
        Make a connection to Redis Stream

        Choose Redis Stream ID
            * 0 => Read the earlist stream
            * $ => Read the latest stream
        """
        try:
            self.id_last = 0
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
                conn_msg = f"Redis TCP: {shared.r_host}:{shared.r_port}"
            else:
                redis_url = f"unix://{shared.r_host_unix}"
                self.pool = redis.ConnectionPool.from_url(redis_url, **unix)
                conn_msg = f"Redis Unix Socket: {shared.r_host_unix}"

            logger.debug(f"connecting to Redis:{self.pool}")
            self.dbase = redis.Redis(connection_pool=self.pool)

            logger.success(
                f"Connected successfully to {conn_msg}"
                f", key: {self.r_skey}:{self.r_tb_key}",
            )
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
        Returns None if this is not valid pubsub messsage against JSON schema
        message: the encoded TradingView value in the 'decoded' Redis stream
        """
        if self.r_tb_key not in msg:
            logger.warning(f"No '{self.r_tb_key}' key found in message: {msg}")
            return None
        data_dict = json.loads(msg[self.r_tb_key])
        return self.validts.validate_message(data_dict)

    @mark
    def handle_event(self, caller) -> Tuple[str, str, str]:
        """
        Vadidates the message and then dispatch it to observers
        Assumes that the decoded channel is being used
        count
            None: receive the newest
            1   : receive one stream from the earlist available
        block
            None: non-blocking
            0   : blocking
            10  : 10 milliseconds blocking
        """
        if not self.dbase:
            return None, None, None

        id_stream, validated_message, id_curr = None, None, None
        earliest, count, block = ("0-0", 1, self.r_read_timeout_ms)
        try:
            data = self.dbase.xread({self.r_skey: earliest}, count, block)
        except UnicodeDecodeError as err:
            logger.critical(f"UnicodeDecodeError: {err}")
            self.delete_all()
            return None, None, None
        except redis.exceptions.ConnectionError as err:
            logger.warning(f"Redis connection error: {err}")
            logger.critical("Attempting to reconnect to Redis...")
            self.connect()  # try to reconnect to Redis
            return None, None, None

        if data:
            first_stream = data[0]
            fs_data_arr = first_stream[1]
            (id_curr, msg) = fs_data_arr[0]
            logger.trace(f"Received new stream ID: {id_curr}")
            validated_message = self.validate_message(msg)

            if validated_message:
                logger.debug(f"[Received validated message]: {validated_message}")
                # Get the timestamp from the Stream id of Redis
                id_stream = id_curr.split("-")[0]
                if id_curr == self.id_last:
                    logger.error(f"Received data but not consumed: {id_curr}")
            else:
                logger.warning(f"Deleting invalid stream: {id_curr}")
                self.delete(id_curr)
            # Update the next stream ID
            self.id_last = id_curr
        return id_stream, validated_message, id_curr

    def delete(self, redis_msg_id: Union[str, bytes]) -> None:
        """
        Deletes a Redis stream

        Args:
            redis_msg_id: The ID of the Redis stream to be deleted.
        """

        if isinstance(redis_msg_id, str):
            redis_msg_id = redis_msg_id.encode(encoding="UTF-8")
        logger.debug(f"Deleting Redis stream id: {redis_msg_id}")
        deleted_count = self.dbase.xdel(self.r_skey, redis_msg_id)
        if deleted_count == 1:
            logger.debug(f"Stream with ID {redis_msg_id.decode()} has been deleted.")
        else:
            logger.debug(f"No stream found with ID {redis_msg_id.decode()}.")

    def delete_all(self):
        """Delete all redis stream with Tradingboat channel"""
        chan = self.dbase.xread(streams={self.r_skey: 0})
        for streams in chan:
            stream_name, messages = streams
            # Delete all ids from the message list
            for i in messages:
                self.dbase.xdel(stream_name, i[0])

    def close(self):
        """Closes Redis connection"""
        if self.dbase:
            self.dbase.close()
            self.dbase = None
