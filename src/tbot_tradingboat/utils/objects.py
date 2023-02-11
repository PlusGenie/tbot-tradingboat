# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.

This file holds NamedTuple to hold data for TBOT
"""
import os
from typing import NamedTuple
from dataclasses import dataclass, field
from functools import partial, lru_cache
from enum import Enum


@dataclass(frozen=True)
class EnvSettings:
    """
    Create NamedTuple to read Environment Values
    """

    # ---------------------------------
    # Interactive Brokers
    # ---------------------------------
    client_id: str = field(
        default_factory=partial(os.environ.get, "TBOT_IBKR_CLIENTID", "1")
    )
    ibkr_port: str = field(
        default_factory=partial(os.environ.get, "TBOT_IBKR_PORT", "4002")
    )
    ibkr_addr: str = field(
        default_factory=partial(os.environ.get, "TBOT_IBKR_IPADDR", "127.0.0.1")
    )

    # ---------------------------------
    # Redis database
    # ---------------------------------
    r_passwd: str = field(
        default_factory=partial(os.environ.get, "TBOT_REDIS_PASSWORD", "")
    )
    r_host_unix: str = field(
        default_factory=partial(os.environ.get, "TBOT_REDIS_UNIXDOMAIN_SOCK", "")
    )
    r_host: str = field(
        default_factory=partial(os.environ.get, "TBOT_REDIS_HOST", "127.0.0.1")
    )
    r_port: str = field(
        default_factory=partial(os.environ.get, "TBOT_REDIS_PORT", "6379")
    )
    r_is_stream: str = field(
        default_factory=partial(os.environ.get, "TBOT_USES_REDIS_STREAM", "True")
    )
    r_read_timeout_ms: str = field(
        default_factory=partial(os.environ.get, "TBOT_REDIS_READ_TIMEOUT_MS", "40")
    )
    # ---------------------------------
    # SQLite3 Database
    # ---------------------------------
    db_home: str = field(
        default_factory=partial(
            os.environ.get, "TBOT_DB_HOME", "/home/tbot/tbot_sqlite3"
        )
    )
    db_office: str = field(
        default_factory=partial(
            os.environ.get, "TBOT_DB_OFFICE", "/home/tbot/tbot_sqlite3"
        )
    )
    # ---------------------------------
    # Messaging Apps: Discord
    # ---------------------------------
    discord_webhook: str = field(
        default_factory=partial(os.environ.get, "TBOT_DISCORD_WEBHOOK", "")
    )

    # ---------------------------------
    # Messaging Apps: Telegram
    # ---------------------------------
    telegram_token: str = field(
        default_factory=partial(os.environ.get, "TBOT_TELEGRAM_TOKEN", "")
    )
    telegram_chat_id: str = field(
        default_factory=partial(os.environ.get, "TBOT_TELEGRAM_CHAT_ID", "")
    )

    # ---------------------------------
    # Check duplications of timestamp
    # ---------------------------------
    duplicated_ts: str = field(
        default_factory=partial(
            os.environ.get, "TBOT_VALIDATE_TIMESTAMP_DUPLICATES", "False"
        )
    )

    # ---------------------------------
    # Watchdog
    # ---------------------------------
    watch_ts: str = field(
        default_factory=partial(os.environ.get, "TBOT_WATCHDOG_USEC", "300000000")
    )

    # ---------------------------------
    # Loglevel
    # ---------------------------------
    loglevel: str = field(
        default_factory=partial(os.environ.get, "TBOT_LOGLEVEL", "INFO")
    )
    logfile: str = field(
        default_factory=partial(
            os.environ.get, "TBOT_LOGFILE", "/home/tbot/tbot_log.txt"
        )
    )
    # loglovel for IB INSYNC
    ib_loglevel: str = field(
        default_factory=partial(os.environ.get, "TBOT_IB_LOGLEVEL", "INFO")
    )

    # ---------------------------------
    # Enable TBOT Profiler
    # ---------------------------------
    profiler: str = field(
        default_factory=partial(os.environ.get, "TBOT_PROFILER", "False")
    )

    @lru_cache
    def __new__(cls) -> object:
        return super().__new__(cls)


class PnL2Contract(NamedTuple):
    """
    Create NamedTuple to work with PnL
    """

    symbol: str
    conId: int


class OrderTV(NamedTuple):
    """
    Create NamedTuple for Orders which is needed to place orders onto IB/TWS
    """

    uniqueKey: str
    timestamp: str
    contract: str
    symbol: str
    timeframe: str
    action: str
    qty: float
    currency: str
    entryLimit: float
    entryStop: float
    exitLimit: float
    exitStop: float
    # TradingView's close price of the bar
    price: float
    orderRef: str
    tif: str


class OrderDBInfo(NamedTuple):
    """
    Create NamedTuple for save results of placing orders to IB/TWS
    """

    tvPrice: float
    orderId: int
    ticker: str
    action: str
    orderType: str
    qty: float
    avgfillprice: float
    orderStatus: str
    orderRef: str
    parentOrderId: int = 0
    lmtPrice: float = 0.0  # Limit Price
    auxPrice: float = 0.0  # stopPrice
    # Either number for filled orders Or number of positions for portfolio
    position: int = 0


class AlertDBInfo(NamedTuple):
    """
    Create NamedTuple for save webhook received from TradingView

    """

    timestamp: str
    ticker: str
    alertStatus: str = ""
    direction: str = ""
    timeframe: str = ""
    orderRef: str = ""
    qty: float = 0.0
    entryLimit: float = 0.0
    entryStop: float = 0.0
    exitLimit: float = 0.0
    exitStop: float = 0.0
    tv_price: float = 0.0


class ErrorDBInfo(NamedTuple):
    """
    Create NamedTuple for save error message to report to a remote server
    """

    unique: str
    reqId: float
    code: int
    ticker: str
    msg: str


class OrderKey(NamedTuple):
    """
    Create Key to search fields from Order Database
    """

    symbol: str
    orderRef: str = "notUsed"


class OrderKeyEx(NamedTuple):
    """
    Create Key to search fields from Order Database
    """

    symbol: str
    orderRef: str
    orderType: str  # LMT or MKT, STP
    action: str = ""  # BUY or SELL
    orderId: int = -1  # invalid orderId


class ErrorStates(Enum):
    """Define state of handling Alerts"""

    UNRECOG = 0
    CANCELLED = 1
    SUBMITTED = 2
    ENOCNTR = 4  # No SecType
    ECALCQTY = 5  # only strategy_close() and strategy_exit()
    EBADMSG = 6  # Invalid message format in Tradingview's webhook
    ENOCLSPOS = 7  # No position to close
    ENENTPOSDB = 8  # No entry position in DB for strategy_close/cancel
    E2BIGQTY = 9  # Error in calculating qty for for strategy_close()
    EBADORDTP = 10  # Invalid Order Type
    ENOTSUP = 11  # Not supported
    ENOENTRDB = 12  # No order in DB for strategy_exit
    ENOACTV = 13  # Cannot update orders in DoneState for bracket orders
    ENOPARFL = 14  # Parent's order is not filled in bracket order
    EDUPORD = 15  # Duplicated orders
    ENOOPNTRD = 16  # No open trade
    ENOMKTPOSDB = 17  # No position to make flat in strategy_close_all
