
PREAMBLE
========

Many pieces of code are based on qtile.

Some useful literature to read:
  0. http://xcb.freedesktop.org/windowcontextandmanipulation/
  1. Extended Window Manager Hints (EWMH)
     http://standards.freedesktop.org/wm-spec/wm-spec-1.3.html
  2. Inter-Client Communication Conventions Manual (ICCM)
     http://tronche.com/gui/x/icccm/


TODO: clean-up orphant processes

# WHEN MOVING WINDOW
2016/10/11 23:00:09 hook.error: Traceback (most recent call last):
  File "/home/exe/github/swm/hook.py", line 59, in fire
    handler(event, *args, **kwargs)
  File "/home/exe/github/swm/myconfig.py", line 293, in move_left
    smart_snap('x', -step)
  File "/home/exe/github/swm/myconfig.py", line 247, in smart_snap
    window.set_geometry(x=snap)
  File "/home/exe/github/swm/window.py", line 171, in set_geometry
    self._conn.core.ConfigureWindowChecked(self.wid, mask, values).check()
  File "/usr/lib/python3.5/site-packages/xcffib/xproto.py", line 2579, in ConfigureWindow
    buf.write(xcffib.pack_list(value_list, "I"))
  File "/usr/lib/python3.5/site-packages/xcffib/__init__.py", line 762, in pack_list
    return struct.pack("=" + pack_type * len(from_), *from_)
struct.error: argument out of range


# when spawning panel
2016/10/11 23:02:05 WM.on_map_notify.notice: Window(27262979, "panel")
2016/10/11 23:02:05 WM.on_map_notify.notice: ['_NET_WM_STRUT', '_NET_WM_STRUT_PARTIAL', 'XdndAware', '_MOTIF_DRAG_RECEIVER_INFO', '_NET_WM_DESKTOP', '_NET_WM_STATE', 'WM_HINTS', '_MOTIF_WM_HINTS', '_NET_WM_SYNC_REQUEST_COUNTER', '_NET_WM_WINDOW_TYPE', '_NET_WM_USER_TIME_WINDOW', 'WM_CLIENT_LEADER', '_NET_WM_PID', 'WM_LOCALE_NAME', 'WM_CLIENT_MACHINE', 'WM_NORMAL_HINTS', 'WM_PROTOCOLS', 'WM_CLASS', 'WM_ICON_NAME', '_NET_WM_ICON_NAME', 'WM_NAME', '_NET_WM_NAME']

# pressing button on taskbar
2016/10/11 23:06:46 WM._xpoll.critical: got ClientMessage <xcffib.xproto.ClientMessageEvent object at 0x7f4f884dc6d8>
2016/10/11 23:06:46 hook.debug: ClientMessage (<xcffib.xproto.ClientMessageEvent object at 0x7f4f884dc6d8>,) {}
2016/10/11 23:06:46 WM.error: ['__class__', '__delattr__', '__dict__', '__dir__', '__doc__', '__eq__', '__format__', '__ge__', '__getattribute__', '__gt__', '__hash__', '__init__', '__le__', '__lt__', '__module__', '__ne__', '__new__', '__reduce__', '__reduce_ex__', '__repr__', '__setattr__', '__sizeof__', '__str__', '__subclasshook__', '__weakref__', 'bufsize', 'data', 'format', 'pack', 'response_type', 'sequence', 'synthetic', 'type', 'window']
2016/10/11 23:06:46 WM.error: client message: Super
