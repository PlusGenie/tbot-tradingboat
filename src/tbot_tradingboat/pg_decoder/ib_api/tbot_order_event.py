# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
import time
from abc import ABC
from typing import List
import random
from ib_insync import (
    Contract,
    Trade,
    Position,
    PnLSingle,
    IB,
    util,
    PortfolioItem,
    OrderStatus,
)

from loguru import logger
from tbot_tradingboat.pg_database.orderdb import TbotOrderDB
from tbot_tradingboat.pg_database.errordb import TbotErrorDB
from tbot_tradingboat.utils.objects import (
    OrderDBInfo,
    OrderKeyEx,
    ErrorDBInfo,
)
from tbot_tradingboat.pg_decoder.ib_api.tbot_api import (
    get_ticker,
    get_timestamp,
    TBOT_PORTFOLIO_ORDERREF_PREFIX,
    TBOT_PORTFOLIO_ORDERSTATUS,
)


def on_disconnected_event():
    """Handle disconnected Event"""
    logger.debug("on_disconnected_event: disconnected")


class TbotOrderEvent(ABC):
    """
    Define class to place order using ib insync API
    """

    def __init__(
        self,
        ibsyn: IB,
        orderdb: TbotOrderDB,
        errordb: TbotErrorDB,
        contract_pnl: List = None,
    ):
        self.ibsyn = ibsyn
        self.orderdb = orderdb
        self.errordb = errordb
        self.contract_pnl = contract_pnl

    def on_connected_event(self):
        """Handle ConnectedEvent from ib_insync"""
        logger.info("onConnectedEvent: connected to IBKR")

    def on_pending_tickers_event(self, tickers):
        """Handle onPendingTickersEvent from ib_insync"""
        logger.debug(f"onPendingTickersEvent: {tickers}")
        for tick in tickers:
            bid = tick.bid if not util.isNan(tick.bid) else 0
            ask = tick.ask if not util.isNan(tick.ask) else 0
            last = tick.last if not util.isNan(tick.last) else tick.markPrice
            logger.debug(f"conid: {tick.contract.conId}|{bid},{ask},{last}")

    def on_update_portfolio(self, item: PortfolioItem):
        """
        Add Portfolio into OrderDB
        The function uses fields of OrderDB slightly differently compared to real Orders
        """
        logger.debug(f"updatePortfolioEvent: {item}")
        symbol = get_ticker(item.contract)
        tv_price = item.marketPrice
        # Fill fields with Portfolio specifc information
        action = item.contract.primaryExchange
        ord_id = item.contract.conId
        ord_ref = TBOT_PORTFOLIO_ORDERREF_PREFIX + symbol
        ord_type = item.contract.secType
        action = item.contract.primaryExchange

        if not action:
            logger.trace("ignoring updatePortfolioEvent out of trading hours")
            return
        key = OrderKeyEx(
            symbol, ord_ref, orderType=ord_type, action=action, orderId=ord_id
        )
        # Generate a unique timestamp for the order
        unique_ts = str(time.time_ns() // 1000000)

        d_ord = OrderDBInfo(
            tv_price,  # use marketPrice instead of TradingView's price
            ord_id,  # use conId instead of orderID
            symbol,
            action,  # use PrimaryExchange instead of 'SELL' or 'BUY'
            ord_type,  # use secType
            0.0,  # qty
            0.0,  # avgfillprice
            TBOT_PORTFOLIO_ORDERSTATUS,
            ord_ref,
        )

        # Check if the order already exists in the database
        if not self.orderdb.find_specified_order_by_type(key):
            # If the order is not in the database, create a new OrderDBInfo object
            logger.debug(f"Creating a new portfolio entry for {symbol}")
            self.create_portfolio_info(unique_ts, d_ord)

        u_ord = d_ord._replace(avgfillprice=item.averageCost, position=item.position)
        # Update the order information in the database
        self.orderdb.update_portfolio(
            get_timestamp(unique_ts),
            u_ord,
            item.marketValue,
            item.unrealizedPNL,
            item.realizedPNL,
        )

    def on_new_order_event(self, trade: Trade):
        """Handle onNewOrderEvent from ib_insync"""
        logger.trace(f"onNewOrderEvent: {trade}")

    def on_cancel_order_event(self, trade: Trade):
        """Handle onCancelOrderEvent from ib_insync"""
        logger.debug(f"onCancelOrderEvent: {trade}")
        self.orderdb.update_cancelled_order(trade.order.orderId)

    def on_pnl_single_event(self, pnl: PnLSingle):
        """Handle onPnlSingleEvent from ib_insync"""
        for ele in self.contract_pnl:
            if ele.conId == pnl.conId:
                msg = {
                    f"onPnlSingleEvent| position: {pnl.position}, value: {pnl.value} "
                    f"unrealizedPnL:{pnl.unrealizedPnL}: realizedPnL: {pnl.realizedPnL}"
                }
                logger.debug(msg)
                # Do something
                self.contract_pnl.remove(ele)
                break
        self.ibsyn.cancelPnLSingle(pnl.account, "", pnl.conId)

    def on_position_event(self, position: Position):
        """Handle onPositionEvent from ib_insync"""
        if __debug__:
            msg = {
                f"onPositionEvent| ticker:{get_ticker(position.contract)}, "
                f"position:{position.position}, avgCost:{position.avgCost}"
            }
            logger.trace(msg)

    def on_error_event(self, reqId: int, errCode: int, errStr: str, contract: Contract):
        """Handle onErrorEvent from ib_insync

        Also this saves some error information into databse according
        to messages codes
        https://interactivebrokers.github.io/tws-api/message_codes.html

        """
        # Pick important System Messages Codes
        # msg_codes = (1100, 1101, 2110, 502)
        sym = f"{contract.localSymbol}" if contract else ""
        msg = (
            f"reqId:{str(reqId)}, errCode:{str(errCode)}, "
            f"errStr:{errStr}, contract: {sym}"
        )
        logger.debug(msg)
        # if errorCode in msg_codes:
        if errCode >= -1:
            err_msg = ErrorDBInfo(
                time.time_ns() // 1000000, reqId, errCode, sym, errStr
            )
            self.create_error_order_info(err_msg)

    def on_order_modify_event(self, trade: Trade):
        """Handle a modified event order
        This is event triggered by strategy.exit()
        """
        logger.debug(f"onOrderModifyEvent: {trade}")
        self.on_order_common_event(trade)

    def on_order_status_ptf_position(self, contract: Contract, position: float):
        """Update the position of portfolio quickly without waiting for portfolio event"""
        logger.debug(f"Update portfolio pos in order_status {position}")
        symbol = get_ticker(contract)
        ord_ref = TBOT_PORTFOLIO_ORDERREF_PREFIX + symbol
        action = contract.primaryExchange
        self.orderdb.update_portfolio_position(symbol, ord_ref, action, position)

    def on_order_status(self, trade: Trade):
        """Updates Order Status from ib insync"""
        logger.debug(f"onOrderStatus: {trade}")
        self.on_order_common_event(trade)
        if trade.orderStatus.status == OrderStatus.Filled:
            # See whether we can update position of portfolio very quickly without waiting for a few seconds
            positions = self.ibsyn.positions()
            for pos in positions:
                if pos.contract.symbol == trade.contract.symbol:
                    self.on_order_status_ptf_position(trade.contract, pos.position)
                    break

    def on_order_common_event(self, trade: Trade):
        """Updates Common Order Status from ib insync"""
        if __debug__:
            msg = (
                f"status:{trade.orderStatus.status}, sym:{trade.contract.symbol}, "
                f"action:{trade.order.action}, qty:{trade.order.totalQuantity}, "
                f"avgPrice:{trade.orderStatus.avgFillPrice}"
            )
            logger.debug(msg)
        if self.orderdb.find_order_exists_by_ord_id(trade.order.orderId):
            lmt_price, aux_price = 0.0, 0.0
            if trade.order.orderType == "LMT":
                lmt_price = trade.order.lmtPrice
            elif trade.order.orderType == "STP":
                aux_price = trade.order.auxPrice
            elif trade.order.orderType == "STP LMT":
                lmt_price = trade.order.lmtPrice
                aux_price = trade.order.auxPrice
            d_ord = OrderDBInfo(
                tvPrice=0.0,  # not used
                orderId=trade.order.orderId,
                ticker="",  # not used
                action=trade.order.action,  # not used
                orderType=trade.order.orderType,  # not used
                qty=trade.order.totalQuantity,  # not used
                avgfillprice=trade.orderStatus.avgFillPrice,
                orderStatus=trade.orderStatus.status,
                orderRef=trade.order.orderRef,  # not used
                parentOrderId=trade.orderStatus.parentId,  # not used
                lmtPrice=lmt_price,
                auxPrice=aux_price,
                position=trade.orderStatus.filled,  # tracking the remaninig qty
            )
            self.orderdb.update_order_status(d_ord)
        else:
            symbol = get_ticker(trade.contract)
            logger.warning(f"cann't find open status: {symbol}")
            d_ord = OrderDBInfo(
                0.0,
                trade.orderStatus.orderId,
                symbol,
                trade.order.action,
                trade.order.orderType,
                trade.order.totalQuantity,
                trade.orderStatus.avgFillPrice,
                trade.orderStatus.status,
                trade.order.orderRef,
                trade.orderStatus.parentId,
            )
            unique_ts = str(time.time_ns() // 1000000)
            self.create_order_info(unique_ts, d_ord)
        if __debug__:
            self.orderdb.display()

    def on_exec_details(self, trade, fill):
        """
        This func handles both live fills and responses to
        reqExecution
        """
        logger.debug(f"onExecDetails {fill.execution} {trade}")

    def on_open_order_event(self, trade: Trade):
        """Callback function for new open order event from Master client ID"""
        logger.trace(trade)
        key = OrderKeyEx(
            get_ticker(trade.contract),
            trade.order.orderRef,
            trade.order.orderType,
            trade.order.action,
            trade.orderStatus.orderId,
        )
        # Check if the order already exists in the database
        if not self.orderdb.find_specified_order_by_type(key):
            # If the order is not in the database, create a new OrderDBInfo object
            logger.debug(
                f"Creating a new order database entry for a missing order: {trade}"
            )
            d_ord = OrderDBInfo(
                0.0,
                trade.orderStatus.orderId,
                get_ticker(trade.contract),
                trade.order.action,
                trade.order.orderType,
                trade.order.totalQuantity,
                trade.orderStatus.avgFillPrice,
                trade.orderStatus.status,
                trade.order.orderRef,
                trade.orderStatus.parentId,
            )
            unique_ts = str(time.time_ns() // 1000000)
            self.create_order_info(unique_ts, d_ord)

    def install_event_hdlrs(self):
        """Installs ib_insync event handlers"""
        self.ibsyn.execDetailsEvent += self.on_exec_details
        self.ibsyn.orderStatusEvent += self.on_order_status
        self.ibsyn.connectedEvent += self.on_connected_event
        # self.ibsyn.disconnectedEvent += on_disconnected_event
        self.ibsyn.pendingTickersEvent += self.on_pending_tickers_event
        self.ibsyn.newOrderEvent += self.on_new_order_event
        self.ibsyn.cancelOrderEvent += self.on_cancel_order_event
        self.ibsyn.positionEvent += self.on_position_event
        self.ibsyn.errorEvent += self.on_error_event
        self.ibsyn.orderModifyEvent += self.on_order_modify_event
        self.ibsyn.pnlSingleEvent += self.on_pnl_single_event
        self.ibsyn.openOrderEvent += self.on_open_order_event
        self.ibsyn.updatePortfolioEvent += self.on_update_portfolio

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

    def create_error_order_info(self, d_ord: ErrorDBInfo):
        """Saves Order into the database"""
        self.errordb.insert("", d_ord)
        if __debug__:
            self.errordb.display()

    def create_order_info(self, unique_ts: str, d_ord: OrderDBInfo):
        """Saves Order into the database"""
        self.orderdb.insert(get_timestamp(unique_ts), d_ord)

    def create_portfolio_info(self, unique_ts: str, d_ord: OrderDBInfo):
        """Creates Portfolio into the database"""
        self.orderdb.insert(get_timestamp(unique_ts), d_ord)

        # Define a probability threshold
        probability_threshold = 0.5  # for a 50% chance
        # Generate a random number between 0 and 1
        random_number = random.random()

        # Call delete_stale_portfolio() based on the probability threshold
        if random_number < probability_threshold:
            self.orderdb.delete_stale_portfolio()
