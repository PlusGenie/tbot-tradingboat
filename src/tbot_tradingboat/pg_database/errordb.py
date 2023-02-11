# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
import sqlite3
from typing import List
from loguru import logger
import pandas as pd

from tbot_tradingboat.pg_decoder.ib_api.tbot_api import get_timestamp
from tbot_tradingboat.utils.objects import ErrorDBInfo
from .tbot_db import TbotDatabase


class TbotErrorDB(TbotDatabase):
    """
    Manage order information which is output of placing order onto IB/TWS
    """

    def __init__(self):
        self.conn = None
        self.cursor = None
        super().__init__(self.conn, self.cursor)
        self.host = None
        self.port = None

    def setup_connection(self, db_path: str, host=None, port=None):
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
        except sqlite3.Error as err:
            logger.error(f"{err}: {db_path}")
            raise
        sql_query = """
            CREATE TABLE IF NOT EXISTS TBOTERRORS (
                timestamp DATETIME DEFAULT(STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW')),
                reqid,
                errcode,
                symbol,
                errstr
            )
        """
        self._exec(sql_query)
        self.create_trigger("TBOTERRORS", "timestamp")
        logger.success("Connected to error database sqlit3")

    def insert(self, unique_ts: int, obj: ErrorDBInfo):
        """Insert error information into the table"""
        sql_query = """
            INSERT INTO TBOTERRORS (
                reqid,
                errcode,
                symbol,
                errstr
            ) VALUES (?, ?, ?, ?)
            """
        sql_data = (obj.reqId, obj.code, obj.ticker, obj.msg)
        self._exec(sql_query, sql_data)

    def display(self):
        """Display the Error table"""
        if self.conn is None:
            return
        sql_query = "SELECT * FROM TBOTERRORS ORDER BY timestamp DESC LIMIT 12"
        data_f = pd.read_sql_query(sql_query, self.conn)
        logger.trace("\n" + data_f.to_string())

    def find_error_by_uniquekey(self, unique: str) -> object:
        """
        Find an error by unique key
        """
        timestamp = get_timestamp(unique)
        logger.trace(f"find_order: {timestamp}")
        sql_query = "SELECT * FROM TBOTERRORS WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 1"
        sql_data = (timestamp,)
        rows = self._exec(sql_query, sql_data)
        logger.trace(f"find_order| {timestamp}, num:{len(rows)}")
        return rows[0] if len(rows) > 0 else None

    def find_errors_by_uniquekey(self, unique: str) -> List[object]:
        """
        Find errors by unique key
        """
        timestamp = get_timestamp(unique)
        logger.trace(f"find_order: {timestamp}")
        sql_query = (
            "SELECT * FROM TBOTERRORS WHERE timestamp > ? ORDER BY timestamp DESC"
        )
        sql_data = (timestamp,)
        rows = self._exec(sql_query, sql_data)
        logger.trace(f"find_order| {timestamp}, num:{len(rows)}")
        return rows if len(rows) > 0 else []
