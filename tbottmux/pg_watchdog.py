#!/bin/env python3
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
import os
import sys
from dotenv import load_dotenv
from ib_insync import Watchdog, IBC, IB
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="TRACE")


# Set the default path to the .env file in the user's home directory
DEFAULT_ENV_FILE_PATH = os.path.expanduser("~/.env")

# Check if the .env file exists at the default path; if not, use the fallback path
if os.path.isfile(DEFAULT_ENV_FILE_PATH):
    ENV_FILE_PATH = DEFAULT_ENV_FILE_PATH
else:
    ENV_FILE_PATH = "/home/tbot/.env"

# Load the environment variables from the chosen .env file
load_dotenv(dotenv_path=ENV_FILE_PATH, override=True)

TBOT_IBC_TWS_VERSION = os.getenv("TBOT_IBC_TWS_VERSION", "10.21")
TBOT_IBC_INI_PATH = os.getenv("TBOT_IBC_INI_PATH", "/home/tbot/ibc/config.ini")


def on_connected(ibsync: IB):
    """Handle Connected event"""
    logger.debug(f"Connected : {ibsync}")


def on_error(ibsync, error, req_id, code):
    """Hande Error Event"""
    logger.debug(f"Error ({req_id}, {code}): {error}")


def run_ibc():
    """starting and stopping TWS/Gateway with watdog"""

    ibc = IBC(
        twsVersion=1019,
        gateway=True,
        tradingMode="paper",
        twsPath="/home/tbot/Jts",
        ibcPath="/opt/ibc",
        ibcIni="/home/tbot/ibc/config.ini",
    )
    ibsync = IB()
    ibsync.connectedEvent += on_connected
    ibsync.errorEvent += on_error
    watchdog = Watchdog(ibc, ibsync, port=4002, clientId=99)
    watchdog.start()
    ibsync.run()


def stop_handler(signal, frame, ibsync, watchdog):
    """Handles the shutdown signal and gracefully stops the IBC and IB connections"""
    logger.warning("Keyboard interrupt received. Stopping...")
    ibsync.disconnect()
    watchdog.stop()
    sys.exit(0)


if __name__ == "__main__":
    run_ibc()
