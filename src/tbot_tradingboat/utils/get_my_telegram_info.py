# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.
"""
import os
import json

from requests import get

TOKEN = os.environ.get("TBOT_TELEGRAM_TOKEN", "")

url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"

data = get(url, timeout=10).json()
print(json.dumps(data, indent=4))
