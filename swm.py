#!/usr/bin/env python3
from __future__ import print_function

"""
Many pieces of code are based on qtile.

Some useful literature to read:
  0. http://xcb.freedesktop.org/windowcontextandmanipulation/
  1. Extended Window Manager Hints (EWMH)
     http://standards.freedesktop.org/wm-spec/wm-spec-1.3.html
  2. Inter-Client Communication Conventions Manual (ICCM)
     http://tronche.com/gui/x/icccm/
"""

# from collections import defaultdict
# import subprocess
# import asyncio
# import traceback
# import signal
# import shlex
# import sys
# import os

# from xcffib.xproto import WindowError, AccessError, DrawableError
# from xcffib.xproto import CW, WindowClass, EventMask, ConfigWindow
# from xcffib import xproto
# import xcffib.randr
# import xcffib.xproto
# import xcffib

# from defs import XCB_CONN_ERRORS, \
#     PROPERTYMAP, SUPPORTED_ATOMS, ModMasks
# from desktop import Desktop
# from window import Window
# from wm import WM

# from useful.log import Log

# DEBUG = True
