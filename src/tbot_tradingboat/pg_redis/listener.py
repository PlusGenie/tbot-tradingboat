# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
from abc import ABC, abstractmethod
from typing import Tuple


class TbotListener(ABC):
    """
    Abstract Class for Observe Pattern for Tbot
    """

    @abstractmethod
    def open(self):
        """
        Uses this function to initialize code after the constructor
        """

    @abstractmethod
    def connect(self) -> bool:
        """Connects to Redis Channel"""

    @abstractmethod
    def validate_message(self, msg) -> object:
        """
        Returns None if this is not valid pubsub messsage
        message (_type_): a message from Redis PubSub channel
        """

    @abstractmethod
    def handle_event(self, caller) -> Tuple[str, str, str]:
        """
        Vadidates the event and then dispatch it to observers
        """

    @abstractmethod
    def close(self):
        """
        Uses this function to close connections
        """
