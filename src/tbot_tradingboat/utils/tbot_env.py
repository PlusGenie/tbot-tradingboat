# -*- coding: utf-8 -*-
"TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved."
import os
from dotenv import load_dotenv
from .objects import EnvSettings

# Set the default path to the .env file in the user's home directory
DEFAULT_ENV_FILE_PATH = os.path.expanduser("~/.env")

# Check if the .env file exists at the default path; if not, use the fallback path
if os.path.isfile(DEFAULT_ENV_FILE_PATH):
    ENV_FILE_PATH = DEFAULT_ENV_FILE_PATH
else:
    ENV_FILE_PATH = "/home/tbot/.env"

# Load the environment variables from the chosen .env file
load_dotenv(dotenv_path=ENV_FILE_PATH, override=True)

# Create an instance of the EnvSettings class to store and manage the environment variables
shared = EnvSettings()
