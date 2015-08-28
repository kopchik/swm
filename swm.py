#!/usr/bin/env python3
"""
Based on qtile code.
"""

import xcffib
import xcffib.randr
import xcffib.xproto
from xcffib.xproto import CW, WindowClass, EventMask
from xcffib.xproto import WindowError, AccessError, DrawableError

from collections import defaultdict
import asyncio
import signal
import os

"""
Hierachy:
WM
Screen
Window
"""

# http://standards.freedesktop.org/wm-spec/latest/ar01s05.html#idm139870830002400
WindowTypes = {
    '_NET_WM_WINDOW_TYPE_DESKTOP': "desktop",
    '_NET_WM_WINDOW_TYPE_DOCK': "dock",
    '_NET_WM_WINDOW_TYPE_TOOLBAR': "toolbar",
    '_NET_WM_WINDOW_TYPE_MENU': "menu",
    '_NET_WM_WINDOW_TYPE_UTILITY': "utility",
    '_NET_WM_WINDOW_TYPE_SPLASH': "splash",
    '_NET_WM_WINDOW_TYPE_DIALOG': "dialog",
    '_NET_WM_WINDOW_TYPE_DROPDOWN_MENU': "dropdown",
    '_NET_WM_WINDOW_TYPE_POPUP_MENU': "menu",
    '_NET_WM_WINDOW_TYPE_TOOLTIP': "tooltip",
    '_NET_WM_WINDOW_TYPE_NOTIFICATION': "notification",
    '_NET_WM_WINDOW_TYPE_COMBO': "combo",
    '_NET_WM_WINDOW_TYPE_DND': "dnd",
    '_NET_WM_WINDOW_TYPE_NORMAL': "normal",
}


PropertyMap = {
    # ewmh properties
    "_NET_DESKTOP_GEOMETRY": ("CARDINAL", 32),
    "_NET_SUPPORTED": ("ATOM", 32),
    "_NET_SUPPORTING_WM_CHECK": ("WINDOW", 32),
    "_NET_WM_NAME": ("UTF8_STRING", 8),
    "_NET_WM_PID": ("CARDINAL", 32),
    "_NET_CLIENT_LIST": ("WINDOW", 32),
    "_NET_CLIENT_LIST_STACKING": ("WINDOW", 32),
    "_NET_NUMBER_OF_DESKTOPS": ("CARDINAL", 32),
    "_NET_CURRENT_DESKTOP": ("CARDINAL", 32),
    "_NET_DESKTOP_NAMES": ("UTF8_STRING", 8),
    "_NET_WORKAREA": ("CARDINAL", 32),
    "_NET_ACTIVE_WINDOW": ("WINDOW", 32),
    "_NET_WM_DESKTOP": ("CARDINAL", 32),
    "_NET_WM_STRUT": ("CARDINAL", 32),
    "_NET_WM_STRUT_PARTIAL": ("CARDINAL", 32),
    "_NET_WM_WINDOW_OPACITY": ("CARDINAL", 32),
    "_NET_WM_WINDOW_TYPE": ("CARDINAL", 32),
    # Net State
    "_NET_WM_STATE": ("ATOM", 32),
    "_NET_WM_STATE_STICKY": ("ATOM", 32),
    "_NET_WM_STATE_SKIP_TASKBAR": ("ATOM", 32),
    "_NET_WM_STATE_FULLSCREEN": ("ATOM", 32),
    "_NET_WM_STATE_MAXIMIZED_HORZ": ("ATOM", 32),
    "_NET_WM_STATE_MAXIMIZED_VERT": ("ATOM", 32),
    "_NET_WM_STATE_ABOVE": ("ATOM", 32),
    "_NET_WM_STATE_BELOW": ("ATOM", 32),
    "_NET_WM_STATE_MODAL": ("ATOM", 32),
    "_NET_WM_STATE_HIDDEN": ("ATOM", 32),
    "_NET_WM_STATE_DEMANDS_ATTENTION": ("ATOM", 32),
    # Xembed
    "_XEMBED_INFO": ("_XEMBED_INFO", 32),
    # ICCCM
    "WM_STATE": ("WM_STATE", 32),
    # Qtile-specific properties
    "QTILE_INTERNAL": ("CARDINAL", 32)
}


XCB_CONN_ERRORS = {
    1: 'XCB_CONN_ERROR',
    2: 'XCB_CONN_CLOSED_EXT_NOTSUPPORTED',
    3: 'XCB_CONN_CLOSED_MEM_INSUFFICIENT',
    4: 'XCB_CONN_CLOSED_REQ_LEN_EXCEED',
    5: 'XCB_CONN_CLOSED_PARSE_ERR',
    6: 'XCB_CONN_CLOSED_INVALID_SCREEN',
    7: 'XCB_CONN_CLOSED_FDPASSING_FAILED',
}


class MaskMap(object):
    """
        A general utility class that encapsulates the way the mask/value idiom
        works in xpyb. It understands a special attribute _maskvalue on
        objects, which will be used instead of the object value if present.
        This lets us passin a Font object, rather than Font.fid, for example.
    """
    def __init__(self, obj):
        self.mmap = []
        for i in dir(obj):
            if not i.startswith("_"):
                self.mmap.append((getattr(obj, i), i.lower()))
        self.mmap.sort()

    def __call__(self, **kwargs):
        """
            kwargs: keys should be in the mmap name set

            Returns a (mask, values) tuple.
        """
        mask = 0
        values = []
        for m, s in self.mmap:
            if s in kwargs:
                val = kwargs.get(s)
                if val is not None:
                    mask |= m
                    values.append(getattr(val, "_maskvalue", val))
                del kwargs[s]
        if kwargs:
            raise ValueError("Unknown mask names: %s" % list(kwargs.keys()))
        return mask, values


class AtomCache(object):
    def __init__(self, conn):
        self.conn = conn
        self.atoms = {}
        self.reverse = {}

        # We can change the pre-loads not to wait for a return
        for name in WindowTypes.keys():
            self.insert(name=name)

        for i in dir(xcffib.xproto.Atom):
            if not i.startswith("_"):
                self.insert(name=i, atom=getattr(xcffib.xproto.Atom, i))

    def insert(self, name=None, atom=None):
        assert name or atom
        if atom is None:
            c = self.conn.core.InternAtom(False, len(name), name)
            atom = c.reply().atom
        if name is None:
            c = self.conn.conn.core.GetAtomName(atom)
            name = c.reply().name.to_string()
        self.atoms[name] = atom
        self.reverse[atom] = name

    def get_name(self, atom):
        if atom not in self.reverse:
            self.insert(atom=atom)
        return self.reverse[atom]

    def __getitem__(self, key):
        if key not in self.atoms:
            self.insert(name=key)
        return self.atoms[key]


class Screen:
  def __init__(self, root):
    self.root = root


class Window:
  def __init__(self, wm, wid):
    self.wid = wid
    self.wm = wm

  def set_attribute(self, **kwargs):
      mask, values = AttributeMasks(**kwargs)
      self.wm._conn.core.ChangeWindowAttributesChecked(
          self.wid, mask, values
      )

  # TODO: rename to set_prop
  def set_property(self, name, value, type=None, format=None):
      """
          name: String Atom name
          type: String Atom name
          format: 8, 16, 32
      """
      if name in PropertyMap:
          if type or format:
              raise ValueError(
                  "Over-riding default type or format for property."
              )
          type, format = PropertyMap[name]
      else:
          if None in (type, format):
              raise ValueError(
                  "Must specify type and format for unknown property."
              )

      if isinstance(value, str):
        # xcffib will pack the bytes, but we should encode them properly
        value = value.encode()
      elif isinstance(value, int):
        value = [value]

      self.wm._conn.core.ChangePropertyChecked(
          xcffib.xproto.PropMode.Replace,
          self.wid,
          self.wm.atoms[name],
          self.wm.atoms[type],
          format,  # Format - 8, 16, 32
          len(value),
          value
      ).check()





AttributeMasks = MaskMap(CW)

SUPPORTED_ATOMS = [
    # From http://standards.freedesktop.org/wm-spec/latest/ar01s03.html
    '_NET_SUPPORTED',
    '_NET_CLIENT_LIST',
    '_NET_CLIENT_LIST_STACKING',
    '_NET_CURRENT_DESKTOP',
    '_NET_ACTIVE_WINDOW',
    # '_NET_WORKAREA',
    '_NET_SUPPORTING_WM_CHECK',
    # From http://standards.freedesktop.org/wm-spec/latest/ar01s05.html
    '_NET_WM_NAME',
    '_NET_WM_VISIBLE_NAME',
    '_NET_WM_ICON_NAME',
    '_NET_WM_DESKTOP',
    '_NET_WM_WINDOW_TYPE',
    '_NET_WM_STATE',
    '_NET_WM_STRUT',
    '_NET_WM_STRUT_PARTIAL',
    '_NET_WM_PID',
]

class WM:
  """
    Hide all dirty implementation details of XCB.
    Other classes should use this class to interface with X.
  """
  root = None
  atoms = None

  def create_window(self, x, y, width, height):
    wid = self._conn.generate_id()
    self._conn.core.CreateWindow(
        self.xcb_default_screen.root_depth,
        wid,
        self.xcb_default_screen.root,
        x, y, width, height, 0,
        WindowClass.InputOutput,
        self.xcb_default_screen.root_visual,
        CW.BackPixel | CW.EventMask,
        [
            self.xcb_default_screen.black_pixel,
            EventMask.StructureNotify | EventMask.Exposure
        ]
    )
    return Window(self, wid)

  def __init__(self, display=None):
    self.hook = Hook()
    if not display:
      display = os.environ.get("DISPLAY")
    self._conn = xcffib.connect(display=display)
    self.atoms = AtomCache(self._conn)
    # 'create' root window
    xcb_setup = self._conn.get_setup()
    xcb_screens = [i for i in xcb_setup.roots]
    self.xcb_default_screen = xcb_screens[self._conn.pref_screen]
    root_wid = self.xcb_default_screen.root
    self.root = Window(self, root_wid)

    self.root.set_attribute(
        eventmask=(
            EventMask.StructureNotify |
            EventMask.SubstructureNotify |
            EventMask.SubstructureRedirect |
            EventMask.EnterWindow |
            EventMask.LeaveWindow
        )
    )

    # INFORM X WHICH FEATURES WE SUPPORT
    self.root.set_property( '_NET_SUPPORTED', [self.atoms[x] for x in SUPPORTED_ATOMS])

    # PRETEND TO BE A WINDOW MANAGER
    supporting_wm_check_window = self.create_window(-1, -1, 1, 1)
    supporting_wm_check_window.set_property('_NET_WM_NAME', "SWM")
    self.root.set_property('_NET_SUPPORTING_WM_CHECK', supporting_wm_check_window.wid)
    # TODO: set cursor
    self.ignoreEvents = set([
        xcffib.xproto.KeyReleaseEvent,
        xcffib.xproto.ReparentNotifyEvent,
        xcffib.xproto.CreateNotifyEvent,
        # DWM handles this to help "broken focusing windows".
        xcffib.xproto.MapNotifyEvent,
        xcffib.xproto.LeaveNotifyEvent,
        xcffib.xproto.FocusOutEvent,
        xcffib.xproto.FocusInEvent,
        xcffib.xproto.NoExposureEvent
    ])

    self.flush()   # TODO: why?
    self._xpoll()   # the event loop is not yet there, but we might have some pending events...
    # TODO: self.grabMouse


    # TODO: self.scan() get list of already opened windows
    # TODO: self.update_net_desktops()

    # setup event loop
    self._eventloop = asyncio.new_event_loop()
    self._eventloop.add_signal_handler(signal.SIGINT, self.stop)
    self._eventloop.add_signal_handler(signal.SIGTERM, self.stop)
    self._eventloop.set_exception_handler(
        lambda x, y: print("Got an exception in poll loop")  # TODO: more details
    )
    fd = self._conn.get_file_descriptor()
    self._eventloop.add_reader(fd, self._xpoll)

  def finalize(self):
    raise NotImplementedError("TODO")

  def flush(self):
    return self._conn.flush()

  def xsync(self):
    # The idea here is that pushing an innocuous request through the queue
    # and waiting for a response "syncs" the connection, since requests are
    # serviced in order.
    self.conn.core.GetInputFocus().reply()

  def stop(self):
    print('Stopping eventloop')
    self._eventloop.stop()

  def loop(self):
      try:
          self._eventloop.run_forever()
      finally:
          self.finalize()


  def _xpoll(self):
    while True:
      # TODO: too long try ... catch
      try:
          e = self._conn.poll_for_event()  # TODO: renane to XCB event
          if not e:
              print("no events in XCB queue")
              break

          evname = e.__class__.__name__

          if evname.endswith("Event"):
              evname = evname[:-5]

          if e.__class__ in self.ignoreEvents:
            print("ignoring", e)
            continue
          self.hook.fire(evname, e)
      # Catch some bad X exceptions. Since X is event based, race
      # conditions can occur almost anywhere in the code. For
      # example, if a window is created and then immediately
      # destroyed (before the event handler is evoked), when the
      # event handler tries to examine the window properties, it
      # will throw a WindowError exception. We can essentially
      # ignore it, since the window is already dead and we've got
      # another event in the queue notifying us to clean it up.
      except (WindowError, AccessError, DrawableError):
          pass

      except Exception as e:
          error_code = self._conn.has_error()
          if error_code:
              error_string = XCB_CONN_ERRORS[error_code]
              print("Shutting down due to X connection error %s (%s)" %
                  (error_string, error_code))
              self.stop()
              break

          print("Got an exception in poll loop", e)


class SupressEvent:
  pass


class Hook:
  def __init__(self):
    self.cb_map = defaultdict(list)

  def fire(self, event, *args, **kwargs):
    handlers = self.cb_map[event]
    if not handlers:
       print("no handler for", event)
    for handler in handlers:
      try:
        handler(event, *args, **kwargs)
      except SupressEvent:
        break
      except Exception as e:
        print("err in cb", handler, e)

if __name__ == '__main__':
  wm = WM()
  wm.loop()
  print("BYE!")
  
