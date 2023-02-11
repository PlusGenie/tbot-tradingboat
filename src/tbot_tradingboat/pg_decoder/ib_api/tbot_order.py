# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
from abc import ABC
from typing import List, Tuple, Optional
from ib_insync import (
    Contract,
    Trade,
    Stock,
    Forex,
    Crypto,
    IB,
    util,
    StopOrder,
    MarketOrder,
    LimitOrder,
    StopLimitOrder,
    OrderStatus,
)

from loguru import logger
from tbot_tradingboat.pg_database.orderdb import TbotOrderDB
from tbot_tradingboat.pg_database.errordb import TbotErrorDB
from tbot_tradingboat.utils.objects import (
    OrderTV,
    PnL2Contract,
    OrderDBInfo,
    OrderKey,
    OrderKeyEx,
    ErrorDBInfo,
    ErrorStates,
)
from tbot_tradingboat.pg_decoder.ib_api.tbot_api import (
    get_ticker,
    get_timestamp,
    TBOT_ALL_CONTRACTS_NUM,
    TBOT_NO_OPEN_POSITIONS,
)
from .marketrules import TbotMarketRules
from .tbot_order_event import TbotOrderEvent


def on_disconnected_event():
    """Handle disconnected Event"""
    logger.debug("on_disconnected_event: disconnected")


class TbotOrder(ABC):
    """
    Define class to place order using ib insync API
    """

    def __init__(self, ibsyn: IB, orderdb: TbotOrderDB, errordb: TbotErrorDB):
        self.ibsyn = ibsyn
        self.redis_conn = None
        self.bars = None
        self.orderdb = orderdb
        self.errordb = errordb
        self.contract_pnl = []
        self.mktrules = TbotMarketRules(ibsyn)
        self.order_event = TbotOrderEvent(ibsyn, orderdb, errordb, self.contract_pnl)
        self.order_event.install_event_hdlrs()

    def get_current_price(self, contract: Contract) -> None:
        """Get current price"""
        bars = self.ibsyn.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="1 D",
            barSizeSetting="1 min",
            whatToShow="MIDPOINT",
            useRTH=False,
            formatDate=1,
        )
        data_f = util.df(bars)
        logger.debug(f"symbol: {contract.symbol}, price:{data_f.close.iloc[-1]}")

    def req_pnl_single(self, contract: Contract):
        """Requests a PnL Single for a contract"""
        symbol = get_ticker(contract)
        if any(elm.symbol == symbol for elm in self.contract_pnl):
            logger.debug(f"req_pnl_single: {symbol} already subscribed to PnL updates.")
            return

        self.contract_pnl.append(PnL2Contract(symbol, contract.conId))
        try:
            account = self.ibsyn.managedAccounts()[0]
            self.ibsyn.reqPnLSingle(account, "", contract.conId)
        except (ValueError, IndexError) as err:
            logger.error(f"Error requesting PnL Single for {symbol}: {err}")
            raise

    def create_error_order_info(self, d_ord: ErrorDBInfo):
        """Saves Order into the database"""
        self.errordb.insert("", d_ord)
        if __debug__:
            self.errordb.display()

    def create_order_info(self, unique_ts: str, d_ord: OrderDBInfo):
        """Saves Order into the database"""
        self.orderdb.insert(get_timestamp(unique_ts), d_ord)
        if __debug__:
            self.orderdb.display()

    def _get_contract(self, t_ord: OrderTV) -> Contract:
        """Chooses the specific contract from TV message'

        :return: contract verified
        """
        contract = None
        if t_ord.contract == "stock":
            contract = Stock(t_ord.symbol, "SMART", t_ord.currency)
        elif t_ord.contract == "forex":
            contract = Forex(pair=t_ord.symbol)
        elif t_ord.contract == "crypto":
            contract = Crypto(t_ord.symbol, "PAXOS", t_ord.currency)
        else:
            logger.error(f"contract: {t_ord.contract} not implemented")
            return None
        self.ibsyn.qualifyContracts(contract)
        return contract

    def get_qty_for_strategy_close(
        self, t_ord: OrderTV, num: int
    ) -> Tuple[float, Optional[str], Optional[ErrorStates]]:
        """Get total qty from filled orders for strategy_close()

        return (qty, action): qty : position, SELL/BUY/None
        """
        filled_orderdb_pos = self.orderdb.find_filled_orders_qty_by_key(
            OrderKey(t_ord.symbol, t_ord.orderRef), num
        )
        if filled_orderdb_pos == TBOT_NO_OPEN_POSITIONS:
            logger.warning(f"Failed to find {t_ord.symbol} in filled orders")
            return -1, None, ErrorStates.ENENTPOSDB

        filled_orderdb_qty = abs(filled_orderdb_pos)
        # Compare filled positions against Api positions()
        positions = self.ibsyn.positions()
        filtered_positions = [
            p for p in positions if t_ord.symbol == get_ticker(p.contract)
        ]
        if not filtered_positions:
            return -1, None, ErrorStates.ENOCLSPOS

        position = filtered_positions[0]
        total = abs(position.position)
        if filled_orderdb_qty > total:
            logger.critical(
                f"Filled orderdb qty ({filled_orderdb_pos}) exceeds total position ({total})"
            )
            return -1, None, ErrorStates.E2BIGQTY

        action = "SELL" if filled_orderdb_pos > 0 else "BUY"
        rv_qty = (
            filled_orderdb_qty
            if t_ord.qty == TBOT_ALL_CONTRACTS_NUM
            else min(t_ord.qty, filled_orderdb_qty)
        )
        logger.debug(f"close| action:{action}, calculated qty:{rv_qty}")
        return rv_qty, action, None

    def get_qty_for_strategy_close_all(
        self, t_ord: OrderTV
    ) -> Tuple[float, Optional[str], Optional[ErrorStates]]:
        """get valid qty from portfolio's position for strategy_close_all()"""
        ptf_pos = self.orderdb.find_position_size_by_key(OrderKey(t_ord.symbol))
        if ptf_pos == TBOT_NO_OPEN_POSITIONS:
            logger.warning(f"Failed to find {t_ord.symbol} in portfolio")
            return -1, None, ErrorStates.ENOMKTPOSDB

        positions = self.ibsyn.positions()
        filtered_positions = [
            p for p in positions if t_ord.symbol == get_ticker(p.contract)
        ]
        if not filtered_positions:
            logger.warning(f"Failed to find {t_ord.symbol} in {positions}")
            return -1, None, ErrorStates.ENOCLSPOS

        position = filtered_positions[0]
        total = abs(position.position)
        action = "SELL" if position.position > 0 else "BUY"
        rv_qty = total if t_ord.qty == TBOT_ALL_CONTRACTS_NUM else min(t_ord.qty, total)
        logger.debug(f"close_all| action:{action}, calculated qty:{rv_qty}")
        return rv_qty, action, None

    def get_qty_for_strategy_exit(self, totalQuantity: float, qty: float) -> float:
        """adjust  totalQuantity for updated bracket order"""
        rv_qty = totalQuantity
        if qty == TBOT_ALL_CONTRACTS_NUM:
            rv_qty = totalQuantity
        elif 0 < qty <= totalQuantity:
            rv_qty = qty
        else:
            rv_qty = -1
        logger.trace(f"adjusted qty({qty}) -> qty({rv_qty})")
        return rv_qty

    def find_open_attached_order_in_opentrade(
        self, t_ord: OrderTV, ord_type: str
    ) -> Tuple[Trade, ErrorStates]:
        """
        Find an open order with the specified orderRef prefix and orderType.
        """
        # Find all trades with the same symbol and orderRef prefix
        selected = [
            trd
            for trd in self.ibsyn.openTrades()
            if t_ord.symbol == get_ticker(trd.contract)
            and trd.order.orderRef.startswith(t_ord.orderRef)
        ]
        if len(selected) == 1:
            if selected[0].order.orderType == ord_type:
                return selected[0], ErrorStates.SUBMITTED
            else:
                logger.warning(f"Unmatched order type {ord_type}")
                return {}, ErrorStates.EBADORDTP
        elif len(selected) == 2:
            for trd in selected:
                if trd.orderStatus.parentId == 0:
                    if trd.orderStatus.status != OrderStatus.Filled:
                        logger.warning(f"Parent order is not filled: {trd.orderStatus}")
                        return {}, ErrorStates.ENOPARFL
        else:
            logger.error(f"Unexpected open orders: count={len(selected)}")
            return {}, ErrorStates.ENOOPNTRD

    def find_open_bracket_orders_in_opentrade(
        self, t_ord: OrderTV
    ) -> Tuple[List[Trade], ErrorStates]:
        """
        Find open bracket orders with the specified orderRef prefix.
        The function assumes that open orders exist.
        Returns:
            Tuple[List[Trade], ErrorStates]: A tuple of bracket orders
                with the specified orderRef prefix,
            or an empty list if not found, and an error state.
        """
        # Find all trades with the same symbol and orderRef prefix
        selected = [
            trd
            for trd in self.ibsyn.openTrades()
            if t_ord.symbol == get_ticker(trd.contract)
            and trd.order.orderRef.startswith(t_ord.orderRef)
        ]

        # Handle different cases based on the number of selected orders
        if len(selected) > 3:
            logger.error(f"Too many duplicated orders: count={len(selected)}")
            return [], ErrorStates.EDUPORD
        elif len(selected) == 3:
            for trd in selected:
                if trd.orderStatus.parentId == 0:
                    if trd.orderStatus.status != OrderStatus.Filled:
                        logger.warning(f"Parent order is not filled: {trd.orderStatus}")
                        return [], ErrorStates.ENOPARFL
        elif len(selected) == 2:
            for trd in selected:
                if trd.orderStatus.status not in OrderStatus.ActiveStates:
                    logger.error(
                        f"Order is not in ActiveStates {trd.orderStatus.status}"
                    )
                    return [], ErrorStates.ENOACTV
        else:
            logger.error(f"No open orders to update: {selected}")
            return [], ErrorStates.ENOOPNTRD

        return selected, ErrorStates.SUBMITTED

    def find_open_bracket_order_in_orderdb(self, t_ord: OrderTV) -> bool:
        """Find existing bracket orders in order db."""
        key = OrderKey(t_ord.symbol, t_ord.orderRef)
        orders = self.orderdb.find_specified_orders(key, 3)
        if len(orders) < 2:
            logger.warning(f"No bracket orders found: {len(orders)}")
            return False
        return True

    def find_open_ordertype_in_orderdb(self, t_ord: OrderTV, ord_type: str) -> bool:
        """Find existing open orders with the specified orderType in order db."""
        rev_act = "BUY" if t_ord.action == "SELL" else "SELL"
        key = OrderKeyEx(
            t_ord.symbol,
            t_ord.orderRef,
            orderType=ord_type,
            action=rev_act,
            orderId=0,  # Set to 0 since we don't know it
        )
        order = self.orderdb.find_specified_order_by_type(key)
        if order and order["ordertype"] == ord_type:
            return True
        logger.warning(f"No open orders found with orderType {ord_type}")
        return False

    def place_updated_bracket_order(self, t_ord: OrderTV) -> ErrorStates:
        """
        Updates stopLoss and ProfitTaker for an exiting bracket order.

        Please note that we will not depend on the database to find the parent
        order that has a 'Filled' status.
        """
        if t_ord.contract == "crypto":
            # https://interactivebrokers.github.io/tws-api/cryptocurrency.html
            logger.warning("TWS does not support bracket order for crypto")
            return ErrorStates.ENOTSUP
        if not self.find_open_bracket_order_in_orderdb(t_ord):
            return ErrorStates.ENOENTRDB

        trades, state = self.find_open_bracket_orders_in_opentrade(t_ord)
        if not trades:
            return state

        for trade in trades:
            if trade.order.orderType == "STP":
                qty = self.get_qty_for_strategy_exit(
                    trade.order.totalQuantity, t_ord.qty
                )
                if qty <= 0:
                    logger.warning(f"Invalid qty {t_ord.qty}")
                    return ErrorStates.ECALCQTY
                exit_stop = self.mktrules.increase_price(
                    trade.contract, t_ord.exitStop
                )[0]
                trade.order.auxPrice = exit_stop
                trade.order.totalQuantity = qty
                trade.order.transmit = True
                self.ibsyn.placeOrder(trade.contract, trade.order)

            elif trade.order.orderType == "LMT":
                qty = self.get_qty_for_strategy_exit(
                    trade.order.totalQuantity, t_ord.qty
                )
                if qty <= 0:
                    logger.warning(f"Invalid qty {t_ord.qty}")
                    return ErrorStates.ECALCQTY
                exit_limit = self.mktrules.increase_price(
                    trade.contract, t_ord.exitLimit
                )[0]
                trade.order.lmtPrice = exit_limit
                trade.order.totalQuantity = qty
                trade.order.transmit = True
                self.ibsyn.placeOrder(trade.contract, trade.order)

        return ErrorStates.SUBMITTED

    def place_updated_open_order(self, t_ord: OrderTV, ord_type: str) -> ErrorStates:
        """
        Updates stopLoss and ProfitTaker for an exiting bracket order.

        Please note that we will not depend on the database to find the parent
        order that has a 'Filled' status.
        """
        if t_ord.contract == "crypto":
            # https://interactivebrokers.github.io/tws-api/cryptocurrency.html
            logger.warning("TWS does not support bracket order for crypto")
            return ErrorStates.ENOTSUP
        if not self.find_open_ordertype_in_orderdb(t_ord, ord_type):
            return ErrorStates.ENOENTRDB

        trade, state = self.find_open_attached_order_in_opentrade(t_ord, ord_type)
        if not trade:
            return state
        qty = self.get_qty_for_strategy_exit(trade.order.totalQuantity, t_ord.qty)
        if qty <= 0:
            logger.warning(f"Invalid qty {t_ord.qty}")
            return ErrorStates.ECALCQTY
        exit_stop = self.mktrules.increase_price(trade.contract, t_ord.exitStop)[0]
        trade.order.auxPrice = exit_stop
        trade.order.totalQuantity = qty
        trade.order.transmit = True
        self.ibsyn.placeOrder(trade.contract, trade.order)
        return ErrorStates.SUBMITTED

    def place_updated_stop_order(self, t_ord: OrderTV) -> ErrorStates:
        """
        Updates StopLoss (attached order)
        """
        return self.place_updated_open_order(t_ord, "STP")

    def place_updated_limit_order(self, t_ord: OrderTV) -> ErrorStates:
        """
        Updates ProfitTaker (attached order)
        """
        return self.place_updated_open_order(t_ord, "LMT")

    def place_limit_order(self, t_ord: OrderTV) -> ErrorStates:
        """Places a limit order on IB/TWS"""
        contract = self._get_contract(t_ord)
        if not contract:
            return ErrorStates.ENOCNTR
        entry_limit = self.mktrules.increase_price(contract, t_ord.entryLimit)[0]
        logger.debug(f"entryStop: {entry_limit}")
        if t_ord.contract == "crypto":
            l_ord = LimitOrder(
                action=t_ord.action,
                totalQuantity=0.0,
                lmtPrice=entry_limit,
                cashQty=t_ord.qty,
                tif="IOC",
                orderRef=t_ord.orderRef,
            )
        else:
            l_ord = LimitOrder(
                t_ord.action,
                t_ord.qty,
                entry_limit,
                tif=t_ord.tif,
                orderRef=t_ord.orderRef,
            )
        trade = self.ibsyn.placeOrder(contract, l_ord)
        d_ord = OrderDBInfo(
            t_ord.price,
            l_ord.orderId,
            t_ord.symbol,
            t_ord.action,
            l_ord.orderType,
            l_ord.totalQuantity,
            trade.orderStatus.avgFillPrice,
            trade.orderStatus.status,
            t_ord.orderRef,
            l_ord.parentId,
            entry_limit,
        )
        self.create_order_info(t_ord.uniqueKey, d_ord)
        return ErrorStates.SUBMITTED

    def place_stop_order(self, t_ord: OrderTV) -> ErrorStates:
        """
        returns true if submitted successfuly else false
        """
        contract = self._get_contract(t_ord)
        if not contract:
            return ErrorStates.ENOCNTR
        if t_ord.contract == "crypto":
            # https://interactivebrokers.github.io/tws-api/cryptocurrency.html
            logger.error("TWS Crypto does not support stop order")
            return ErrorStates.ENOTSUP
        entry_stop = self.mktrules.increase_price(contract, t_ord.entryStop)[0]
        logger.debug(f"entryStop: {entry_stop}")
        s_ord = StopOrder(
            t_ord.action,
            t_ord.qty,
            entry_stop,
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
        )
        trade = self.ibsyn.placeOrder(contract, s_ord)
        d_ord = OrderDBInfo(
            t_ord.price,
            s_ord.orderId,
            t_ord.symbol,
            s_ord.action,
            s_ord.orderType,
            s_ord.totalQuantity,
            trade.orderStatus.avgFillPrice,
            trade.orderStatus.status,
            t_ord.orderRef,
            s_ord.parentId,
            0.0,
            entry_stop,
        )
        self.create_order_info(t_ord.uniqueKey, d_ord)
        return ErrorStates.SUBMITTED

    def place_stop_limit_order(self, t_ord: OrderTV) -> ErrorStates:
        """
        returns true if submitted successfuly else false
        """
        contract = self._get_contract(t_ord)
        if not contract:
            return ErrorStates.ENOCNTR
        if t_ord.contract == "crypto":
            # https://interactivebrokers.github.io/tws-api/cryptocurrency.html
            logger.error("TWS Crypto does not support stop order")
            return ErrorStates.ENOTSUP
        entry_limit, entry_stop = self.mktrules.increase_price(
            contract, t_ord.entryLimit, t_ord.entryStop
        )
        sl_ord = StopLimitOrder(
            t_ord.action,
            t_ord.qty,
            entry_limit,
            entry_stop,
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
        )
        trade = self.ibsyn.placeOrder(contract, sl_ord)
        d_ord = OrderDBInfo(
            t_ord.price,
            sl_ord.orderId,
            t_ord.symbol,
            sl_ord.action,
            sl_ord.orderType,
            sl_ord.totalQuantity,
            trade.orderStatus.avgFillPrice,
            trade.orderStatus.status,
            t_ord.orderRef,
            sl_ord.parentId,
            0.0,
            entry_stop,
        )
        self.create_order_info(t_ord.uniqueKey, d_ord)
        return ErrorStates.SUBMITTED

    def place_market_order(self, t_ord: OrderTV) -> ErrorStates:
        """Places a market order on IB/TWS"""
        contract = self._get_contract(t_ord)
        if not contract:
            return ErrorStates.ENOCNTR
        if t_ord.contract == "crypto":
            if t_ord.action == "BUY":
                m_ord = MarketOrder(
                    action=t_ord.action,
                    totalQuantity=0.0,
                    cashQty=t_ord.qty,  # Must for MKT
                    tif="IOC",  # (Immediate or Cancel)
                    orderRef=t_ord.orderRef,
                )
            else:
                m_ord = MarketOrder(
                    t_ord.action,
                    t_ord.qty,
                    tif="IOC",  # (Immediate or Cancel)
                    orderRef=t_ord.orderRef,
                )
        else:
            m_ord = MarketOrder(
                t_ord.action, t_ord.qty, tif=t_ord.tif, orderRef=t_ord.orderRef
            )
        trade = self.ibsyn.placeOrder(contract, m_ord)
        d_ord = OrderDBInfo(
            t_ord.price,
            m_ord.orderId,
            t_ord.symbol,
            m_ord.action,
            m_ord.orderType,
            m_ord.totalQuantity,
            trade.orderStatus.avgFillPrice,
            trade.orderStatus.status,
            t_ord.orderRef,
            m_ord.parentId,
        )
        self.create_order_info(t_ord.uniqueKey, d_ord)
        return ErrorStates.SUBMITTED

    def place_bracket_limit_order(self, t_ord: OrderTV) -> ErrorStates:
        """
        Create a limit order that is bracketed by a take-profit order and
        a stop-loss order
        """
        if t_ord.contract == "crypto":
            # https://interactivebrokers.github.io/tws-api/cryptocurrency.html
            logger.error("IBKR crypto does not support bracket order")
            return ErrorStates.ENOTSUP
        contract = self._get_contract(t_ord)
        if not contract:
            return ErrorStates.ENOCNTR
        entryLimit, exitLimit, exitStop = self.mktrules.increase_price(
            contract, t_ord.entryLimit, t_ord.exitLimit, t_ord.exitStop
        )
        # Create the bracket order with the entry, exit limit and stop prices
        kwargs = {"orderRef": t_ord.orderRef, "tif": t_ord.tif}
        b_ords = self.ibsyn.bracketOrder(
            t_ord.action,
            t_ord.qty,
            entryLimit,
            exitLimit,
            exitStop,
            **kwargs,
        )
        # Loop through the bracket orders and place each order
        for idx, elm in enumerate(b_ords):
            trd = self.ibsyn.placeOrder(contract, elm)
            # Set the limit and stop prices based on the index of the bracket order
            if idx == 0:
                lmtPrice = entryLimit
                auxPrice = 0.0
            elif idx == 1:
                lmtPrice = exitLimit
                auxPrice = 0.0
            else:
                lmtPrice = 0.0
                auxPrice = exitStop
            d_ord = OrderDBInfo(
                t_ord.price,
                elm.orderId,
                t_ord.symbol,
                elm.action,
                elm.orderType,
                elm.totalQuantity,
                trd.orderStatus.avgFillPrice,
                trd.orderStatus.status,
                t_ord.orderRef,
                elm.parentId,
                lmtPrice,
                auxPrice,
            )
            self.create_order_info(t_ord.uniqueKey, d_ord)
        return ErrorStates.SUBMITTED

    def place_market_then_limit_order(self, t_ord: OrderTV) -> ErrorStates:
        """
        Places market order and then attaches a ProfitTaker.
        """
        if t_ord.contract == "crypto":
            # https://interactivebrokers.github.io/tws-api/cryptocurrency.html
            logger.error("TWS does not support bracket order for crypto")
            return ErrorStates.ENOTSUP
        contract = self._get_contract(t_ord)
        if not contract:
            return ErrorStates.ENOCNTR
        p_ord_id = self.ibsyn.client.getReqId()
        exit_limit = self.mktrules.increase_price(contract, t_ord.exitLimit)[0]
        rev_act = "BUY" if t_ord.action == "SELL" else "SELL"
        parent = MarketOrder(
            t_ord.action,
            t_ord.qty,
            orderId=p_ord_id,
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=False,
        )
        takeProfit = LimitOrder(
            rev_act,
            t_ord.qty,
            exit_limit,
            parentId=p_ord_id,
            orderId=self.ibsyn.client.getReqId(),
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=True,
        )
        for i, elm in enumerate([parent, takeProfit]):
            logger.debug(f"placing bracket orderID: {elm.orderId}")
            trd = self.ibsyn.placeOrder(contract, elm)
            # Set the limit and stop prices based on the index of the bracket order
            if i == 0:
                lmtPrice = 0.0
            elif i == 1:
                lmtPrice = exit_limit
            d_ord = OrderDBInfo(
                t_ord.price,
                elm.orderId,
                t_ord.symbol,
                elm.action,
                elm.orderType,
                elm.totalQuantity,
                trd.orderStatus.avgFillPrice,
                trd.orderStatus.status,
                t_ord.orderRef,
                elm.parentId,
                lmtPrice,
            )
            self.create_order_info(t_ord.uniqueKey, d_ord)
        return ErrorStates.SUBMITTED

    def place_limit_then_limit_order(self, t_ord: OrderTV) -> ErrorStates:
        """
        Places limit order and then attaches a profiTtaker.
        """
        if t_ord.contract == "crypto":
            # https://interactivebrokers.github.io/tws-api/cryptocurrency.html
            logger.error("TWS does not support bracket order for crypto")
            return ErrorStates.ENOTSUP
        contract = self._get_contract(t_ord)
        if not contract:
            return ErrorStates.ENOCNTR
        p_ord_id = self.ibsyn.client.getReqId()
        entry_limit, exit_limit = self.mktrules.increase_price(
            contract, t_ord.entryLimit, t_ord.exitLimit
        )
        rev_act = "BUY" if t_ord.action == "SELL" else "SELL"
        parent = LimitOrder(
            t_ord.action,
            t_ord.qty,
            entry_limit,
            orderId=p_ord_id,
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=False,
        )
        takeProfit = LimitOrder(
            rev_act,
            t_ord.qty,
            exit_limit,
            parentId=p_ord_id,
            orderId=self.ibsyn.client.getReqId(),
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=True,
        )
        for i, elm in enumerate([parent, takeProfit]):
            logger.debug(f"placing bracket orderID: {elm.orderId}")
            trd = self.ibsyn.placeOrder(contract, elm)
            # Set the limit and stop prices based on the index of the bracket order
            if i == 0:
                lmtPrice = entry_limit
            elif i == 1:
                lmtPrice = exit_limit
            d_ord = OrderDBInfo(
                t_ord.price,
                elm.orderId,
                t_ord.symbol,
                elm.action,
                elm.orderType,
                elm.totalQuantity,
                trd.orderStatus.avgFillPrice,
                trd.orderStatus.status,
                t_ord.orderRef,
                elm.parentId,
                lmtPrice,
            )
            self.create_order_info(t_ord.uniqueKey, d_ord)
        return ErrorStates.SUBMITTED

    def place_market_then_stop_order(self, t_ord: OrderTV) -> ErrorStates:
        """
        Places market order and then attaches a StopLoss.
        """
        if t_ord.contract == "crypto":
            # https://interactivebrokers.github.io/tws-api/cryptocurrency.html
            logger.error("TWS does not support bracket order for crypto")
            return ErrorStates.ENOTSUP
        contract = self._get_contract(t_ord)
        if not contract:
            return ErrorStates.ENOCNTR
        p_ord_id = self.ibsyn.client.getReqId()
        exit_stop = self.mktrules.increase_price(contract, t_ord.exitStop)[0]
        rev_act = "BUY" if t_ord.action == "SELL" else "SELL"
        parent = MarketOrder(
            t_ord.action,
            t_ord.qty,
            orderId=p_ord_id,
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=False,
        )
        stopLoss = StopOrder(
            rev_act,
            t_ord.qty,
            exit_stop,
            parentId=p_ord_id,
            orderId=self.ibsyn.client.getReqId(),
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=True,
        )

        for idx, elm in enumerate([parent, stopLoss]):
            logger.debug(f"placing bracket orderID: {elm.orderId}")
            trd = self.ibsyn.placeOrder(contract, elm)
            if idx == 0:
                auxPrice = 0.0
            elif idx == 1:
                auxPrice = exit_stop
            d_ord = OrderDBInfo(
                t_ord.price,
                elm.orderId,
                t_ord.symbol,
                elm.action,
                elm.orderType,
                elm.totalQuantity,
                trd.orderStatus.avgFillPrice,
                trd.orderStatus.status,
                t_ord.orderRef,
                elm.parentId,
                0.0,
                auxPrice,
            )
            self.create_order_info(t_ord.uniqueKey, d_ord)
        return ErrorStates.SUBMITTED

    def place_limit_then_stop_order(self, t_ord: OrderTV) -> ErrorStates:
        """
        Places limit order and then attaches a StopLoss.
        """
        if t_ord.contract == "crypto":
            # https://interactivebrokers.github.io/tws-api/cryptocurrency.html
            logger.error("TWS does not support bracket order for crypto")
            return ErrorStates.ENOTSUP
        contract = self._get_contract(t_ord)
        if not contract:
            return ErrorStates.ENOCNTR
        p_ord_id = self.ibsyn.client.getReqId()
        entry_limit, exit_stop = self.mktrules.increase_price(
            contract, t_ord.entryLimit, t_ord.exitStop
        )
        rev_act = "BUY" if t_ord.action == "SELL" else "SELL"
        parent = LimitOrder(
            t_ord.action,
            t_ord.qty,
            entry_limit,
            orderId=p_ord_id,
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=False,
        )
        stopLoss = StopOrder(
            rev_act,
            t_ord.qty,
            exit_stop,
            parentId=p_ord_id,
            orderId=self.ibsyn.client.getReqId(),
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=True,
        )

        for idx, elm in enumerate([parent, stopLoss]):
            logger.debug(f"placing bracket orderID: {elm.orderId}")
            trd = self.ibsyn.placeOrder(contract, elm)
            if idx == 0:
                lmtPrice = entry_limit
                auxPrice = 0.0
            elif idx == 1:
                lmtPrice = 0.0
                auxPrice = exit_stop
            d_ord = OrderDBInfo(
                t_ord.price,
                elm.orderId,
                t_ord.symbol,
                elm.action,
                elm.orderType,
                elm.totalQuantity,
                trd.orderStatus.avgFillPrice,
                trd.orderStatus.status,
                t_ord.orderRef,
                elm.parentId,
                lmtPrice,
                auxPrice,
            )
            self.create_order_info(t_ord.uniqueKey, d_ord)
        return ErrorStates.SUBMITTED

    def place_bracket_market_order(self, t_ord: OrderTV) -> ErrorStates:
        """
        Places bracket order with a MaketOrder entry
        """
        if t_ord.contract == "crypto":
            # https://interactivebrokers.github.io/tws-api/cryptocurrency.html
            logger.error("TWS does not support bracket order for crypto")
            return ErrorStates.ENOTSUP
        contract = self._get_contract(t_ord)
        if not contract:
            return ErrorStates.ENOCNTR
        p_ord_id = self.ibsyn.client.getReqId()
        exit_limit, exit_stop = self.mktrules.increase_price(
            contract, t_ord.exitLimit, t_ord.exitStop
        )
        rev_act = "BUY" if t_ord.action == "SELL" else "SELL"
        parent = MarketOrder(
            t_ord.action,
            t_ord.qty,
            orderId=p_ord_id,
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=False,
        )
        takeProfit = LimitOrder(
            rev_act,
            t_ord.qty,
            exit_limit,
            parentId=p_ord_id,
            orderId=self.ibsyn.client.getReqId(),
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=False,
        )
        stopLoss = StopOrder(
            rev_act,
            t_ord.qty,
            exit_stop,
            parentId=p_ord_id,
            orderId=self.ibsyn.client.getReqId(),
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=True,
        )
        for idx, elm in enumerate([parent, takeProfit, stopLoss]):
            logger.debug(f"placing bracket orderID: {elm.orderId}")
            trd = self.ibsyn.placeOrder(contract, elm)
            if idx == 0:
                lmtPrice = 0.0
                auxPrice = 0.0
            elif idx == 1:
                lmtPrice = exit_limit
                auxPrice = 0.0
            else:
                lmtPrice = 0.0
                auxPrice = exit_stop
            d_ord = OrderDBInfo(
                t_ord.price,
                elm.orderId,
                t_ord.symbol,
                elm.action,
                elm.orderType,
                elm.totalQuantity,
                trd.orderStatus.avgFillPrice,
                trd.orderStatus.status,
                t_ord.orderRef,
                elm.parentId,
                lmtPrice,
                auxPrice,
            )
            self.create_order_info(t_ord.uniqueKey, d_ord)
        return ErrorStates.SUBMITTED

    def place_bracket_stop_order(self, t_ord: OrderTV) -> ErrorStates:
        """
        Places bracket order with a MaketOrder entry
        """
        if t_ord.contract == "crypto":
            # https://interactivebrokers.github.io/tws-api/cryptocurrency.html
            logger.error(" bracket order for crypto")
            return ErrorStates.ENOTSUP
        contract = self._get_contract(t_ord)
        if not contract:
            return ErrorStates.ENOCNTR
        entry_stop, exit_limit, exit_stop = self.mktrules.increase_price(
            contract, t_ord.entryStop, t_ord.exitLimit, t_ord.exitStop
        )
        p_ord_id = self.ibsyn.client.getReqId()
        rev_act = "BUY" if t_ord.action == "SELL" else "SELL"
        parent = StopOrder(
            t_ord.action,
            t_ord.qty,
            entry_stop,
            orderId=p_ord_id,
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=False,
        )
        takeProfit = LimitOrder(
            rev_act,
            t_ord.qty,
            exit_limit,
            parentId=p_ord_id,
            orderId=self.ibsyn.client.getReqId(),
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=False,
        )
        stopLoss = StopOrder(
            rev_act,
            t_ord.qty,
            exit_stop,
            parentId=p_ord_id,
            orderId=self.ibsyn.client.getReqId(),
            tif=t_ord.tif,
            orderRef=t_ord.orderRef,
            transmit=True,
        )
        for idx, elm in enumerate([parent, takeProfit, stopLoss]):
            logger.debug(f"placing bracket orderID: {elm.orderId}")
            trd = self.ibsyn.placeOrder(contract, elm)
            if idx == 0:
                lmtPrice = 0.0
                auxPrice = entry_stop
            elif idx == 1:
                lmtPrice = exit_limit
                auxPrice = 0.0
            else:
                lmtPrice = 0.0
                auxPrice = exit_stop
            d_ord = OrderDBInfo(
                t_ord.price,
                elm.orderId,
                t_ord.symbol,
                elm.action,
                elm.orderType,
                elm.totalQuantity,
                trd.orderStatus.avgFillPrice,
                trd.orderStatus.status,
                t_ord.orderRef,
                elm.parentId,
                lmtPrice,
                auxPrice,
            )
            self.create_order_info(t_ord.uniqueKey, d_ord)
        return ErrorStates.SUBMITTED

    def close(self):
        """Close Order"""
