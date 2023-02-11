#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023. All Rights Reserved.

You can run this script via 'crontab -e'
For example:
--------------------------------------------------------------------------------------
@reboot /home/tbot/develop/github/tbot-tradingboat/tbottmux/run_ngrok_flask_tbot.sh
--------------------------------------------------------------------------------------

It will launch NGROK/TVWB/TBOT in Tmux Windows everytime the system reboots
"""
__author__ = "Sangwook Lee"
__copyright__ = "Copyright (C) 2023 Plusgenie Ltd"
__license__ = "Dual-Licensing (GPL or Commercial License)"


from functools import wraps

import sys
import subprocess
import getopt
from typing import Tuple

from loguru import logger
import libtmux

logger.remove()
logger.add(sys.stderr, level="TRACE")

TBOT_SESSION = "tbot"


def mark(func):
    """
    Prints Enter/Exit of functions
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(f"Entering {func.__name__}")
        out = func(*args, **kwargs)
        logger.debug(f"Exiting {func.__name__}")
        return out

    return wrapper


class TmuxTbot:
    """
    The TmuxTbot class provdes a way to launch TBOT/FLASK into a fixed TMUX session.
    The session will have a few Windows.
    """

    @property
    def cls(self):
        """Configure classname"""
        return type(self).__name__

    def __init__(self):
        try:
            self.server = libtmux.Server()
        except BaseException as err:
            logger.critical(f"{err}")
        self.session_default_name = TBOT_SESSION
        # Fill session, window, pane
        self.session_default = self.find_tmux_session()

    @mark
    def _create_window_per_cmd(self, command: str, window_name: str):
        """Create a window per command and then attach it to the default session"""
        for window in self.session_default.windows:
            if window.window_name == window_name:
                logger.error("requested window exists")
                return
        window = self.session_default.new_window(attach=False, window_name=window_name)
        # Once a window is created, there will be an attached pane automatically
        window.attached_pane.send_keys(command)

    @mark
    def tb_start(self, command: str, window_name: str):
        """
        Start a new pane for the command.
        if there is no session/window, it will create them at first
        """
        if not self.session_default:
            # A new session will create one window and one pane by default
            session = self.server.new_session(
                self.session_default_name, window_name="def_win"
            )
            logger.success(f"creating a new session {self.session_default_name}")

            self.session_default = session
            if not self.session_default:
                logger.error("failed to create a new_session")
                return
        self._create_window_per_cmd(command, window_name)

    def tb_stop(self, cleanup_command=None):
        """Kill master session with the clean-up"""
        if cleanup_command:
            subprocess.call(cleanup_command, shell=True)
        if self.session_default:
            self.session_default.kill_session()

    @mark
    def find_tmux_session(self):
        """
        Find the specific session created for Trading Bot
        """
        ret = None
        try:
            for session in self.server.sessions:
                if session.session_name == self.session_default_name:
                    logger.info(
                        f"found| session_id={session.session_id}, "
                        f"session_name={session.session_name}"
                    )
                    ret = session
                    break
        except BaseException as err:
            logger.error(f"{err}")
        if not ret:
            logger.trace("No existing tmux session")
        return ret


def usage():
    """Create usage"""
    mystring = """
Send command into the pre-defined Tmux session
usage: {prg} -a  [start | stop] -c [command to a pane] -w [windnow name]
-a :action
    start - send the command to Tmux session as creating window
    stop - Kill Tmux session including all windows
-c :command, this should be used with -a
-w :window name: this should be used with -a
    ex:
        ${prg} -a start -c 'ls -al' -w TBOT
        ${prg} -a stop
        """.format(
        prg=sys.argv[0]
    )
    logger.info(mystring)


def get_args() -> Tuple:
    """Get Arguments"""
    action = None
    command = None
    window_name = None
    try:
        # 'a:' ->  'a' needs an argument, 'c:' -> 'c' needs an argument
        opts, args = getopt.gnu_getopt(sys.argv[1:], "ha:c:w:")
    except getopt.GetoptError:
        usage()
        sys.exit(2)
    for key, val in opts:
        if key == "-h":
            usage()
            sys.exit()
        elif key == "-a":
            action = val
        elif key == "-c":
            command = val
        elif key == "-w":
            window_name = val
    logger.trace(f"args: {action, command, window_name}")
    return action, command, window_name


def get_cmdline():
    """Get command lines"""
    action, command, window_name = get_args()
    logger.trace(f"action,command,window_name={action, command, window_name}")

    if not action:
        usage()
        sys.exit(-1)
    tbot = TmuxTbot()
    if action == "start":
        if command and window_name:
            tbot.tb_start(command, window_name)
        else:
            logger.critical(f"{action, command, window_name}")
    elif action == "stop":
        tbot.tb_stop()
    else:
        usage()


if __name__ == "__main__":
    get_cmdline()
