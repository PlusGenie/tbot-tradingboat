# File: tbot_tradingboat/pg_pnl_monitor/pnl_monitor.py

from ib_insync import IB, PnL, MarketOrder
from tbot_tradingboat.pg_decoder.tbot_observer import TbotObserver
from loguru import logger
from tbot_tradingboat.utils.tbot_env import shared
#import asyncio

class PnLMonitorObserver(TbotObserver):
    def __init__(self):
        super().__init__()
        self.ib = IB()
        self.loss_threshold = float(shared.pnl_threshold)  # Configurable loss threshold
        self.beginning_balance = None
        self.account = None
        self.action_taken = False

    def open(self):
        # Connect to IB
        self.connect()
        # Get the account ID
        self.account = self.ib.managedAccounts()[0]
        # Fetch the beginning account balance
        self.fetch_beginning_balance()
        # Subscribe to PnL updates
        self.subscribe_to_pnl()


    def connect(self):
        self.ib.connect(
            host=shared.ibkr_addr,
            port=int(shared.ibkr_port),
            clientId=int(shared.client_id) + 1,  # Use a different client ID
        )
        logger.info("PnLMonitorObserver connected to IB.")

    def fetch_beginning_balance(self):
        account_values = self.ib.accountValues(account=self.account)
        net_liquidation = next(
            (float(item.value) for item in account_values
             if item.tag == 'NetLiquidation' and item.currency == 'BASE'),
            None
        )
        if net_liquidation is not None:
            self.beginning_balance = net_liquidation
            logger.info(f"Beginning account balance: {self.beginning_balance}")
        else:
            logger.error("Failed to retrieve the beginning account balance.")


    def subscribe_to_pnl(self):
        # Subscribe to account-level PnL updates
        pnl = self.ib.reqPnL(self.account)
        pnl.updateEvent += self.on_pnl_update
        logger.info("Subscribed to PnL updates.")


    def on_pnl_update(self, pnl: PnL):
        """
        Event handler for PnL updates.
        """
        if self.action_taken:
            return

        if self.beginning_balance is None:
            logger.error("Beginning balance not set.")
            return

        # Calculate percentage change
        net_liquidation = self.beginning_balance + pnl.dailyPnL
        percentage_change = ((net_liquidation - self.beginning_balance) / self.beginning_balance) * 100
        logger.info(f"Current P&L: {percentage_change:.2f}%")

        if percentage_change <= self.loss_threshold:
            logger.warning(f"P&L threshold reached: {percentage_change:.2f}%")
            # Take action to close positions and cancel orders
            self.take_action()
            self.action_taken = True

    def take_action(self):
        """
        Closes all positions and cancels all open orders.
        """
        logger.info("Closing all positions and cancelling all orders.")
        # Close all positions
        positions = self.ib.positions(account=self.account)
        for position in positions:
            contract = position.contract
            qty = position.position
            action = 'SELL' if qty > 0 else 'BUY'
            order = MarketOrder(action, abs(qty))
            trade = self.ib.placeOrder(contract, order)
            logger.info(f"Closing position: {action} {abs(qty)} {contract.symbol}")
        # Cancel all open orders
        open_orders = self.ib.openOrders()
        for order in open_orders:
            self.ib.cancelOrder(order)
            logger.info(f"Cancelling order: {order.orderId}")
        # Optionally, disconnect or stop monitoring after action
        self.ib.disconnect()
        logger.info("Disconnected from IB after taking action.")


    def update(self, caller=None, *args, **kwargs):
        """
        Since we're using event-driven callbacks, the update method can remain empty.
        """
        pass

    def close(self):
        # Disconnect from IB
        if self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Disconnected from IB.")


