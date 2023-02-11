# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
from typing import Dict
import time
from datetime import datetime
from dataclasses import dataclass

from json import dumps
from http.client import HTTPException
from loguru import logger

from telegram import Bot
from telegram.error import TimedOut, TelegramError

from tbot_tradingboat.pg_decoder.tbot_observer import TbotObserver
from tbot_tradingboat.pg_database.orderdb import TbotOrderDB
from tbot_tradingboat.pg_database.errordb import TbotErrorDB
from tbot_tradingboat.utils.constants import TBOT_UPLOAD_ERROR_TIME_SEC
from tbot_tradingboat.utils.tbot_env import shared


@dataclass
class TelegramObserver(TbotObserver):
    """
    The Observer interface to send messages to Telegram.
    """

    def __init__(self):
        """Initialize Telegram bot"""

        self.bot = None
        self.new_events = []
        self.orderdb = None
        self.errordb = None
        self.log_start_sec = 0
        self.err_start_sec = 0
        self.last_order_ms = 0
        # Set the default time to read erros from database
        self.last_err_ms = (time.time_ns() // 1000000) - (3600 * 1 * 1000)
        if shared.telegram_token and shared.telegram_chat_id:
            self.bot = Bot(token=shared.telegram_token)

    def open(self):
        if self.bot:
            self.orderdb = TbotOrderDB()
            self.orderdb.setup_connection(shared.db_office)
            self.errordb = TbotErrorDB()
            self.errordb.setup_connection(shared.db_office)

    def _send_msg(self, title: str, msg: str):
        """
        Sends messages to Telegram
        """
        body = title + msg
        data = None
        try:
            data = self.bot.send_message(chat_id=shared.telegram_chat_id, text=body)
        except TimedOut as err:
            logger.error(f"Telegram request timed out: {err}")
        except HTTPException as err:
            logger.error(f"Telegram request failed: {err}")
        except TelegramError as err:
            logger.error(f"Telegram request failed: {err}")
        if data:
            logger.success("It successfully sent the message to Telegram.")

    def send_errors(self):
        """Send error message"""
        row = self.errordb.find_error_by_uniquekey(self.last_err_ms)
        if row:
            logger.debug(f"sending error ${row}")
            msg = dumps(row)
            title = f"{row['errcode']} {row['errstr']} {row['symbol']}"
            self._send_msg(title, msg)
            dt_obj = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
            self.last_err_ms = dt_obj.timestamp() * 1000

    def send_order(self):
        """Send order messages"""
        row = self.orderdb.find_order_by_unique_key(self.last_order_ms)
        if row:
            title = (
                f"{row['ticker']} {row['action']} {row['qty']} on #{shared.client_id}"
            )
            msg = dumps(row)
            self._send_msg(title, msg)

    def update(self, caller=None, tbot_ts: str = "", data_dict: Dict = None, **kwargs):
        """
        Send message to Discord if there is no webhook incoming (not buy)
        """
        if not self.bot:
            # logger.trace("Telegram bot is not ready")
            return
        if data_dict:
            self.new_events.append(tbot_ts)
        else:
            t_now_sec = time.time()
            if (t_now_sec - self.err_start_sec) > TBOT_UPLOAD_ERROR_TIME_SEC:
                self.err_start_sec = t_now_sec
                self.send_errors()

            if len(self.new_events) > 0:
                self.last_order_ms = self.new_events.pop(0)
                self.send_order()

    def close(self):
        """
        Handle Keyboard Interrupt
        """
        if self.orderdb:
            self.orderdb.close()
        if self.errordb:
            self.errordb.close()
