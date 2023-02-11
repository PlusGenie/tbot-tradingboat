# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
import json
import os
from typing import Dict
import time
from datetime import datetime
from json import dumps
from dataclasses import dataclass

from http.client import HTTPException
from requests.exceptions import Timeout

from requests import Response
from loguru import logger

from discord_webhook import DiscordEmbed, DiscordWebhook
from tbot_tradingboat.utils.constants import (
    TBOT_UPLOAD_LOGFILE_TIME_SEC,
    TBOT_UPLOAD_ERROR_TIME_SEC,
)
from tbot_tradingboat.utils.tbot_env import shared
from tbot_tradingboat.pg_decoder.tbot_observer import TbotObserver
from tbot_tradingboat.pg_database.orderdb import TbotOrderDB
from tbot_tradingboat.pg_database.errordb import TbotErrorDB

script_dir = os.path.dirname(__file__)
logo_file_path = os.path.join(script_dir, "assets/genie_thumb.jpg")


@dataclass
class DiscordObserver(TbotObserver):
    """
    The Observer interface to send messages to Discord.
    """

    color_buy = "A1DE01"
    color_sell = "EA4514"
    color_error = "C9385E"
    color_logo = "FFFF00"
    color_logfile = "36454F"

    def __init__(self):
        """Initialize Discord Webhook"""

        self.webhook = None
        self.new_events = []
        self.orderdb = None
        self.errordb = None
        self.retry_after_ms = 0.0
        self.log_start_sec = 0.0
        self.err_start_sec = 0.0
        self.last_order_ms = 0
        # Set the default time to read erros from database
        self.last_err_ms = (time.time_ns() // 1000000) - (3600 * 1 * 1000)
        # Show log filename in Discord Channel
        self.log_filename = "log.txt"
        self.is_logo_uploaded = False
        # rate_limit_retry set to False in order to avoid time.sleep()
        if shared.discord_webhook:
            self.webhook = DiscordWebhook(
                url=shared.discord_webhook, rate_limit_retry=False, timeout=3
            )

    def open(self):
        """Open the database"""
        if self.webhook:
            self.orderdb = TbotOrderDB()
            self.orderdb.setup_connection(shared.db_office)
            self.errordb = TbotErrorDB()
            self.errordb.setup_connection(shared.db_office)

    def _webhook_excecute(self) -> Response:
        response = None
        try:
            response = self.webhook.execute(remove_embeds=True)
        except Timeout as err:
            logger.error(f"Timeout error while connecting to Discord: {err}")
        except HTTPException as err:
            logger.error(f"HTTP error while connecting to Discord: {err}")
        except ConnectionError as err:
            logger.error(f"Error connecting to Discord: {err}")
        except json.JSONDecodeError as err:
            logger.error(f"JSON decoding error: {err}")
        except Exception as err:
            logger.error(f"Unexpected error while connecting to Discord: {err}")

        if response:
            logger.trace(f"status_code: {response.status_code}")
            if response.status_code >= 200 and response.status_code < 300:
                logger.success("It successfully sent the message to Discord.")
            elif response.status_code == 400:
                logger.error("Invalid Embed type")
            elif response.status_code == 429:
                try:
                    errors = json.loads(response.content.decode("utf-8"))
                    _ = float(errors.get("retry_after", "0.0")) * 1e3 + 150
                    self.retry_after_ms = max(_, self.retry_after_ms)
                except json.JSONDecodeError:
                    logger.error("Ignoring invalid JSON content in the response")
            else:
                logger.error(f"Unhandled HTTP status code: {response.status_code}")
        return response

    def _send_msg(self, title: str, desc: str, color: str) -> Response:
        """Sends order messages to Discord"""
        embed = DiscordEmbed(title=title, description=desc, color=color)
        embed.set_timestamp()
        self.webhook.add_embed(embed)
        response = self._webhook_excecute()
        return response

    def send_order(self) -> Response:
        """Send an order message"""
        response = None
        row = self.orderdb.find_order_by_unique_key(self.last_order_ms)
        if row:
            title = (
                f"{row['ticker']} {row['action']} {row['qty']} on #{shared.client_id}"
            )
            logger.debug(f"sending order ${row}")
            color = self.color_buy if row["action"] == "BUY" else self.color_sell
            embed = DiscordEmbed(title=title, description=dumps(row), color=color)
            embed.set_timestamp()
            embed.add_embed_field(name="ACTION", value=row["action"])
            embed.add_embed_field(name="TICKER", value=row["ticker"])
            embed.add_embed_field(name="QTY", value=str(row["qty"]))
            self.webhook.add_embed(embed)
            response = self._webhook_excecute()
            if response and response.status_code != 429:
                self.last_order_ms = self.new_events.pop(0)
        else:
            # We have a new webhook but it might be cancled by the decoder
            logger.trace("no order to send")
            self.last_order_ms = self.new_events.pop(0)
        return response

    def send_error(self) -> Response:
        """Send an error message"""
        response = None
        row = self.errordb.find_error_by_uniquekey(self.last_err_ms)
        if row:
            logger.debug(f"sending error ${row}")
            title = f"Error on Tradingboat #{shared.client_id}"
            embed = DiscordEmbed(title=title, description="", color=self.color_error)
            embed.set_timestamp()
            embed.add_embed_field(name="ERRCODE", value=str(row["errcode"]))
            embed.add_embed_field(name="ERRSTR", value=row["errstr"])
            embed.add_embed_field(name="SYMBOL", value=row["symbol"])
            self.webhook.add_embed(embed)
            response = self._webhook_excecute()
            if response and response.status_code != 429:
                dt_obj = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
                self.last_err_ms = dt_obj.timestamp() * 1000
        else:
            logger.trace("no error to send")
        return response

    def send_logo_file(self):
        """Send a logo file"""
        with open(logo_file_path, "rb") as fobj:
            self.webhook.add_file(file=fobj.read(), filename="genie.jpg")
        title = f"Welcome to Tbot on Tradingboat #{shared.client_id}"
        embed = DiscordEmbed(title=title, description="", color=self.color_logo)
        embed.set_thumbnail(url="attachment://genie.jpg")
        embed.set_image(url="attachment://genie.jpg")
        embed.set_timestamp()
        self.webhook.add_embed(embed)
        self._webhook_excecute()

    def send_logfile(self):
        """Uploads the log file to Discord"""
        file_path = shared.logfile
        if not file_path:
            logger.error("there is no log file to upload")
            return
        try:
            title = f"Log on Tradingboat #{shared.client_id}"
            embed = DiscordEmbed(title=title, description="", color=self.color_logfile)
            embed.set_thumbnail(url="attachment://genie.jpg")
            embed.set_timestamp()
            self.webhook.add_embed(embed)
            with open(file_path, "rb") as fobj:
                self.webhook.add_file(file=fobj.read(), filename=self.log_filename)
            self._webhook_excecute()
            self.webhook.remove_files()
            self.webhook.remove_embeds()
        except Exception as err:
            logger.error(f"Unexpected error while sending logfile to Discord: {err}")
            raise

    def update(self, caller=None, tbot_ts: str = "", data_dict: Dict = None, **kwargs):
        """
        Send message to Discord if there is no webhook incoming (not buy)
        """
        if not self.webhook:
            logger.trace("webhook is not ready")
            return
        if data_dict:
            self.new_events.append(tbot_ts)
        else:
            if not self.is_logo_uploaded:
                self.send_logo_file()
                self.is_logo_uploaded = True
            if self.retry_after_ms > 0:
                logger.warning(f"following rate_limit: {self.retry_after_ms}ms")
                self.retry_after_ms -= caller.event_loop_ms
            else:
                t_now_sec = time.time()
                if (t_now_sec - self.log_start_sec) > TBOT_UPLOAD_LOGFILE_TIME_SEC:
                    self.send_logfile()
                    self.log_start_sec = t_now_sec

                if (t_now_sec - self.err_start_sec) > TBOT_UPLOAD_ERROR_TIME_SEC:
                    self.err_start_sec = t_now_sec
                    self.send_error()
                # Send new order info as soon as possible
                if self.new_events:
                    self.send_order()

    def close(self):
        """
        Handle Keyboard Interrupt
        """
        if self.orderdb:
            self.orderdb.close()
        if self.errordb:
            self.errordb.close()
