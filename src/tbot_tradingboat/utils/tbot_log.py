# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
__author__ = "Sangwook Lee"
__copyright__ = "Copyright (C) 2023 Plusgenie Ltd"
__license__ = "Dual-Licensing (GPL or Commercial License)"


import sys
from loguru import logger
from .tbot_env import shared

LOGGER_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "{extra[clientId]} | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def tbot_initialize_log():
    """Initialize log for Tbot"""
    logger.configure(extra={"clientId": shared.client_id})
    # Change the loglevel for loguru
    logger.remove()

    logger.add(sys.stderr, level=shared.loglevel, format=LOGGER_FORMAT)

    # Watch out too big logfile
    logger.add(
        shared.logfile,
        level=shared.loglevel,
        format=LOGGER_FORMAT,
        rotation="4 MB",
        compression="zip",
        enqueue=True,
        retention="7 days",
    )
