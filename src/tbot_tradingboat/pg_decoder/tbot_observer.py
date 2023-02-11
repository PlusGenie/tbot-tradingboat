# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
from abc import ABC, abstractmethod
from typing import Dict


class TbotObserver(ABC):
    """
    Abstract Class for Observe Pattern for Tbot
    """

    @abstractmethod
    def open(self):
        """
        Uses this function to initialize code after the constructor
        """

    @abstractmethod
    def update(self, caller: object, tbot_ts: str, data_dict: Dict, **kwargs):
        """
        Uses this function to handle messages from subject class
        """

    @abstractmethod
    def close(self):
        """
        Uses this function to close connections
        """
