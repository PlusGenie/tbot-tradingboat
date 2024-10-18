#!/usr/bin/env python3
import sys
import os
import time
from ib_insync import IB, PnL, MarketOrder, util
from loguru import logger

# Configure logging
logger.add("pnl_monitor.log", rotation="1 MB")

# Configuration variables (can be set via environment variables)
IBKR_HOST = os.environ.get('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.environ.get('IBKR_PORT', '4002'))
CLIENT_ID = int(os.environ.get('CLIENT_ID', '1')) + 2  # Ensure unique client ID
PNL_THRESHOLD = float(os.environ.get('PNL_THRESHOLD', '-1.0'))  # Default to -1%
ACCOUNT = os.environ.get('ACCOUNT', '')  # If not set, will use the first account

class PnLMonitor:
    def __init__(self):
        self.ib = IB()
        self.loss_threshold = PNL_THRESHOLD
        self.beginning_balance = None
        self.account = ACCOUNT
        self.action_taken = False

    def run(self):
        try:
            self.connect()
            self.fetch_beginning_balance()
            self.subscribe_to_pnl()
            self.ib.run()  # Start the event loop
        except Exception as e:
            logger.exception(f"Exception in PnLMonitor: {e}")
        finally:
            self.ib.disconnect()
            logger.info("Disconnected from IB.")

    def connect(self):
        logger.info(f"Connecting to IBKR at {IBKR_HOST}:{IBKR_PORT} with client ID {CLIENT_ID}")
        self.ib.connect(host=IBKR_HOST, port=IBKR_PORT, clientId=CLIENT_ID)
        if not self.account:
            self.account = self.ib.managedAccounts()[0]
        logger.info(f"Connected to IBKR. Using account: {self.account}")

    def fetch_beginning_balance(self):
        # Fetch account summary (blocking call on first run)
        account_values = self.ib.accountSummary(account=self.account)
        net_liquidation = next(
            (float(item.value) for item in account_values
             if item.tag == 'NetLiquidation' and item.currency == 'USD'),
            None
        )
        if net_liquidation is not None:
            self.beginning_balance = net_liquidation
            logger.info(f"Beginning account balance: {self.beginning_balance}")
        else:
            logger.error("Failed to retrieve the beginning account balance.")
            sys.exit(1)

    def subscribe_to_pnl(self):
        # Subscribe to account-level PnL updates
        self.ib.reqPnL(self.account)
        self.ib.pnlEvent += self.on_pnl_update
        logger.info("Subscribed to PnL updates.")

    def on_pnl_update(self, pnl: PnL):
        """
        Event handler for PnL updates.
        """
        if pnl.account != self.account:
            return  # Ignore updates for other accounts

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
        close_orders = []
        for position in positions:
            contract = position.contract
            qty = position.position
            action = 'SELL' if qty > 0 else 'BUY'
            order = MarketOrder(action, abs(qty))
            trade = self.ib.placeOrder(contract, order)
            logger.info(f"Closing position: {action} {abs(qty)} {contract.symbol}")
            close_orders.append(trade)

        # Wait for orders to be filled
        util.waitUntil(lambda: all(trade.isDone() for trade in close_orders), timeout=60)

        # Cancel all open orders using reqGlobalCancel
        self.ib.reqGlobalCancel()
        logger.info("All open orders have been canceled.")

        logger.info("All positions closed and open orders cancelled.")

if __name__ == "__main__":
    monitor = PnLMonitor()
    monitor.run()
