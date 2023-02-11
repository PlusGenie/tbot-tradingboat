#!/usr/bin/env python3
"""
Plusgenie(c) 2023 All rights reserved.
"""
# -*- coding: utf-8 -*-
__author__ = "Sangwook Lee"
__copyright__ = "Copyright (C) 2023 Plusgenie Ltd"
__license__ = "Dual-Licensing (GPL or Commercial License)"


import asyncio
import json
import os
import sys
import ssl

from hashlib import md5
from typing import Dict, List, Optional, Tuple
from enum import Enum

import aiohttp

from dotenv import load_dotenv
from loguru import logger

from tbot_tradingboat.pg_database.orderdb import TbotOrderDB
from tbot_tradingboat.pg_database.alertdb import TbotAlertDB

from tbot_tradingboat.pg_decoder.ib_api.tbot_api import get_ordref_ex
from tbot_tradingboat.utils.objects import OrderKey, OrderKeyEx

# Set the default path to the .env file in the user's home directory
DEFAULT_ENV_FILE_PATH = os.path.expanduser("~/.env")
# Check if the .env file exists at the default path; if not, use the fallback path
if os.path.isfile(DEFAULT_ENV_FILE_PATH):
    ENV_FILE_PATH = DEFAULT_ENV_FILE_PATH
else:
    ENV_FILE_PATH = "/home/tbot/.env"
# Load the environment variables from the chosen .env file
load_dotenv(dotenv_path=ENV_FILE_PATH, override=True)

# Change the log levelfor loguru
logger.remove()
logger.add(sys.stderr, level=os.environ.get("TBOT_LOGLEVEL", "DEBUG"))

WEBSERVER = os.environ.get("TBOT_PYTEST_IPADDR", "http://localhost:5000/webhook")
UNIQUE_KEY = os.environ.get("TVWB_UNIQUE_KEY", "").strip()
TBOT_TVWB_EVENT = "WebhookReceived"
CLIENT_ID = int(os.environ.get("TBOT_IBKR_CLIENTID", "1").strip())


class DatabaseType(Enum):
    """
    An enumeration of database types.

    Attributes:
        ORDER_DB (str): Represents an order database.
        ALERT_DB (str): Represents an alert database.
    """

    ORDER_DB = "orderdb"
    ALERT_DB = "alertdb"


async def send_webhook(json_list: List, delay: float = 0.0) -> None:
    """
    Sends the list of JSON data to the Flask server.

    Args:
        json_list (List[Dict]): A list of dictionaries containing JSON data.
        delay (float, optional): The amount of delay in seconds. Defaults to 0.0.
    """
    # Create an SSL context with no certificate validation
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    ssl_context.verify_mode = ssl.CERT_NONE

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_context)
    ) as session:
        assert len(json_list) > 0, "No data for TV messages"
        for elm in json_list:
            webhook_url = WEBSERVER
            headers = {"content-type": "application/json"}
            async with session.post(webhook_url, data=elm, headers=headers) as resp:
                logger.debug(f"resp status:{resp.status}")
                logger.debug(await resp.text())
            await asyncio.sleep(delay)


async def send_single_webhook(json_data: Dict, delay: float = 0.0) -> None:
    """
    Sends the JSON data to the Flask server.

    Args:
        json_data (Dict): A dictionary containing JSON data.
        delay (float, optional): The amount of delay in seconds. Defaults to 0.0.
    """
    # Create an SSL context with no certificate validation
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    ssl_context.verify_mode = ssl.CERT_NONE

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_context)
    ) as session:
        assert json_data, "No data for TV messages"
        webhook_url = WEBSERVER
        headers = {"content-type": "application/json"}
        async with session.post(webhook_url, json=json_data, headers=headers) as resp:
            logger.debug(f"resp status:{resp.status}")
            logger.debug(await resp.text())
        await asyncio.sleep(delay)


def update_tvmsg_data(
    data_dict: Dict,
    new_timestamp: str = "",
    new_ord_ref: str = "",
    **kwargs: float,
) -> Dict:
    """
    Updates the TradingView message.

    Args:
        data_dict (Dict): The dictionary containing the TradingView message.
        new_timestamp (str, optional): The timestamp to be updated. Defaults to "".
        new_ord_ref (str, optional): The order reference to be updated. Defaults to "".
        kwargs (float, optional): The keyword arguments to update metrics values.

    Returns:
        Dict: The updated dictionary containing the TradingView message.
    """
    data_dict[
        "key"
    ] = f'{TBOT_TVWB_EVENT}:{md5(f"{TBOT_TVWB_EVENT + UNIQUE_KEY}".encode()).hexdigest()[:6]}'

    # Overwrite clientId
    data_dict["clientId"] = CLIENT_ID
    if new_timestamp:
        data_dict["timestamp"] = new_timestamp
    if new_ord_ref:
        data_dict["orderRef"] = new_ord_ref

    logger.debug(f'{data_dict["metrics"]}')
    for elm in data_dict["metrics"]:
        if "entry_limit" in kwargs and elm.get("name") == "entry.limit":
            elm["value"] = kwargs["entry_limit"]
        if "entry_stop" in kwargs and elm.get("name") == "entry.stop":
            elm["value"] = kwargs["entry_stop"]
        if "exit_limit" in kwargs and elm.get("name") == "exit.limit":
            elm["value"] = kwargs["exit_limit"]
        if "exit_stop" in kwargs and elm.get("name") == "exit.stop":
            elm["value"] = kwargs["exit_stop"]

    return data_dict


def update_tvmsg(
    file_path: str,
    timestamp: Optional[str] = None,
    newordref: Optional[str] = None,
    **kwargs,
) -> Tuple[Dict, OrderKey]:
    """
    Update a TradingView message with a new timestamp and/or order reference.

    Args:
        file_path (str): The path to the TradingView message file to be updated.
        timestamp (str, optional): The new timestamp for the TradingView message.
            Defaults to None.
        newordref (str, optional): The new order reference for the TradingView message.
            Defaults to None.

    Returns:
        Tuple[str, OrderKey]: A tuple containing the updated TradingView message as a JSON string
        and an OrderKey object used to look up a database.
    """
    try:
        logger.debug(f"Opening {file_path}")
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.loads(file.read())
            data = update_tvmsg_data(data, timestamp, newordref, **kwargs)
            ord_refex = get_ordref_ex(data["timeframe"], data["orderRef"])
            key = OrderKey(data["ticker"], ord_refex)
            logger.debug(f"Returning updated data: {json.dumps(data)}")
            return data, key
    except FileNotFoundError as err:
        logger.error(f"File not found: {file_path}, {err}")
        raise
    except json.JSONDecodeError as err:
        logger.error(f"Error decoding JSON from file {file_path}: {err}")
        raise


def open_tvmsg(
    file_paths: List[str] = None,
    message_list: List[str] = None,
    timestamp: Optional[str] = None,
    newordref: Optional[str] = None,
) -> List[OrderKey]:
    """
    Opens files and loads TradingView messages into `message_list`,
    updating the message if necessary.

    Args:
        file_paths (List[str], optional): A list of file paths to open.
            Defaults to None.
        message_list (List[str], optional):
            A list to which the loaded TradingView messages will be appended.
            Defaults to None.
        timestamp (str, optional): The timestamp to be updated
                in the TradingView message. Defaults to None.
        newordref (str, optional):
             The order reference to be updated in the TradingView message.
             Defaults to None.

    Returns:
        List[OrderKey]: A list of keys used to look up a database.
    """
    if file_paths is None:
        file_paths = []  # create a new empty list
    if message_list is None:
        message_list = []  # create a new empty list
    rval = []
    for file_path in file_paths:
        try:
            logger.debug(f"opening {file_path}")
            with open(file_path, "r", encoding="utf-8") as file:
                data = update_tvmsg_data(
                    data_dict=json.loads(file.read()),
                    new_timestamp=timestamp,
                    new_ord_ref=newordref,
                )
                ord_refex = get_ordref_ex(data["timeframe"], data["orderRef"])
                key = OrderKey(data["ticker"], ord_refex)
                logger.debug(f"appending {key}")
                rval.append(key)
                message_list.append(json.dumps(data))
        except FileNotFoundError as err:
            logger.error(f"File not found: {file_path}, {err}")
        except json.JSONDecodeError as err:
            logger.error(f"Error decoding JSON from file {file_path}: {err}")
    assert rval, f"No files given for open_tvmsg len={len(rval)}"
    return rval


def open_db(db_type: DatabaseType = DatabaseType.ORDER_DB) -> object:
    """
    Opens the specified database connection.

    Args:
        db_type (DatabaseType, optional):
            Type of database connection to be opened.
            Defaults to DatabaseType.ORDER_DB.

    Returns:
        object: The database connection object.
    """
    if db_type == DatabaseType.ORDER_DB:
        return open_orderdb()
    elif db_type == DatabaseType.ALERT_DB:
        return open_alertdb()
    else:
        raise ValueError(f"Invalid database type: {db_type}")


def open_orderdb() -> object:
    """Open the Order database connection"""
    dbase = TbotOrderDB()
    dbase.setup_connection(os.environ.get("TBOT_DB_OFFICE", "/run/tbot/tbot_sqlite3"))
    return dbase


def open_alertdb() -> object:
    """Open the Alert database connection"""
    dbase = TbotAlertDB()
    dbase.setup_connection(os.environ.get("TBOT_DB_OFFICE", "/run/tbot/tbot_sqlite3"))
    return dbase


def find_specified_orders(dbase: object, key: OrderKey, num: int) -> List[Dict]:
    """Find orders from order database using key, number"""
    data = {}
    if dbase:
        data = dbase.find_specified_orders(key, num)
    return data


def find_specified_order(dbase: object, key: OrderKey) -> Dict:
    """Find order from order database using key"""
    data = {}
    if dbase:
        data = dbase.find_specified_order(key)
    return data


def find_specified_done_order_by_type(dbase: object, key: OrderKeyEx) -> Dict:
    """Find order from order database using key"""
    data = {}
    if dbase:
        data = dbase.find_specified_done_order_by_type(key)
    return data


def find_specified_active_order_by_type(dbase: object, key: OrderKeyEx) -> Dict:
    """Find order from order database using key"""
    data = {}
    if dbase:
        data = dbase.find_specified_active_order_by_type(key)
    return data


def find_specified_cancelled_order_by_type(dbase: object, key: OrderKeyEx) -> Dict:
    """Find order from order database using key"""
    data = {}
    if dbase:
        data = dbase.find_specified_cancelled_order_by_type(key)
    return data


def find_specified_order_by_type(dbase: object, key: OrderKeyEx) -> Dict:
    """Find order with a specified orderType
    from order database using Extended Key
    """
    data = {}
    if dbase:
        data = dbase.find_specified_order_by_type(key)
    return data


def find_specified_filled_orders(dbase: object, key: OrderKey) -> Dict:
    """Find order from order database using key"""
    data = {}
    if dbase:
        data = dbase.find_specified_filled_orders(key)
    return data


def find_portfolio_info(dbase: object, key: OrderKey) -> Dict:
    """Find order from order database using key"""
    data = {}
    if dbase:
        data = dbase.find_portfolio_info(key)
    return data
