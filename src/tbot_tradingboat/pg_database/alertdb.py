# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
import sqlite3
from typing import List, Dict

import pandas as pd
from loguru import logger

from tbot_tradingboat.pg_decoder.ib_api.tbot_api import get_timestamp
from tbot_tradingboat.utils.objects import (
    AlertDBInfo,
    OrderKey,
)
from .tbot_db import TbotDatabase


class TbotAlertDB(TbotDatabase):
    """
    Define database for TradingView Webhook (Alerts)
    """

    def __init__(self):
        self.conn = None
        self.cursor = None
        super().__init__(self.conn, self.cursor)
        self.host = None
        self.port = None

    def setup_connection(self, db_path, host=None, port=None):
        """
        Connect to sqlite3

        Args:
            db_path (str): the path to sqlite3 socket
            host (str): the hostname of the remote SQLite server
            port (int): the port number of the remote SQLite server
        """
        try:
            if host and port:
                self.conn = sqlite3.connect(f"sqlite://{host}:{port}/{db_path}")
                self.host = host
                self.port = port
            else:
                self.conn = sqlite3.connect(db_path)
            self.cursor = self.conn.cursor()

            # Retrieve the page size of the database in bytes
            page_size_query = "PRAGMA page_size;"
            page_size = self.conn.execute(page_size_query).fetchone()[0]

            # Set the cache size to 32MB (in bytes)
            cache_size = 32 * 1024 * 1024

            # Calculate the number of pages in the cache
            num_cache_pages = cache_size // page_size

            # Set the cache size using PRAGMA cache_size
            cache_size_query = f"PRAGMA cache_size = {-num_cache_pages};"
            self._exec(cache_size_query)

        except sqlite3.Error as err:
            logger.error(f"{err}: {db_path}")
            raise
        sql_query = """
            CREATE TABLE IF NOT EXISTS TBOTALERTS (
                timestamp DATETIME DEFAULT(STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW')),
                uniquekey,
                tv_timestamp,
                ticker,
                direction,
                timeframe,
                qty,
                orderref,
                alertstatus,
                entrylimit,
                entrystop,
                exitlimit,
                exitstop,
                tv_price
            )
        """
        self._exec(sql_query)

        # create an index on uniquekey
        sql_query = "CREATE INDEX IF NOT EXISTS alert_index ON TBOTALERTS(uniquekey);"
        self._exec(sql_query)

        self.create_trigger("TBOTALERTS", "uniquekey")
        logger.success("Connected to Alert Database sqlit3")

    def insert(self, unique_ts: str, obj: AlertDBInfo):
        sql_query = """
            INSERT INTO TBOTALERTS (
                uniquekey,
                tv_timestamp,
                ticker,
                direction,
                timeframe,
                qty,
                orderref,
                alertstatus,
                entrylimit,
                entrystop,
                exitlimit,
                exitstop,
                tv_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        uniq_t = get_timestamp(unique_ts)
        tv_t = get_timestamp(obj.timestamp)
        sql_data = (
            uniq_t,
            tv_t,
            obj.ticker,
            obj.direction,
            obj.timeframe,
            obj.qty,
            obj.orderRef,
            obj.alertStatus,
            obj.entryLimit,
            obj.entryStop,
            obj.exitLimit,
            obj.exitStop,
            obj.tv_price,
        )
        self._exec(sql_query, sql_data)

    def find_specified_orders(self, key: OrderKey, num: int) -> List[Dict]:
        """
        Find N specified orders in the order table.
        """
        if self.conn:
            logger.debug(f"find_specified_orders: {key.symbol}, {key.orderRef}")
            sql_query = (
                "SELECT * FROM TBOTALERTS WHERE (ticker=? and orderref=?) "
                "ORDER BY uniquekey DESC LIMIT ?"
            )
            sql_data = (key.symbol, key.orderRef, num)
            rows = self._exec(sql_query, sql_data)
            if len(rows) > 0:
                logger.trace(f"ask:{num},got:{len(rows)}")
                return rows
        else:
            logger.error("find_specified_orders: database connection is not ready.")
        return []

    def find_specified_order(self, key: OrderKey) -> Dict:
        """
        Find the specified order in the order table.
        """
        rval = self.find_specified_orders(key, 1)
        return rval[0] if rval else {}

    def display(self):
        """Display the Alert table"""
        if self.conn is None:
            return
        sql_query = "SELECT * FROM TBOTALERTS ORDER BY uniquekey DESC LIMIT 12"
        data_f = pd.read_sql_query(sql_query, self.conn)
        logger.debug("\n" + data_f.to_string())
