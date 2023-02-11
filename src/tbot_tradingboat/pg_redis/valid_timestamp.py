# -*- coding: utf-8 -*-
""" Redis Subsriber & ib_insyc
Plusgenie(c) 2023
This is to run Redis Subscriber and then validate messages
"""


from pathlib import Path
from typing import Dict
from dataclasses import dataclass

import json
import jsonschema
from loguru import logger

from tbot_tradingboat.utils.tbot_env import shared
from tbot_tradingboat.utils.tbot_utils import strtobool


@dataclass
class RedisMessageValidator:
    """
    Validate Tradingview's messages againt JSON schema
    and also check the duplicated timestamps from NGROK

    The class is used to help development of redis pubsub/stream as ngrok replay packets
    """

    TBOT_JSON_SCHEMA = "alert_webhook_schema.json"

    def __init__(self):
        """Initialize a subscriber to Redis"""
        self.set_ts = set()
        self.set_size = 10000
        self.schema = None
        self.duplicated_ts = strtobool(shared.duplicated_ts)
        self.load_json_schema()

    def load_json_schema(self) -> bool:
        """Loads the JSON schema for Tradingview's JSON format"""
        path = Path(__file__).parent / RedisMessageValidator.TBOT_JSON_SCHEMA
        logger.trace(f"Schema: {path}")
        with path.open() as user_file:
            self.schema = json.loads(user_file.read())

    def is_valid_json_schema(self, data_dict: Dict) -> bool:
        """Validates Tradingview's JSON format"""
        if not self.schema:
            logger.error("Failed to load the schema")
            return False
        ret = False
        try:
            jsonschema.validate(data_dict, self.schema)
            logger.trace("Schema validation successful")
            ret = True
        except jsonschema.SchemaError as err:
            logger.error(f"Schema validation failed {err}")
        except jsonschema.ValidationError as err:
            logger.error(err)
        except BaseException as err:
            logger.error(err)
        return ret

    def validate_message(self, data_dict=None) -> dict:
        """
        Validate message w.r.t JSON schema and timestamp duplications

        data_dict: the message that has timestamp from Tradingview
        """
        if data_dict and not self.is_valid_json_schema(data_dict):
            return None
        ret = data_dict
        if self.duplicated_ts:
            if data_dict.get("timestamp"):
                _ts = data_dict["timestamp"]
                if _ts in self.set_ts:
                    logger.info(f"Ignoring duplicated msgs with timestamp: {_ts}")
                    ret = None
                else:
                    # Add the timestamp set
                    self.set_ts.add(_ts)
            else:
                logger.error(f"message formattimestamp is missing: {_ts}")
                ret = None
            #  Delete the timestamp set
            if len(self.set_ts) > self.set_size:
                logger.debug("clearing timestamp set")
                self.set_ts.clear()
        return ret
