#!/usr/bin/env python3
# -*- coding: utf-8 -*-
__author__ = "Sangwook Lee"
__copyright__ = "Copyright (C) 2023 Plusgenie Ltd"
__license__ = "Dual-Licensing (GPL or Commercial License)"

"""
This is to simulator Tradingview indicators as generating WEBHOOKs
Plusgenie(c) 2023 All rights reserved.
"""


import json
import os
import sys
from redis import Redis
from dotenv import load_dotenv

from loguru import logger


# Change the log levelfor loguru
logger.remove()
logger.add(sys.stderr, level=os.environ.get("TBOT_LOGLEVEL", "INFO"))

# Set the default path to the .env file in the user's home directory
DEFAULT_ENV_FILE_PATH = os.path.expanduser("~/.env")

# Check if the .env file exists at the default path; if not, use the fallback path
if os.path.isfile(DEFAULT_ENV_FILE_PATH):
    ENV_FILE_PATH = DEFAULT_ENV_FILE_PATH
else:
    ENV_FILE_PATH = "/home/tbot/.env"

# Load the environment variables from the chosen .env file
load_dotenv(dotenv_path=ENV_FILE_PATH, override=True)


TV_WEBHOOK = {
    "timestamp": 1670712860260,
    "ticker": "TSLA",
    "timeframe": "D",
    "key": "WebhookReceived:8c43d5",
    "currency": "USD",
    "clientId": 1,
    "contract": "stock",
    "orderRef": "LOT1001",
    "direction": "strategy.entrylong",
    "metrics": [
        {"name": "entry.stop", "value": 0.0},
        {"name": "entry.limit", "value": 0.0},
        {"name": "exit.limit", "value": 180.00},
        {"name": "exit.stop", "value": 150.01},
        {"name": "qty", "value": 100},
    ],
}


class RedisStreamPub:
    """Redis Pub"""

    def __init__(self):
        self.connect_to_redis_stream_unix_domain()

    def connect_to_redis_stream_unix_domain(self):
        # Creating the Publisher
        self.redis_stream_key = os.getenv("REDIS_STREAM_KEY", "REDIS_SKEY_1")
        self.redis_stream_tb_key = os.getenv("REDIS_STREAM_TB_KEY", "tradingboat")
        hostname = os.getenv(
            "TBOT_REDIS_UNIXDOMAIN_SOCK", "/var/run/redis/redis-server.sock"
        )
        self.redis_channel = os.getenv("REDIS_CHANNEL", "REDIS_CH_99")
        self.redis_conn = Redis(
            unix_socket_path=hostname,
            # decode_responses=True,
            db=0,
        )

    def add_redis_stream(self, data_dict) -> str:
        """Add data to the stream"""
        logger.info("Producer: writing")
        stream_id = "0-0"
        if data_dict:
            # Create a bespoken dictionary for Redis Stream
            stream_dict = {self.redis_stream_tb_key: json.dumps(data_dict)}
            stream_id = self.redis_conn.xadd(self.redis_stream_key, stream_dict)
            logger.debug(
                f"---> pushed to redis, {self.redis_stream_key}:{self.redis_stream_tb_key}"
            )
        return stream_id


class RedisStreamSub:
    """Redis Sub"""

    def __init__(self):
        self.schema = None
        self.connect_to_redis_stream_unix_domain()

    def connect_to_redis_stream_unix_domain(self):
        logger.info("consumer: connecting")
        self.redis_stream_key = os.getenv("REDIS_STREAM_KEY", "REDIS_SKEY_1")
        self.redis_stream_tb_key = os.getenv("REDIS_STREAM_TB_KEY", "tradingboat")
        hostname = os.getenv(
            "TBOT_REDIS_UNIXDOMAIN_SOCK", "/var/run/redis/redis-server.sock"
        )
        self.redis_channel = os.getenv("REDIS_CHANNEL", "REDIS_CH_99")
        self.redis_conn = Redis(
            unix_socket_path=hostname,
            # decode_responses=True,
            db=0,
        )

    def read_redis_stream(self):
        """
        Suppposed that the earlist stream ID is 1670792643625-0'
        stream_id, count, block = ('$', None, 0) -> not work
        stream_id, count, block = ('1670792643625-0', None, 0) -> works: return all streams
            stream_id, count, block = (b'1670792643625-0', 1, 0) -> works
            '1670792643625-0' is the lastone,  return stream will be the next one after it
        stream_id, count, block = ('0-0', 1, 0) -> earlist stream
        """
        stream_id, count, block = (b"0-0", 1, 0)
        logger.info(f"Consumer: input stream_id {stream_id}")
        r_data = self.redis_conn.xread({self.redis_stream_key: stream_id}, count, block)
        if r_data:
            first_stream = r_data[0]
            fs_data_arr = first_stream[1]
            (stream_id, _value) = fs_data_arr[0]
            logger.info(f"first_stream:{first_stream}, stream_id:{stream_id}")


if __name__ == "__main__":
    producer = RedisStreamPub()
    consumer = RedisStreamSub()
    stream_id = producer.add_redis_stream(TV_WEBHOOK)
    consumer.read_redis_stream()
