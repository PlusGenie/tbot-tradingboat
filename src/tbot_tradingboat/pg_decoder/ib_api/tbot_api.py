# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
from datetime import datetime
from functools import wraps
from ib_insync import Contract
from loguru import logger
from tbot_tradingboat.utils.tbot_env import shared

TBOT_ORDERREF_MAX_LEN = 20
TBOT_ORDERREF_PREFIX = "C"
TBOT_ALL_CONTRACTS_NUM = -1e10
TBOT_CANCELLED_ORDER_MARK = -1e10
TBOT_NO_OPEN_POSITIONS = -1e10
TBOT_PORTFOLIO_ORDERREF_PREFIX = "Ptf_"
TBOT_PORTFOLIO_ORDERSTATUS = "Portfolio"
TBOT_PORTFOLIO_THRESHOLD_MS = 4 * 60 * 60 * 1000

# Use a unique orderRef to identify the order, rather than increasing the loopback counter
# TBOT_STRATEGY_CLOSE_ORDERDB_LOOPBACK. When strategy_close() is called,
# TBOT should look up how many filled orders to retrieve from the order database.
# Since we only need the latest filled order, the value of 1 is sufficient.
# If you need to retrieve more than one filled order,
# it may be better to use a unique orderRef in TradingView's webhook.
TBOT_STRATEGY_CLOSE_ORDERDB_LOOPBACK = 1


def mark(func):
    """
    Prints enter/exit messages for functions.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.trace(f"Entering {func.__name__}")
        out = func(*args, **kwargs)
        logger.trace(f"Exiting {func.__name__}")
        return out

    return wrapper


def get_ticker(contract: Contract) -> str:
    """Returns a consistent symbol across contracts."""
    ticker = "NOT_SUPPORT"
    if contract.secType == "STK":
        ticker = contract.symbol
    elif contract.secType == "CASH":
        ticker = contract.localSymbol.replace(".", "")
    return ticker


def get_ordref_ex_prefix() -> str:
    """
    Get prefix for the extented order reference.
    """
    client_id = shared.client_id
    return f"{TBOT_ORDERREF_PREFIX}{client_id}_"


def get_ordref_ex(timeframe: str = "", ord_ref: str = "") -> str:
    """
    Get the unique extended order reference for Order.orderRef
    """
    return f"{get_ordref_ex_prefix()}{timeframe}_{ord_ref}"


def get_timestamp(unique_ts: str) -> str:
    """Get timestamp for database"""
    dtime = datetime.fromtimestamp(int(unique_ts) / 1000.0)
    dtime_str = dtime.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return dtime_str
