# -*- coding: utf-8 -*-
"""
TradingBoat © Copyright, Plusgenie Limited 2023.
All Rights Reserved.
"""

__author__ = "Sangwook Lee"
__copyright__ = "Copyright (C) 2023 Plusgenie Ltd"
__license__ = "Dual-Licensing (GPL or Commercial License)"

# strtobool was copied from https://github.com/python/cpython/blob/3.10/Lib/distutils/util.py#L308
# under the license of https://github.com/python/cpython/blob/main/LICENSE


def strtobool(val):
    """
    Convert a string representation of truth to true (1) or false (0).
    True values are 'y', 'yes', 't', 'true', 'on', and '1'; false values
    are 'n', 'no', 'f', 'false', 'off', and '0'.  Raises ValueError if
    'val' is anything else.

    Args:
        val (str): A string representation of truth

    Returns:
        int: A boolean value represented as an integer (0 or 1)
    """
    val = val.lower()
    if val in ('y', 'yes', 't', 'true', 'on', '1'):
        return 1
    elif val in ('n', 'no', 'f', 'false', 'off', '0'):
        return 0
    else:
        raise ValueError(f"invalid truth value: {val}")
