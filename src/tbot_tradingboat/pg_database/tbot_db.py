# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
import sqlite3

from loguru import logger


class TbotDatabase(ABC):
    """
    Base class for Sqlite3 database for Tbot
    """

    def __init__(self, conn=None, cursor=None):
        self.conn = conn
        self.cursor = cursor

    @abstractmethod
    def setup_connection(self, db_path: str, host=None, port=None):
        """Connect to sqlite3

        Args:
            db_path (str): the path to sqlite3 socket
            host (str): the hostname of the remote SQLite server
            port (int): the port number of the remote SQLite server
        """

    # Define a custom row factory that returns a dictionary for each row
    def dict_factory(self, cursor, row):
        """Define Custom row factory"""
        mdict = {}
        for idx, col in enumerate(cursor.description):
            mdict[col[0]] = row[idx]
        return mdict

    def _exec(self, sql_query, sql_data=None) -> List[Dict]:
        res = None
        if not self.conn:
            logger.error("Connection error: No connection available.")
            return res
        try:
            with self.conn:
                self.conn.row_factory = self.dict_factory
                cursor = self.conn.cursor()
                if sql_data:
                    cursor.execute(sql_query, sql_data)
                else:
                    cursor.execute(sql_query)
                res = cursor.fetchall()
        except sqlite3.Error as err:
            logger.error(f"{err}: {sql_query}")
            raise
        return res

    def create_trigger(
        self, table_name: str, key: str, max_records: int = 3600
    ) -> bool:
        """
        Creates the trigger for the given table that will delete old records
        when the table reaches a maximum size.

        :param table_name: The name of the table to create the trigger for
        :param max_records: The maximum number of records to keep in the table
        :return: True if the trigger was created successfully, False otherwise
        """
        sql_query = (
            f"CREATE TEMP TRIGGER TRIG_{table_name.upper()} "
            f"AFTER INSERT ON {table_name} "
            f"WHEN NEW.rowid % 64 == 0 "
            f"BEGIN "
            f"DELETE FROM {table_name} "
            f"WHERE {key} NOT IN (SELECT {key} FROM {table_name} "
            f"ORDER BY {key} DESC LIMIT {max_records}); "
            f"END;"
        )
        try:
            self._exec(sql_query)
            logger.trace(f"Created trigger for {table_name} database sqlite3")
            return True
        except sqlite3.Error as err:
            logger.exception(err)
            return False

    @abstractmethod
    def insert(self, unique_ts: str, obj: Any):
        """Insert object into the table with the key"""

    @abstractmethod
    def display(self):
        """Display Table"""

    def close(self):
        """Close connection to sqlite3"""
        if self.conn:
            self.conn.commit()
            if self.cursor:
                self.cursor.close()
            self.conn.close()
