# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
from typing import Dict, Tuple
import logging
import os
import sys
import errno

import socket
import time
import shutil
import re
from dataclasses import dataclass
import sqlite3

from ib_insync import util, IB, OrderStatus
from loguru import logger
import numpy as np

from tbot_tradingboat.pg_database.alertdb import TbotAlertDB
from tbot_tradingboat.pg_database.orderdb import TbotOrderDB
from tbot_tradingboat.pg_database.errordb import TbotErrorDB
from tbot_tradingboat.utils.tbot_env import shared
from tbot_tradingboat.utils.objects import OrderTV, AlertDBInfo, ErrorStates
from tbot_tradingboat.utils.constants import TBOT_PUT_REDIS_EVENT_SLEEP_SEC
from tbot_tradingboat.pg_decoder.ib_api.tbot_api import (
    get_ordref_ex,
    get_ordref_ex_prefix,
    get_ticker,
    mark,
    TBOT_ORDERREF_MAX_LEN,
    TBOT_ALL_CONTRACTS_NUM,
    TBOT_STRATEGY_CLOSE_ORDERDB_LOOPBACK,
)
from tbot_tradingboat.utils.tbot_utils import strtobool

from .ib_api.tbot_order import TbotOrder
from .tbot_observer import TbotObserver


@dataclass
class TBOTDecoder(TbotObserver):
    """
    The Observer interface declares the update method, used by subjects.
    """

    def __init__(self):
        """Initialize ib_insync"""
        self.ibsyn = IB()
        self.ibsyn.client.apiError += self.on_api_error
        self.ib_enable_log(shared.ib_loglevel)
        self.orderdb = TbotOrderDB()
        self.alertdb = TbotAlertDB()
        self.errordb = TbotErrorDB()
        self.torder = TbotOrder(self.ibsyn, self.orderdb, self.errordb)
        self.loop = None
        self.profiler = strtobool(shared.profiler)

    def open(self):
        try:
            self._copy_sqlite3_to_dest(shared.db_office, shared.db_home)
            self.orderdb.setup_connection(shared.db_office)
            self.alertdb.setup_connection(shared.db_office)
            self.errordb.setup_connection(shared.db_office)
        except sqlite3.OperationalError as err:
            logger.exception(f"{err}: {shared.db_office}")
            raise
        else:
            logger.info("Successfully opened all databases.")

    def on_api_error(self, msg):
        """
        Handles API Error Events
        """
        logger.warning(f"{msg}")
        if re.search("Peer closed", msg, re.IGNORECASE):
            logger.debug("please check Auto Restart Time in TWS")
            logger.warning("restarting the connection to TWS")

    def is_connected(self) -> bool:
        """Check if the app is connected to IB/TWS"""
        con_a = bool(self.loop)
        con_b = self.ibsyn.isConnected()
        return con_a and con_b

    def ib_strategy_cancel_a_contract(
        self, t_ord: OrderTV, action: str = "SELL"
    ) -> ErrorStates:
        """
        Cancels the specified contract with the same action and order reference.
        Returns True if the order was successfully cancelled, False otherwise.
        """
        # Find the order(s) associated with the contract and order reference
        trades = [
            trd
            for trd in self.ibsyn.openTrades()
            if get_ticker(trd.contract) == t_ord.symbol
            and trd.order.orderRef == t_ord.orderRef
            and trd.order.action == action
        ]

        # Cancel the order(s)
        if trades:
            count = 0
            for trd in trades:
                if trd.orderStatus.status != OrderStatus.PendingCancel:
                    self.ibsyn.cancelOrder(trd.order)
                    msg = (
                        f"Cacnceling open order: {t_ord.symbol},{trd.order.orderId},"
                        f"{trd.order.orderType},{trd.order.totalQuantity}"
                    )
                    logger.warning(msg)
                    count += 1
                else:
                    logger.debug(f"ignoring PendingCancel {trd.orderStatus}")
            logger.success(f"Cancelled total {count} orders")
            util.sleep(0)  # Refresh openOrders
            return ErrorStates.SUBMITTED

        logger.warning(f"No open order found for {t_ord}")
        return ErrorStates.ENOOPNTRD

    def ib_strategy_cancellong(self, t_ord: OrderTV) -> ErrorStates:
        """
        Implements strategy.cancel() with regard to strategy.long
        https://www.tradingview.com/pine-script-reference/v5/#fun_strategy{dot}cancel
        """
        return self.ib_strategy_cancel_a_contract(t_ord, "BUY")

    def ib_strategy_cancelshort(self, t_ord: OrderTV) -> ErrorStates:
        """
        Implements strategy.cancel() with regard to strategy.short
        https://www.tradingview.com/pine-script-reference/v5/#fun_strategy{dot}cancel
        """
        return self.ib_strategy_cancel_a_contract(t_ord, "SELL")

    def ib_strategy_cancel_all(self, t_ord: OrderTV) -> ErrorStates:
        """
        Cancels all open orders for the specified symbol and order reference prefix.
        Returns True if at least one order was successfully cancelled, False otherwise.

        https://www.tradingview.com/pine-script-reference/v5/#fun_strategy{dot}cancel_all
        """
        trades = [
            trd
            for trd in self.ibsyn.openTrades()
            if get_ticker(trd.contract) == t_ord.symbol
            and trd.order.orderRef.startswith(get_ordref_ex_prefix())
        ]

        # Cancel the order(s)
        if trades:
            count = 0
            for trd in trades:
                if trd.orderStatus.status != OrderStatus.PendingCancel:
                    self.ibsyn.cancelOrder(trd.order)
                    msg = (
                        f"Cancelling open order: {t_ord.symbol},{trd.order.orderId},"
                        f"{trd.order.orderType},{trd.order.totalQuantity}"
                    )
                    logger.warning(msg)
                    count += 1
                else:
                    logger.debug(f"ignoring PendingCancel {trd.orderStatus}")
                logger.success(f"Cancelled total {count} orders")
            util.sleep(0)  # Refresh openOrders
            return ErrorStates.SUBMITTED

        logger.warning(f"No open order found for {t_ord}")
        return ErrorStates.ENOOPNTRD

    def ib_strategy_exitlong(self, t_ord: OrderTV) -> ErrorStates:
        """
        Implements strategy.exit() with regard to strategy.long
            https://www.tradingview.com/pine-script-reference/v5/#fun_strategy{dot}exit

        Note that
        if orderRef is empty string, it means that from_entry is empty string.
        Hence
            from_entry (series string) An optional parameter.
            The identifier of a specific entry order to exit from it.
            To exit all entries an empty string should be used.
            The default values is empty string.
        """
        return self.ib_strategy_exit(t_ord)

    def ib_strategy_exitshort(self, t_ord: OrderTV) -> ErrorStates:
        """
        Implements strategy.exit() with regard to strategy.short
            https://www.tradingview.com/pine-script-reference/v5/#fun_strategy{dot}exit

        Note that
        if orderRef is empty string, from_entry is empty string.
        Hence
            from_entry (series string) An optional parameter.
            The identifier of a specific entry order to exit from it.
            To exit all entries an empty string should be used.
            The default values is empty string.
        """
        return self.ib_strategy_exit(t_ord)

    @mark
    def ib_strategy_exit(self, t_ord: OrderTV) -> ErrorStates:
        """
        Implements TradingView's strategy.exit().
         https://www.tradingview.com/pine-script-reference/v5/#fun_strategy{dot}exit
        """
        _x = [t_ord.entryLimit, t_ord.entryStop, t_ord.exitLimit, t_ord.exitStop]
        _y = np.array(_x)
        logger.debug(f"args: {t_ord}")
        vec = np.where(_y > 0, 1, 0)
        if (vec == np.array([0, 0, 1, 1])).all():
            state = self.torder.place_updated_bracket_order(t_ord)
        elif (vec == np.array([0, 0, 1, 0])).all():
            state = self.torder.place_updated_limit_order(t_ord)
        elif (vec == np.array([0, 0, 0, 1])).all():
            state = self.torder.place_updated_stop_order(t_ord)
        else:
            logger.error(f"Unsupported orderType combinations: {_x}")
            state = ErrorStates.EBADORDTP

        return state

    def ib_strategy_entry(self, t_ord: OrderTV) -> ErrorStates:
        """
        Implements TradingView's strategy.entry().
        https://www.tradingview.com/pine-script-reference/v5/#fun_strategy{dot}entry

        In addition to strategy.entry(), this function can open a bracket order for IBKR.
        """
        if t_ord.qty <= 0:
            logger.error(f"[X]: invalid message format: qty: {t_ord.qty}")
            return ErrorStates.EBADMSG

        state = ErrorStates.UNRECOG
        _x = [t_ord.entryLimit, t_ord.entryStop, t_ord.exitLimit, t_ord.exitStop]
        _y = np.array(_x)
        logger.trace(f"args: {t_ord}")
        vec = np.where(_y > 0, 1, 0)
        if (vec == np.array([0, 0, 0, 0])).all():
            if self.ib_check_balance(t_ord, t_ord.price):
                state = self.torder.place_market_order(t_ord)
        elif (vec == np.array([1, 0, 0, 0])).all():
            if self.ib_check_balance(t_ord, t_ord.entryLimit):
                state = self.torder.place_limit_order(t_ord)
        elif (vec == np.array([0, 1, 0, 0])).all():
            if self.ib_check_balance(t_ord, t_ord.entryStop):
                state = self.torder.place_stop_order(t_ord)
        elif (vec == np.array([1, 1, 0, 0])).all():
            if self.ib_check_balance(t_ord, t_ord.entryStop):
                state = self.torder.place_stop_limit_order(t_ord)
        elif (vec == np.array([1, 0, 1, 1])).all():
            if self.ib_check_balance(t_ord, t_ord.entryLimit):
                state = self.torder.place_bracket_limit_order(t_ord)
        elif (vec == np.array([0, 0, 1, 0])).all():
            if self.ib_check_balance(t_ord, t_ord.entryLimit):
                state = self.torder.place_market_then_limit_order(t_ord)
        elif (vec == np.array([0, 0, 0, 1])).all():
            if self.ib_check_balance(t_ord, t_ord.entryLimit):
                state = self.torder.place_market_then_stop_order(t_ord)
        elif (vec == np.array([1, 0, 1, 0])).all():
            if self.ib_check_balance(t_ord, t_ord.entryLimit):
                state = self.torder.place_limit_then_limit_order(t_ord)
        elif (vec == np.array([1, 0, 0, 1])).all():
            if self.ib_check_balance(t_ord, t_ord.entryLimit):
                state = self.torder.place_limit_then_stop_order(t_ord)
        elif (vec == np.array([0, 1, 1, 1])).all():
            if self.ib_check_balance(t_ord, t_ord.entryStop):
                state = self.torder.place_bracket_stop_order(t_ord)
        elif (vec == np.array([0, 0, 1, 1])).all():
            if self.ib_check_balance(t_ord, t_ord.price):
                state = self.torder.place_bracket_market_order(t_ord)
        else:
            logger.error(f"Unsupported orderType combinations: {_x}")
            state = ErrorStates.EBADORDTP

        return state

    @mark
    def ib_strategy_close_all_cancel_all(self, t_ord: OrderTV) -> ErrorStates:
        """
        Implements strategy.close_all() which calles strategy.cancel_all()
        """
        # First call cancel_all() is optional for close_all()
        state = self.ib_strategy_cancel_all(t_ord)
        if state != ErrorStates.SUBMITTED:
            logger.info(f"cancel_all(): ErrorStates={state.name}")
        # And then call close_all()
        return self.ib_strategy_close_all(t_ord)

    @mark
    def ib_strategy_close_all(self, t_ord: OrderTV) -> ErrorStates:
        """
        Implements strategy.close_all().
        Exits the current market position, making it flat.
        https://www.tradingview.com/pine-script-reference/v5/#fun_strategy{dot}close_all
        It closes all positions of the specified contract.
        """
        if not (t_ord.qty > 0 or t_ord.qty == TBOT_ALL_CONTRACTS_NUM):
            logger.error(f"[X]: invalid message format: qty: {t_ord.qty}")
            return ErrorStates.EBADMSG

        qty, action, err = self.torder.get_qty_for_strategy_close_all(t_ord)
        if qty <= 0.0:
            logger.warning(f"No open position for {t_ord.symbol}")
            return err

        new_ord = t_ord._replace(action=action, qty=qty)
        self.torder.place_market_order(new_ord)
        logger.warning(f"Closing all position: {action} {qty} {t_ord.symbol}")
        util.sleep(0)  # Refresh openOrders
        return ErrorStates.SUBMITTED

    def ib_strategy_close(self, t_ord: OrderTV) -> ErrorStates:
        """
        Implements TradingView's strategy.close()
        https://www.tradingview.com/pine-script-reference/v5/#fun_strategy{dot}close

        t_ord.qty:  Number of contracts/shares/lots/units to exit a trade with.
                    TBOT_ALL_CONTRACTS_NUM means all positions of the specific entry
        """
        if not (t_ord.qty > 0 or t_ord.qty == TBOT_ALL_CONTRACTS_NUM):
            logger.error(f"[X]: invalid message format: qty: {t_ord.qty}")
            return ErrorStates.EBADMSG

        qty, action, err = self.torder.get_qty_for_strategy_close(
            t_ord, TBOT_STRATEGY_CLOSE_ORDERDB_LOOPBACK
        )
        if qty <= 0.0:
            logger.warning(
                f"Cannot find open position for {t_ord.symbol} {action} close ({t_ord.orderRef})"
            )
            return err

        _x = [t_ord.entryLimit, t_ord.entryStop, t_ord.exitLimit, t_ord.exitStop]
        _y = np.array(_x)
        vec = np.where(_y > 0, 1, 0)
        if (vec == np.array([0, 0, 0, 0])).all():
            t_ord_new = t_ord._replace(qty=qty, action=action)
            logger.info(f"Order qty is adjusted from {t_ord.qty} to {qty}")
            state = self.torder.place_market_order(t_ord_new)
        else:
            logger.error(f"Unsupported orderType combinations: {_x}")
            state = ErrorStates.EBADORDTP

        return state

    def extract_order_parameters(self, data_dict):
        """Extract order params"""
        symbol = data_dict.get("ticker", "")
        currency = data_dict.get("currency", "USD")
        metrics = data_dict.get("metrics")
        timeframe = data_dict.get("timeframe", "?")
        orderRef = data_dict.get("orderRef", "missing").strip()[:TBOT_ORDERREF_MAX_LEN]
        timestamp = data_dict.get("timestamp", "")
        return symbol, currency, metrics, timeframe, orderRef, timestamp

    def extract_order_values(self, metrics) -> Tuple:
        """Extract order values"""
        qty = 0.0
        price = entryStop = entryLimit = exitStop = exitLimit = 0.0
        for mdict in metrics:
            if mdict["name"] == "qty":
                qty = mdict["value"]
            if mdict["name"] == "entry.stop":
                entryStop = mdict["value"]
            if mdict["name"] == "entry.limit":
                entryLimit = mdict["value"]
            if mdict["name"] == "exit.stop":
                exitStop = mdict["value"]
            if mdict["name"] == "exit.limit":
                exitLimit = mdict["value"]
            if mdict["name"] == "price":
                price = mdict["value"]  # midpoint
        return qty, price, entryStop, entryLimit, exitStop, exitLimit

    def submit_order(self, direction: str, t_ord: OrderTV) -> ErrorStates:
        """Place order into ib_insync"""
        state = ErrorStates.UNRECOG
        logger.info(f"order: {t_ord.symbol}, {direction}, {t_ord.orderRef}")
        if direction in ("strategy.entrylong", "strategy.entryshort"):
            state = self.ib_strategy_entry(t_ord)
        elif direction == "strategy.close":
            state = self.ib_strategy_close(t_ord)
        elif direction == "strategy.close_all":
            state = self.ib_strategy_close_all_cancel_all(t_ord)
        elif direction == "strategy.cancellong":
            state = self.ib_strategy_cancellong(t_ord)
        elif direction == "strategy.cancelshort":
            state = self.ib_strategy_cancelshort(t_ord)
        elif direction == "strategy.cancel_all":
            state = self.ib_strategy_cancel_all(t_ord)
        elif direction == "strategy.exitlong":
            state = self.ib_strategy_exitlong(t_ord)
        elif direction == "strategy.exitshort":
            state = self.ib_strategy_exitshort(t_ord)
        else:
            logger.critical(f"Unexpected direction: {direction}")
        logger.info(
            f"order: {t_ord.symbol}, {direction}, {t_ord.orderRef}, exit: {state.name}"
        )
        return state

    @mark
    def ib_dispatch_order(self, unique_key: str, data_dict: Dict) -> ErrorStates:
        """
        Parse the pre-defined message format and identify which order you have
        - Market Order, Limit Order, Bracket Order
        """
        rv_state = ErrorStates.UNRECOG
        action_dict = {
            "strategy.entrylong": "BUY",
            "strategy.entryshort": "SELL",
            "strategy.close": "CLOSE",
            "strategy.close_all": "CLOSE_ALL",
            "strategy.exitlong": "SELL",
            "strategy.exitshort": "BUY",
            "strategy.cancellong": "CANCEL",
            "strategy.cancelshort": "CANCEL",
            "strategy.cancel_all": "CANCEL_ALL",
            "strategy.alert": "ALERT",
        }
        (
            symbol,
            currency,
            metrics,
            timeframe,
            orderRef,
            timestamp,
        ) = self.extract_order_parameters(data_dict)
        orderRefEx = get_ordref_ex(timeframe, orderRef)
        tvSecType = ("stock", "forex", "crypto")
        _contract = data_dict.get("contract", "").strip().lower()
        if _contract in tvSecType:
            contract = _contract
        else:
            contract = None
        direction = data_dict.get("direction", "").strip()
        action = action_dict.get(direction, None)
        if not action:
            logger.error(f"[X]: invalid msg format: direction(action):{direction}")
            rv_state = ErrorStates.EBADMSG
            self.ib_create_alert_info(
                unique_key,
                AlertDBInfo(
                    timestamp,
                    symbol,
                    rv_state.name,
                ),
            )
            return None
        if not (
            timestamp
            and contract
            and symbol
            and currency
            and orderRefEx
            and contract
            and metrics
            and isinstance(metrics, list)
        ):
            logger.error(
                f"[X]: invalid msg format: sym:{symbol}, currency:{currency}, ref:{orderRefEx}"
            )
            rv_state = ErrorStates.EBADMSG
            self.ib_create_alert_info(
                unique_key,
                AlertDBInfo(
                    timestamp,
                    symbol,
                    rv_state.name,
                    direction,
                    timeframe,
                    orderRefEx,
                ),
            )
            return None

        (
            qty,
            tv_price,
            entry_stop,
            entry_limit,
            exit_stop,
            exit_limit,
        ) = self.extract_order_values(metrics)
        t_ord = OrderTV(
            unique_key,
            timestamp,
            contract,
            symbol,
            timeframe,
            action,
            qty,
            currency,
            entry_limit,
            entry_stop,
            exit_limit,
            exit_stop,
            tv_price,
            orderRefEx,
            "GTC",
        )
        rv_state = self.submit_order(direction, t_ord)
        self.ib_create_alert_info(
            unique_key,
            AlertDBInfo(
                timestamp,
                symbol,
                rv_state.name,
                direction,
                timeframe,
                orderRefEx,
                qty,
                entry_limit,
                entry_stop,
                exit_limit,
                exit_stop,
                tv_price,
            ),
        )

    def calculate_end_to_end_delay(self, tv_ts_m: int, redis_ts_ms: int = 0):
        """
        Measures end-to-end delay

        tv_ts_ms: Tradingview (timestamp in miliseconds)
        redis_ts_ms: at the time of receving the webhook and push it into Redis
        ibkr_ts_ms: at the time of placing order
        """
        ibkr_ts_ms = time.time_ns() // 1000000
        if redis_ts_ms:
            logger.debug(
                f"E-2-E: from TradingView to Flask: {redis_ts_ms - tv_ts_m} ms"
            )
            logger.trace(
                f"E-2-E: from Flask to RedisSub: {ibkr_ts_ms - redis_ts_ms} ms"
            )
        logger.trace(f"E-2-E: from TradingView to RedisSub: {ibkr_ts_ms - tv_ts_m} ms")

    def connect(self) -> bool:
        """
        Connects to TWS/IB Gateway
        """
        ret = False
        sleep_on_error = 12
        try:
            logger.info("trying to connect to TWS/IBG")
            self.ibsyn.connect(
                shared.ibkr_addr,
                int(shared.ibkr_port),
                clientId=int(shared.client_id),
            )
            self.loop = util.getLoop()
            logger.success("The connection to IBKR done well")
            ret = True
        except socket.error:
            err = sys.exc_info()[1]
            if err.errno == errno.ENETUNREACH:
                logger.warning("please check network connection!")
                util.sleep(sleep_on_error)
            if err.errno == errno.ECONNREFUSED:
                logger.warning("please check IP addr and port for TWS/IB!")
                util.sleep(sleep_on_error)
            raise
        except BaseException as err:
            self.loop = None
            logger.error(
                "Make sure API port on TWS/IBG is open\n"
                f"Check API Settings -> General: {sleep_on_error}"
            )
            logger.error(f"{err}")
            util.sleep(sleep_on_error)
        return ret

    def update(
        self, caller: object = None, tbot_ts: str = "", data_dict: Dict = None, **kwargs
    ):
        """
        Handle Tradingview's WEBHOOK from Redis publish or stream
        Args:
            caller: subject in Observer's design pattern
            data_dict: Tradingview WEBHOOK message
        """
        # Verify connection regardless of data_dict's status
        if not self.is_connected():
            self.connect()

        redis_stream_id = "0-0"
        try:
            redis_stream_id = kwargs["redis_msg_id"]
        except KeyError:
            logger.error("redis_msg_id not found in kwargs")
            return

        if self.is_connected():
            if data_dict:
                if self.profiler and tbot_ts:
                    self.calculate_end_to_end_delay(
                        data_dict.get("timestamp"), int(tbot_ts)
                    )
                if tbot_ts:
                    self.ib_dispatch_order(tbot_ts, data_dict)
                    caller.delete_event(redis_stream_id)
                logger.debug("Completed the message delivery")
            else:
                # Give time to async loop
                util.sleep(TBOT_PUT_REDIS_EVENT_SLEEP_SEC)

    def ib_check_balance(self, t_ord: OrderTV, price: float) -> bool:
        """Get the account summary"""
        account_summary = self.ibsyn.accountSummary()
        currency = t_ord.currency
        sec_type = (
            "STK"
            if t_ord.contract == "stock"
            else "CASH"
            if t_ord.contract == "forex"
            else "CRYPTO"
            if t_ord.contract == "crypto"
            else None
        )
        # Find the available cash balance in the appropriate currency
        if sec_type == "STK":
            available_funds_str = next(
                (
                    item.value
                    for item in account_summary
                    if item.tag == "AvailableFunds"
                ),
                None,
            )
        elif sec_type == "CASH" and currency is not None:
            available_funds_str = sum(
                item.value
                for item in account_summary
                if item.tag == "AvailableFunds" and item.currency == currency
            )
        elif sec_type == "CRYPTO":
            available_funds_str = next(
                (
                    item.value
                    for item in account_summary
                    if item.tag == "AvailableFunds"
                ),
                None,
            )
        else:
            logger.critical(
                f"Invalid security type {sec_type} or missing currency for Forex trade"
            )
            return False

        if available_funds_str:
            available_funds = float(available_funds_str)
        else:
            logger.error(
                f"No available funds found for sec_type: {sec_type} and currency: {currency}"
            )
            return False

        # Calculate the total cost of the order
        qty = t_ord.qty
        total_cost = qty * price

        # Check if the user has enough balance to buy
        if total_cost <= available_funds:
            logger.info(
                f"total_cost:{total_cost} <= available_funds:{available_funds_str}"
            )
            return True
        else:
            logger.error(
                f"total_cost:{total_cost} > available_funds:{available_funds_str}"
            )
            return False

    def ib_create_alert_info(self, unique_ts: str, alt: AlertDBInfo):
        """
        Saves TradingView's alerts into the database
        """
        self.alertdb.insert(unique_ts, alt)
        if __debug__:
            self.alertdb.display()

    def ib_enable_log(self, level=logging.ERROR):
        """Enables ib insync logging"""
        util.logToConsole(level)

    def _copy_sqlite3_to_dest(self, dest: str, src: str):
        try:
            if os.path.exists(src):
                if os.path.exists(dest):
                    logger.debug(f"sqlite3: overwriting {dest}")
                shutil.move(src, dest)
        except IOError as err:
            logger.critical(f"sqlite3: unable to overwrite file {err}")
            raise
        except Exception as err:
            logger.critical(f"sqlite3: unexpected file error: {err}")
            raise

    def _close_ib(self):
        """Closes ib_insync connection"""
        if self.loop:
            self.loop.stop()
        if self.ibsyn:
            if self.ibsyn.isConnected():
                logger.warning("closing ib.disconnect()")
                self.ibsyn.disconnect()

    def _close_db(self):
        logger.info("closing sqlite3")
        if self.torder:
            self.torder.close()
        if self.alertdb:
            self.alertdb.close()
        if self.orderdb:
            self.orderdb.close()
        if self.errordb:
            self.errordb.close()
        self._copy_sqlite3_to_dest(shared.db_home, shared.db_office)

    def close(self):
        """
        Close all connections
        """
        try:
            self._close_ib()
        except Exception as err:
            logger.exception(f"Failed to close IB: {err}")
        else:
            logger.info("IB connection closed")

        try:
            self._close_db()
        except Exception as err:
            logger.exception(f"Failed to close DB: {err}")
        else:
            logger.info("DB connection closed")

        logger.trace("ByeBye")
