# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
import sys
import traceback
import time
from typing import List, Dict

import sqlite3
from loguru import logger
import pandas as pd

from ib_insync import (
    OrderStatus,
)

from tbot_tradingboat.utils.objects import (
    OrderDBInfo,
    OrderKey,
    OrderKeyEx,
)
from tbot_tradingboat.pg_decoder.ib_api.tbot_api import (
    get_timestamp,
    TBOT_PORTFOLIO_ORDERSTATUS,
    TBOT_PORTFOLIO_ORDERREF_PREFIX,
    TBOT_NO_OPEN_POSITIONS,
    TBOT_CANCELLED_ORDER_MARK,
    TBOT_PORTFOLIO_THRESHOLD_MS,
)

from .tbot_db import TbotDatabase

UNSET_DOUBLE = sys.float_info.max


class TbotOrderDB(TbotDatabase):
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

            # Set cache size to 10,000 pages: 40 Mbytes
            self.conn.execute("PRAGMA cache_size = 10000")
            self.cursor = self.conn.cursor()
        except sqlite3.Error as err:
            logger.error(f"{err}: {db_path}")
            raise

        sql_query = """
        CREATE TABLE IF NOT EXISTS TBOTORDERS (
            timestamp DATETIME DEFAULT(STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW')),
            uniquekey,
            tv_price,
            orderid,
            ticker,
            action,
            ordertype,
            lmtprice,
            auxprice,
            qty,
            avgfillprice,
            orderstatus,
            orderref,
            parentid,
            position,
            mrkvalue,
            avgprice,
            unrealizedpnl,
            realizedpnl
        )"""
        self._exec(sql_query)

        # create an index on ticker and orderref columns
        sql_query = (
            "create index if not exists idx_tbotorders_ticker_orderref "
            "on TBOTORDERS (ticker, orderref)"
        )
        self._exec(sql_query)

        self.create_trigger("TBOTORDERS", "uniquekey")
        self.delete_stale_portfolio()
        logger.success("Connected to Order Database sqlit3")

    def insert(self, unique_ts, obj: OrderDBInfo):
        """Insert a new entry into TBOTORDERS"""
        sql_query = """
        INSERT INTO TBOTORDERS (
            uniquekey,
            tv_price,
            orderid,
            ticker,
            action,
            ordertype,
            lmtprice,
            auxprice,
            qty,
            avgfillprice,
            orderstatus,
            orderref,
            parentid,
            position,
            mrkvalue,
            avgprice,
            unrealizedpnl,
            realizedpnl
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ? ,?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        sql_data = (
            unique_ts,
            obj.tvPrice,
            obj.orderId,
            obj.ticker,
            obj.action,
            obj.orderType,
            obj.lmtPrice,
            obj.auxPrice,
            obj.qty,
            obj.avgfillprice,
            obj.orderStatus,
            obj.orderRef,
            obj.parentOrderId,
            0,
            0,
            0,
            0,
            0,
        )
        self._exec(sql_query, sql_data)

    def query_n_fetch(self, sql_query, sql_data=None) -> List[object]:
        """
        Query sqlite3 and then get results by Row Factory
        Note that the database should be opened by connect_rowfactory()
        """
        ret = []
        if self.conn is None:
            return
        try:
            values = None
            if sql_data:
                values = self.cursor.execute(sql_query, sql_data).fetchall()
            else:
                values = self.cursor.execute(sql_query).fetchall()
            # Insert needs commit
            self.conn.commit()
            ret = [{k: item[k] for k in item.keys()} for item in values]
        except sqlite3.Error as err:
            logger.error(f"SQL: {sql_query}")
            logger.error(f"SQLite error: {err.args}")
            logger.error("Exception class is: ", err.__class__)
            logger.error("SQLite traceback: ")
            exc_type, exc_value, exc_tb = sys.exc_info()
            logger.error(traceback.format_exception(exc_type, exc_value, exc_tb))
            self.conn.close()
            ret = []
        return ret

    def connect_rowfactory(self, db_path: str):
        """
        Open database by readonly using Row Factory
        """
        try:
            addr = "file:" + db_path + "?mode=ro"
            self.conn = sqlite3.connect(addr, uri=True)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()
            logger.success("Connected to Order Database(Readonly)")
        except sqlite3.Error as err:
            logger.error(err)
            raise

    def find_specified_orders(self, key: OrderKey, num: int) -> List[Dict]:
        """
        Find N specified orders in the order table.
        """
        if self.conn:
            logger.debug(f"find_specified_orders: {key.symbol}, {key.orderRef}")
            sql_query = (
                "SELECT * FROM TBOTORDERS WHERE (ticker=? and orderref=?) "
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

    def find_portfolio_info(self, key: OrderKey) -> Dict:
        """
        Find the specified order in the order table.
        """
        new = key._replace(orderRef=TBOT_PORTFOLIO_ORDERREF_PREFIX + key.symbol)
        rval = self.find_specified_orders(new, 1)
        return rval[0] if rval else {}

    def find_specified_state_order(
        self, key: OrderKeyEx, states: OrderStatus.DoneStates
    ) -> Dict:
        """
        Finds an order by key whose status is either PendingSubmit,
            ApiPending, PreSubmitted, or Submitted.

        Args:
            key (OrderKey): The OrderKey to search for.

        Returns:
            Dict: The order with the specified key and status is found,
            {}: otherwise.
        """
        if not self.conn:
            logger.error("db: connection is not ready")
            return {}

        logger.debug(f"order: {key.symbol}, {key.orderRef}")
        sql_query = (
            "SELECT * FROM TBOTORDERS "
            "WHERE (ticker=? AND orderref=? AND ordertype=? AND action=?) "
            "ORDER BY uniquekey DESC LIMIT 3"
        )
        sql_data = (key.symbol, key.orderRef, key.orderType, key.action)
        rows = self._exec(sql_query, sql_data)
        for row in rows:
            if row["orderstatus"] in states:
                logger.debug(
                    f"Found, orderID:{row['orderid']}, "
                    f"status:{row['orderstatus']}, type:{row['ordertype']}",
                )
                return row

        return {}

    def find_specified_done_order_by_type(self, key: OrderKeyEx) -> Dict:
        """
        Finds orders by key whose status is done
        """
        logger.debug(f"order: {key.symbol}, {key.orderRef}")
        return self.find_specified_state_order(key, OrderStatus.DoneStates)

    def find_specified_cancelled_order_by_type(self, key: OrderKeyEx) -> Dict:
        """
        Finds orders in the cancel transition by key.
        The statuses depend on the time this function is called.
        """
        #  Cancel transition will include statuses like the following.

        cancel_transition = {
            OrderStatus.PendingCancel,
            OrderStatus.PreSubmitted,
            OrderStatus.Submitted,
            OrderStatus.Cancelled,
        }
        return self.find_specified_state_order(key, cancel_transition)

    def find_specified_active_order_by_type(self, key: OrderKeyEx) -> Dict:
        """
        Finds orders by key whose status is either PendingSubmit,
            ApiPending, PreSubmitted, or Submitted.
        """
        return self.find_specified_state_order(key, OrderStatus.ActiveStates)

    def find_filled_orders_qty_by_key(self, key: OrderKey, num: int) -> float:
        """
        Find specified orders filled by key and then return total qty size

        Note that filled orders uses `Position` as the filled qty
        """
        rows = self.find_specified_filled_orders(key, num)
        total_position = 0.0
        for row in rows:
            total_position += (
                row["position"] * -1 if row["action"] == "SELL" else row["position"]
            )
        if len(rows) > 0:
            logger.debug(
                f"Found {len(rows)} filled orders for {key.symbol}, {key.orderRef}"
            )
            return total_position
        logger.debug(f"No filled orders found for {key.symbol}, {key.orderRef}")
        return TBOT_NO_OPEN_POSITIONS

    def find_specified_order_by_type(self, key: OrderKeyEx) -> Dict:
        """
        Find the specified order using OrderKeyEx in the order table
        """
        if not self.conn:
            logger.error("db: connection is not ready")
            return {}

        logger.trace(f"find_order: {key.symbol}, {key.orderRef}")
        if key.orderId > 0:
            sql_query = (
                "SELECT * FROM TBOTORDERS "
                "WHERE (ticker=? AND orderref=? AND action=? AND ordertype=? AND orderid=?) "
                "ORDER BY uniquekey DESC LIMIT 1"
            )
            sql_data = (
                key.symbol,
                key.orderRef,
                key.action,
                key.orderType,
                key.orderId,
            )
        else:
            sql_query = (
                "SELECT * FROM TBOTORDERS "
                "WHERE ticker=? AND orderref=? AND action=? AND ordertype=? "
                "ORDER BY uniquekey DESC LIMIT 1"
            )
            sql_data = (key.symbol, key.orderRef, key.action, key.orderType)
        rows = self._exec(sql_query, sql_data)
        logger.trace(f"find_order| row:{rows}")

        return rows[0] if rows else {}

    def find_specified_filled_orders(self, key: OrderKey, num: int) -> List[Dict]:
        """
        Finds filled orders by key whose status is filled
        Args:
            key (OrderKey): The OrderKey to search for.
        Returns:
            list of Dict: The order with the specified key and status is found,
            []: otherwise.
        """
        results = []
        if self.conn:
            sql_query = (
                "SELECT * FROM TBOTORDERS "
                "WHERE (ticker=? AND orderref=?) "
                "ORDER BY uniquekey DESC LIMIT ?"
            )
            sql_data = (key.symbol, key.orderRef, num)
            rows = self._exec(sql_query, sql_data)
            logger.debug(
                f"order: {key.symbol}, {key.orderRef}, loopback:{num}, rows:{len(rows)}"
            )
            for row in rows:
                if row["orderstatus"] == OrderStatus.Filled:
                    logger.debug(
                        f"Found, filled, :{row['orderid']}, status:{row['orderstatus']}"
                    )
                    results.append(row)
                elif row["qty"] == row["position"]:
                    # Sometimes, position is updated faster than orderstatus
                    logger.info(
                        f"Found, filled :{row['orderid']}, {row['qty']}={row['position']}"
                    )
                    results.append(row)
        else:
            logger.error("Database connection is not ready")
        return results

    def find_order_by_unique_key(self, unique_key: str) -> Dict:
        """
        Find an order in the TBOTORDERS table by its unique key.

        The unique key is a timestamp that is shared between the alert database and order database.
        If the timestamp is not available from the Redis stream, it will be created on the fly.
        If there is no sqlite3 database when TBOT boots up, it will create open orders from events
        and generate a new timestamp as well.

        This function can be used by an observer to easily access the alert and order database.

        Args:
            unique_key (str): The unique key of the order.

        Returns:
            dict: A dictionary containing information about the order, or an empty one if not found.
        """
        timestamp = get_timestamp(unique_key)
        sql_query = (
            "SELECT * FROM TBOTORDERS WHERE uniquekey=? ORDER BY uniquekey DESC LIMIT 1"
        )
        sql_data = (timestamp,)
        rows = self._exec(sql_query, sql_data)
        logger.debug(f"{unique_key} (UTC) -> {timestamp}: {rows}")
        return rows[0] if rows else {}

    def find_order_by_ord_id(self, ord_id: int) -> Dict:
        """
        Find an order by orderId

        Args:
            ord_id (int): The orderId of the order to be found.

        Returns:
            dict: A dictionary containing information about the order, or an empty one if not found.
        """
        if self.conn:
            sql_query = "SELECT * FROM TBOTORDERS WHERE orderid = ?"
            sql_data = (ord_id,)
            rows = self._exec(sql_query, sql_data)
            logger.debug(f"find_order| rows:{rows}")
            return rows[0] if rows else {}
        else:
            logger.error("db: connection not ready")
            return {}

    def find_order_exists_by_ord_id(self, ord_id: int) -> bool:
        """
        Find an order by orderId
        """
        if self.conn:
            sql_query = "SELECT EXISTS(SELECT 1 FROM TBOTORDERS WHERE orderid = ?)"
            sql_data = (ord_id,)
            result = self._exec(sql_query, sql_data)
            row_exists = bool(
                result[0]["EXISTS(SELECT 1 FROM TBOTORDERS WHERE orderid = ?)"]
            )
            logger.debug(f"find_order| row_exists:{row_exists}")
            return row_exists
        else:
            logger.error("db: connection not ready")
            return False

    def find_position_size_by_key(self, key: OrderKey) -> float:
        """Find position size of portfolio in order tables"""
        sql_query = (
            "SELECT position FROM TBOTORDERS WHERE (ticker=? and orderstatus=?) "
            "ORDER BY uniquekey DESC LIMIT 1"
        )
        sql_data = (key.symbol, TBOT_PORTFOLIO_ORDERSTATUS)
        rows = self._exec(sql_query, sql_data)
        logger.debug(f"find_order| {sql_data}, row:{rows}")
        if rows:
            logger.trace(f"size_by_key| {sql_data}, row:{rows[0]}")
            return rows[0]["position"]
        else:
            logger.debug(f"No rows found for {key.symbol}")
            return TBOT_NO_OPEN_POSITIONS

    def update_portfolio(
        self,
        unique_ts,
        order: OrderDBInfo,
        market_val: float,
        unreal_pnl: float,
        realized_pnl: float,
    ):
        """
        Update the most recent portfolio for the symbol
        """
        sql_query = (
            "UPDATE TBOTORDERS SET "
            "uniquekey=?,tv_price=?,position=?,avgfillprice=?,mrkvalue=?, "
            "unrealizedpnl=?,realizedpnl=? "
            "WHERE ROWID IN "
            "(SELECT ROWID FROM TBOTORDERS WHERE (ticker=? and orderref=? and action=?) "
            "ORDER BY uniquekey DESC LIMIT 1)"
        )
        sql_data = (
            unique_ts,
            order.tvPrice,
            order.position,
            order.avgfillprice,
            market_val,
            unreal_pnl,
            realized_pnl,
            order.ticker,
            order.orderRef,
            order.action,
        )
        self._exec(sql_query, sql_data)

    def update_portfolio_position(
        self,
        ticker: str,
        ord_ref: str,
        action: str,
        position: float,
    ) -> None:
        """
        Update the portfolio position.

        Args:
            ticker (str): The ticker symbol for the position to be updated.
            ord_ref (str): The order reference for the position to be updated.
            action (str): The action of the position to be updated.
            position (float): The new position value.

        Returns:
            None
        """
        sql_query = (
            "UPDATE TBOTORDERS SET position=? "
            "WHERE ROWID IN (SELECT ROWID FROM TBOTORDERS "
            "WHERE (ticker=? and orderref=? and action=?) "
            "ORDER BY uniquekey DESC LIMIT 1)"
        )
        sql_data = (
            position,
            ticker,
            ord_ref,
            action,
        )
        self._exec(sql_query, sql_data)

    def delete_stale_portfolio(self) -> None:
        """Delete stale portfolio older than threshold_ms"""
        # Calculate the unique timestamp by subtracting the threshold
        # from the current time (in milliseconds)
        unique_ts = str((time.time_ns() // 1000000) - TBOT_PORTFOLIO_THRESHOLD_MS)
        timestamp = get_timestamp(unique_ts)
        sql_query = "DELETE from TBOTORDERS WHERE orderstatus = ? and uniquekey < ? "
        sql_data = (TBOT_PORTFOLIO_ORDERSTATUS, timestamp)
        self._exec(sql_query, sql_data)
        logger.debug(f"Total number of rows deleted :{self.conn.total_changes}")

    def update_cancelled_order(self, ord_id: int) -> bool:
        """Track cancelled order until orderstatus is updated during trading hours

        This is the check whether TBOT has placed a cancel order on the existing one.
        It takes the current tv_price and updates it based on the following rules:
        If tv_price is greater than 0, it will set to the minus value of that price.
        If tv_price is zero, it will set to -1e10.

        Args:
            ord_id (int): The order ID to be updated.
        """
        order = self.find_order_by_ord_id(ord_id)
        if not order:
            return False
        tv_price = order["tv_price"]
        # Calculate the new value of tv_price
        new_tv_price = -tv_price if tv_price > 0 else TBOT_CANCELLED_ORDER_MARK
        # Update the tv_price in the database
        sql_query = "UPDATE TBOTORDERS SET tv_price=? WHERE orderid=?"
        sql_data = (new_tv_price, ord_id)
        self._exec(sql_query, sql_data)

        return True

    def update_order_status(self, order: OrderDBInfo):
        """Update order into the table on orderStatusEvent

        Note that it uses `POSITION` as `filled` in case of a normal order
        """
        # Donot update order status with invalid prices

        if all(
            price != UNSET_DOUBLE and price != 0.0
            for price in [order.lmtPrice, order.auxPrice]
        ):
            sql_query = (
                "UPDATE TBOTORDERS "
                "SET qty=?,lmtprice=?,auxprice=?,avgfillprice=?,position=?,orderstatus=? "
                "WHERE orderid=?"
            )
            sql_data = (
                order.qty,
                order.lmtPrice,
                order.auxPrice,
                order.avgfillprice,
                order.position,
                order.orderStatus,
                order.orderId,
            )
        elif order.lmtPrice != UNSET_DOUBLE and order.lmtPrice != 0:
            sql_query = (
                "UPDATE TBOTORDERS "
                "SET qty=?,lmtprice=?,avgfillprice=?,position=?,orderstatus=? "
                "WHERE orderid=?"
            )
            sql_data = (
                order.qty,
                order.lmtPrice,
                order.avgfillprice,
                order.position,
                order.orderStatus,
                order.orderId,
            )
        elif order.auxPrice != UNSET_DOUBLE and order.auxPrice != 0:
            sql_query = (
                "UPDATE TBOTORDERS "
                "SET qty=?,auxprice=?,avgfillprice=?,position=?,orderstatus=? "
                "WHERE orderid=?"
            )
            sql_data = (
                order.qty,
                order.auxPrice,
                order.avgfillprice,
                order.position,
                order.orderStatus,
                order.orderId,
            )
        else:
            logger.debug(f"ignoring invalid lmt={order.lmtPrice},aux={order.auxPrice}")
            sql_query = (
                "UPDATE TBOTORDERS "
                "SET qty=?,avgfillprice=?,position=?,orderstatus=? "
                "WHERE orderid=?"
            )
            sql_data = (
                order.qty,
                order.avgfillprice,
                order.position,
                order.orderStatus,
                order.orderId,
            )
        self._exec(sql_query, sql_data)

    def display(self):
        """Display the Order table"""
        if self.conn is None:
            return
        sql_query = "SELECT * FROM TBOTORDERS ORDER BY uniquekey DESC LIMIT 12"
        data_f = pd.read_sql_query(sql_query, self.conn)
        logger.debug("\n" + data_f.to_string())
