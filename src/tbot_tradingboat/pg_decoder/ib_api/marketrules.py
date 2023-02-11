# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
from abc import ABC
from typing import List
import math
from dataclasses import dataclass, field

from ib_insync import Contract, IB, PriceIncrement
from loguru import logger
from .tbot_api import get_ticker


@dataclass
class SymbolPriceIncrement:
    """PriceIncrement Container for a single ticker"""

    symbol: str
    ranges: List[PriceIncrement] = field(default_factory=list)


class TbotMarketRules(ABC):
    """
    Handle price increments rule.
    Some trades have constant price increments at all price levels.
    https://interactivebrokers.github.io/tws-api/minimum_increment.html
    """

    def __init__(self, ibsyn: IB):
        self.ibsyn = ibsyn
        # Local cache for all contract
        self.market_rules = []

    def req_market_rules(self, contract: Contract) -> bool:
        """
        Request price increment rules for the contract.

        Args:
            contract: the Contract object for which to request the price increment rules.
        """
        is_ok = False
        mlist = self.ibsyn.reqContractDetails(contract)
        if len(mlist) > 0:
            market_rule_ids = mlist[0].marketRuleIds.split(",")
            if market_rule_ids:
                pr_incs = self.ibsyn.reqMarketRule(market_rule_ids[0])
                if pr_incs:
                    m_rule = SymbolPriceIncrement(get_ticker(contract))
                    for elm in pr_incs:
                        m_rule.ranges.append(elm)
                        logger.debug(
                            f"lowEdge: {elm.lowEdge}, increment: {elm.increment}"
                        )
                    self.market_rules.append(m_rule)
                    if len(self.market_rules) > 0:
                        is_ok = True
        if not is_ok:
            logger.debug(
                f"No market rules found for {contract.secType}, {contract.symbol}."
            )
        else:
            logger.debug(f"Market rules found for {contract.symbol}.")
        return is_ok

    def find_rules(self, contract: Contract) -> SymbolPriceIncrement:
        """
        Find market rules for the contract

        Try it with cache, If cache missed, let's fetch from IB
        """
        for elm in self.market_rules:
            if elm.symbol == get_ticker(contract):
                logger.debug(f"found market rules from cache: {elm.symbol}")
                return elm

        if self.req_market_rules(contract):
            for elm in self.market_rules:
                if elm.symbol == get_ticker(contract):
                    logger.debug(f"found market rules after fetching: {elm.symbol}")
                    return elm

        logger.warning(
            f"no market rule available to: {contract.secType},{get_ticker(contract)}"
        )
        return None

    def adjust_price(self, contract: Contract, price: float) -> float:
        """
        Increase a single price based on market rules and return it.

        Args:
            contract: The contract for which to adjust the price.
            price: The price to adjust.

        Returns:
            The adjusted price.
        """
        symbol_rules = self.find_rules(contract)
        new_price = price
        if symbol_rules:
            if len(symbol_rules.ranges) == 1:
                tick_size = symbol_rules.ranges[0].increment
                multiplier = 1 / tick_size
                new_price = math.ceil(price * multiplier) / multiplier
                if new_price != price:
                    logger.warning(
                        f"Price increased for {symbol_rules.symbol} from {price} to {new_price}"
                    )
            elif len(symbol_rules.ranges) > 1:
                logger.warning(
                    f"Market rule is not applicable for {get_ticker(contract)}"
                )
        return new_price

    def increase_price(self, contract: Contract, *args: List[float]) -> List[float]:
        """Increase prices and then return"""
        results = []
        for elm in args:
            results.append(self.adjust_price(contract, elm))
        return results
