#!/bin/bash

TBOT_APP_HOME='/home/tbot/develop/github/tbot-tradingboat'

# this is called by crontab @reboot
if [ -f "/home/tbot/.profile" ]; then
  source "/home/tbot/.profile"
fi

# Give time to other tmux clients

# Install libtmux and loguru globally
# pip install --upgrade pip libtmux==0.21.0
# pip install loguru

# Check libtmux version number
LIBTMUX_VERSION=$(pip show libtmux | grep Version | awk '{print $2}')
if [[ "$LIBTMUX_VERSION" < "0.21.0" ]]; then
  echo "Error: libtmux version is lower than 0.21.0. Please upgrade libtmux before continuing."
  exit 1
fi

t_cmd="cd $TBOT_APP_HOME;\
. .venv/bin/activate;\
python src/tbot_tradingboat/main.py"

$TBOT_APP_HOME/tbottmux/pg_tmux_main.py -a start -c "$t_cmd" -w 'TBOT'
