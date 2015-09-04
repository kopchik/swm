#!/usr/bin/env python3
from __future__ import print_function

"""
Many pieces of code are based on qtile.

Some useful literature to read:
  0. http://xcb.freedesktop.org/windowcontextandmanipulation/
  1. Extended Window Manager Hints (EWMH) http://standards.freedesktop.org/wm-spec/wm-spec-1.3.html
  2. Inter-Client Communication Conventions Manual (ICCM) http://tronche.com/gui/x/icccm/
"""

from collections import defaultdict
from functools import  reduce
import operator
import asyncio
# import trollius as asyncio
import signal
import os

from xcffib.xproto import WindowError, AccessError, DrawableError
from xcffib.xproto import CW, WindowClass, EventMask, ConfigWindow
from xcffib import xproto
import xcffib.randr
import xcffib.xproto
import xcffib

from defs import XCB_CONN_ERRORS, WINDOW_TYPES, PROPERTYMAP, SUPPORTED_ATOMS, ModMasks
from xkeysyms import keysyms


# TODO: have no idea what is this class about.
class MaskMap:
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


# TODO: stolen from qtile. Probably, we want to re-factor it.
class AtomCache:
    def __init__(self, conn):
        self.conn = conn
        self.atoms = {}
        self.reverse = {}

        # We can change the pre-loads not to wait for a return
        for name in WINDOW_TYPES.keys():
            self.insert(name=name)

        for i in dir(xproto.Atom):
            if not i.startswith("_"):
                self.insert(name=i, atom=getattr(xproto.Atom, i))

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

AttributeMasks = MaskMap(CW)


def get_modmask(modifiers):
    """
    Translate a modifier mask specified as a list of strings into an or-ed
    bit representation.
    """
    masks = []
    for i in modifiers:
        try:
            masks.append(ModMasks[i])
        except KeyError:
            raise KeyError("Unknown modifier: %s" % i)
    if masks:
        return reduce(operator.or_, masks)
    else:
        return 0


class Xrandr:
  """ Represents screen as seen by xrandr. """
  def __init__(self, root, conn):
    self.screens = []
    self.root = root
    self._conn = conn(xcffib.randr.key)
    for i in self._conn.GetScreenResources(root.wid).reply().crtcs:
      info = self._conn.GetCrtcInfo(i, xcffib.CurrentTime).reply()
      self.screens.append(info)
    self.screen = self.screens[0]


    # reply = xcffib.randr.randrExtension.GetScreenResourcesCurrent(root).reply()
    # reply = xcffib.randr.`(runtime.viewport.root).reply()
    # print("XXXXXXXX", reply)

class Desktop:
  """ Class for virtual desktops. """
  def __init__(self, windows=None):
    if not windows:
      windows = []
    self.windows = windows
    self.cur_focus = None
    self.prev_focus = None

  def get_prev_focus(self):
    raise NotImplementedError

  def get_next_focus(self):
    raise NotImplementedError

  def show(self):
    for window in self.windows:
      window.show()

  def hide(self):
    for window in self.windows:
      window.hide()

  def window_add(self, window):
    if not self.cur_focus:
      self.cur_focus = window
    raise NotImplementedError

  def window_remove(self, window):
    self.windows.remove(window)
    raise NotImplementedError


class Window:
  def __init__(self, wm, wid):
    assert isinstance(wid, int), "wid must be int"
    assert isinstance(wm, WM),  "wid must be an instance of WM"
    self.wid = wid
    self.wm = wm
    self._conn = self.wm._conn
    self.prev_geometry = None

  def show(self):
    self._conn.core.MapWindow(self.wid).reply()  # TODO: is sync needed?

  def hide(self):
    self.wm.hide_window(self)

  def rise(self):
    """ Put window on top of others. TODO: what about focus? """
    mode = xproto.StackMode.Above
    self._conn.core.ConfigureWindow(self.wid, xproto.ConfigWindow.StackMode, [mode])

  def focus(self):
    """ Let window receive mouse and keyboard events. """
    # TODO: '_NET_ACTIVE_WINDOW'
    self._conn.core.SetInputFocus(xproto.InputFocus.PointerRoot,
                                  self.wid, xproto.Time.CurrentTime)
    self.wm.cur_desktop.cur_focus = self
    return self

  def kill(self):
    """ This is what happens to windows when Alt-F4 or Ctrl-w is pressed. """
    self._conn.core.KillClient(self.wid)

  def move(self, x=None, y=None, dx=0, dy=0):
    if dx or dy:
      x, y, width, height = self.geometry
      x += dx
      y += dy

    mask = xproto.ConfigWindow.X | xproto.ConfigWindow.Y
    value = [x, y]
    self._conn.core.ConfigureWindowChecked(self.wid, mask, value).check()  # TODO: what the hell is *Checked and check?
    return self

  def resize(self, x=None, y=None, dx=0, dy=0):
    if x and y:
      width = x
      height = y
    if dx and dy:
      x, y, width, height = self.geometry
      width += dx
      height += dy

    mask = xproto.ConfigWindow.Width | xproto.ConfigWindow.Height
    value = [width, height]
    self._conn.core.ConfigureWindowChecked(self.wid, mask, value).check()  # TODO: what the hell is *Checked and check?

  def toggle_maximize(self):
    if self.prev_geometry:
      self.set_geometry(*self.prev_geometry)
      self.prev_geometry = None
    else:
      self.prev_geometry = self.geometry
      screen = self.wm.xrandr.screen
      self.set_geometry(x=1,y=1, width=screen.width, height=screen.height)
      self.rise()

  @property
  def geometry(self):
    geom = self._conn.core.GetGeometry(self.wid).reply()
    return [geom.x, geom.y, geom.width, geom.height]

  def set_geometry(self, x=None,y=None, width=None, height=None):
    mask = 0
    values = []
    if x is not None:
      mask |= xproto.ConfigWindow.X
      values.append(x)
    if y is not None:
      mask |= xproto.ConfigWindow.Y
      values.append(y)
    if width is not None:
      mask |= xproto.ConfigWindow.Width
      values.append(width)
    if height is not None:
      mask |= xproto.ConfigWindow.Height
      values.append(height)
    self._conn.core.ConfigureWindowChecked(self.wid, mask, values).check()  # TODO: what the hell is *Checked and check?

  def warp(self):
    print("TODO WARPING DOES NOT WORK :(")
    self._conn.core.WarpPointer(0, self.wid, 0,0,0,0, 100, 100)
    return self

  def grab_key(self, modifiers, key):
    """ Don't know why one would do window-specific hotkeys, but here it is! """
    self.wm.grab_key(modifiers, key, window=self)

  def set_attr(self, **kwargs):
      mask, values = AttributeMasks(**kwargs)
      self.wm._conn.core.ChangeWindowAttributesChecked(
          self.wid, mask, values
      )

  # TODO: move this code to WM
  def set_prop(self, name, value, type=None, format=None):
      """
          name: String Atom name
          type: String Atom name
          format: 8, 16, 32
      """
      if name in PROPERTYMAP:
          if type or format:
              raise ValueError(
                  "Over-riding default type or format for property."
              )
          type, format = PROPERTYMAP[name]
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
          xproto.PropMode.Replace,
          self.wid,
          self.wm.atoms[name],
          self.wm.atoms[type],
          format,  # Format - 8, 16, 32
          len(value),
          value
      ).check()

  def __lt__(self, other):  # used for sorting and comparison
    return True

  def __repr__(self):
    return "Window(%s)" % self.wid


class Keyboard:
  """ Just keyboard service functions. """
  def __init__(self, xcb_setup, conn):
    self._conn = conn
    self.code_to_syms = {}
    self.first_sym_to_code = {}

    first = xcb_setup.min_keycode
    count = xcb_setup.max_keycode - xcb_setup.min_keycode + 1
    q = self._conn.core.GetKeyboardMapping(first, count).reply()
    assert len(q.keysyms) % q.keysyms_per_keycode == 0,  \
        "Wrong keyboard mapping from X server??"

    for i in range(len(q.keysyms) // q.keysyms_per_keycode):
        self.code_to_syms[first + i] = \
            q.keysyms[i * q.keysyms_per_keycode:(i + 1) * q.keysyms_per_keycode]
    for k, s in self.code_to_syms.items():
        if s[0] and not s[0] in self.first_sym_to_code:
            self.first_sym_to_code[s[0]] = k

  def key_to_code(self, key):
    assert key in keysyms, "unknown key"  # TODO: generate warning
    sym  = keysyms[key]
    return self.first_sym_to_code[sym]


class WM:
  """
      Provides basic building blocks to make a window manager.
      It hides all the dirty implementation details of XCB.
      Other classes should use its methods to interface with X.
  """
  root  = None
  atoms = None

  def __init__(self, display=None, desktops=None):
    # INIT SOME BASIC STUFF
    self.hook = Hook()
    self.windows = {}
    if not display:
      display = os.environ.get("DISPLAY")
    self._conn = xcffib.connect(display=display)
    self.atoms = AtomCache(self._conn)
    self.desktops = desktops or [Desktop()]
    self.cur_desktop = self.desktops[0]

    # CREATE ROOT WINDOW
    xcb_setup = self._conn.get_setup()
    xcb_screens = [i for i in xcb_setup.roots]
    self.xcb_default_screen = xcb_screens[self._conn.pref_screen]
    root_wid = self.xcb_default_screen.root
    self.root = Window(self, root_wid)
    self.windows[root_wid] = self.root

    self.root.set_attr(
        eventmask=(
            EventMask.StructureNotify |
            EventMask.SubstructureNotify |
            EventMask.SubstructureRedirect |
            EventMask.EnterWindow |
            EventMask.LeaveWindow |
            EventMask.PropertyChange
        )
    )

    # INFORM X WHICH FEATURES WE SUPPORT
    self.root.set_prop( '_NET_SUPPORTED', [self.atoms[x] for x in SUPPORTED_ATOMS])

    # PRETEND TO BE A WINDOW MANAGER
    supporting_wm_check_window = self.create_window(-1, -1, 1, 1)
    supporting_wm_check_window.set_prop('_NET_WM_NAME', "SWM")
    self.root.set_prop('_NET_SUPPORTING_WM_CHECK', supporting_wm_check_window.wid)

    # TODO: set cursor

    # EVENTS THAT HAVE LITTLE USE FOR US...
    self.ignoreEvents = set([
        # xproto.KeyReleaseEvent,
        xproto.ReparentNotifyEvent,
        # xproto.CreateNotifyEvent,
        # DWM handles this to help "broken focusing windows".
        xproto.MapNotifyEvent,
        xproto.ConfigureNotifyEvent,
        xproto.LeaveNotifyEvent,
        xproto.FocusOutEvent,
        xproto.FocusInEvent,
        xproto.NoExposureEvent
    ])
    # KEYBOARD
    self.kbd = Keyboard(xcb_setup, self._conn)

    # FLUSH PENDING STUFF
    self.xsync()    # apply settings
    self._xpoll()   # the event loop is not yet there, but we might have some pending events...
    # TODO: self.grabMouse
    self.scan()
    self.cur_desktop.cur_focus = sorted(self.windows.values())[-1].focus()

    # TODO: self.update_net_desktops()

    # SETUP EVENT LOOP
    self._eventloop = asyncio.new_event_loop()
    self._eventloop.add_signal_handler(signal.SIGINT, self.stop)
    self._eventloop.add_signal_handler(signal.SIGTERM, self.stop)
    self._eventloop.set_exception_handler(
        lambda x, y: print("Got an exception in poll loop")  # TODO: more details
    )
    fd = self._conn.get_file_descriptor()
    self._eventloop.add_reader(fd, self._xpoll)

    # HANDLE STANDARD EVENTS
    self.hook.register("MapRequest", self.on_map_request)
    self.hook.register("KeyPress",   self.on_key_press)
    self.hook.register("KeyRelease", self.on_key_release)
    self.hook.register("CreateNotify", self.on_window_create)
    self.hook.register("EnterNotify", self.on_window_enter)
    self.hook.register("ConfigureRequest", self.on_configure_window)
    # TODO: DestroyNotify

    self.xrandr = Xrandr(root=self.root, conn=self._conn)


  def on_window_create(self, evname=None, xcb_event=None, wid=None):
    if not wid:
      wid = xcb_event.window
    window = Window(self, wid)
    self.windows[wid] = window
    self.cur_desktop.windows.append(window)
    self._conn.core.ChangeWindowAttributesChecked(
        wid, CW.EventMask, [EventMask.EnterWindow])

  def on_window_enter(self, evname, xcb_event):
    wid = xcb_event.event
    window = self.windows[wid]
    self.hook.fire("window_enter", window)

  def on_map_request(self, evname, xcb_event):
    """ Map request is a request to draw the window on screen. """
    wid = xcb_event.window
    if wid not in self.windows:
      window = Window(self, wid)
      self.windows[wid] = window
    else:
      window = self.windows[wid]
    window.show()
    window.focus()

  def grab_key(self, modifiers, key,  owner_events=False, window=None):
    """ Intercept this key when it is pressed. If owner_events=False then
        the window in focus will not receive it. This is useful from WM hotkeys.
    """
    # TODO: check if key already grabbed?
    # Here is how X works with keys:
    # key => keysym => keycode
    # where `key' is something like 'a', 'b' or 'Enter',
    # `keysum' is what should be written on they key cap (physical keyboard)
    # and `keycode' is a number reported by the keyboard when the key is pressed.
    # Modifiers are keys like Shift, Alt, Win and some other buttons.

    if window is None:
      window = self.root

    keycode = self.kbd.key_to_code(key)
    modmask = get_modmask(modifiers)  # TODO: move to Keyboard
    event = ("on_key_press", modmask, keycode)
    pointer_mode = xproto.GrabMode.Async
    keyboard_mode = xproto.GrabMode.Async
    self._conn.core.GrabKey(
        owner_events,
        window.wid,
        modmask,
        keycode,
        pointer_mode,
        keyboard_mode
    )
    self.flush()
    return event

  def on_key_press(self, evname, xcb_event):
    # TODO: ignore capslock, scrolllock and other modifiers?
    modmap  = xcb_event.state
    keycode = xcb_event.detail
    event = ("on_key_press", modmap, keycode)
    self.hook.fire(event)

  def on_key_release(self, evname, xcb_event):
    modmap  = xcb_event.state
    keycode = xcb_event.detail
    event = ("on_key_release", modmap, keycode)
    self.hook.fire(event)

  def on_configure_window(self, _, event):
      # TODO: code from fpwm
      values = []
      if event.value_mask & ConfigWindow.X:
          values.append(event.x)
      if event.value_mask & ConfigWindow.Y:
          values.append(event.y)
      if event.value_mask & ConfigWindow.Width:
          values.append(event.width)
      if event.value_mask & ConfigWindow.Height:
          values.append(event.height)
      if event.value_mask & ConfigWindow.BorderWidth:
          values.append(event.border_width)
      if event.value_mask & ConfigWindow.Sibling:
          values.append(event.sibling)
      if event.value_mask & ConfigWindow.StackMode:
          values.append(event.stack_mode)
      self._conn.core.ConfigureWindow(event.window, event.value_mask, values)

  def create_window(self, x, y, width, height):
    """ Create a window. Right now only used for initialisation, see __init__. """
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

  def scan(self):
    """ Get all windows in the system. """
    q = self._conn.core.QueryTree(self.root.wid).reply()
    for wid in q.children:
      if wid not in self.windows:
        self.on_window_create(wid=wid)
    print("WINDOWS:", sorted(self.windows.values()))


  def finalize(self):
    """ This code is run when event loop is terminated. """
    pass  # currently nothing to do here

  def flush(self):
    """ Force pending X request to be sent.
        By default XCB aggressevly buffers for performance reasons. """
    return self._conn.flush()

  def xsync(self):
    """ Flush XCB queue and wait till it is processed by X server. """
    # The idea here is that pushing an innocuous request through the queue
    # and waiting for a response "syncs" the connection, since requests are
    # serviced in order.
    self._conn.core.GetInputFocus().reply()

  def stop(self):
    """ It does what it says. """
    print('Stopping eventloop')
    self._eventloop.stop()

  def loop(self):
    """ DITTO """
    try:
        self._eventloop.run_forever()
    finally:
        self.finalize()

  def _xpoll(self):
    """ Fetch incomming events (if any) and call hooks. """
    while True:
      # TODO: too long try ... catch
      try:
          e = self._conn.poll_for_event()  # TODO: renane to XCB event
          if not e:
            break

          evname = e.__class__.__name__
          if evname.endswith("Event"):
              evname = evname[:-5]

          if e.__class__ in self.ignoreEvents:
            print("ignoring", e)
            continue
          self.hook.fire(evname, e)
      # *Original description:
      # Catch some bad X exceptions. Since X is event based, race
      # conditions can occur almost anywhere in the code. For
      # example, if a window is created and then immediately
      # destroyed (before the event handler is evoked), when the
      # event handler tries to examine the window properties, it
      # will throw a WindowError exception. We can essentially
      # ignore it, since the window is already dead and we've got
      # another event in the queue notifying us to clean it up.
      # *My description:
      # Ok, kids, today I'll teach you how to write reliable interprise
      # software! You just catch all exceptions in a top-level loop
      # and ignore them. No, I'm kidding, these exceptions are no use
      # for us because we don't care if a window cannot be drawn or something.
      # We actually only need to handle just a few events and ignore the rest.
      # Hence, we do not process these errors.
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

          print("Got an exception in poll loop: %s (%s)" %  (e, type(e)))
    self.flush()  # xcb often doesn't flush implicitly


class SupressEvent(Exception):
  """ Raise this one in callback if further callbacks shouldn't be called. """


class Hook:
  """ Simple callback dispatcher. """
  def __init__(self):
    self.cb_map = defaultdict(list)

  def decor(self, event):
    def wrap(cb):
      self.register(event, cb)
      return cb
    return wrap
  __call__ = decor

  def register(self, event, cb):
    self.cb_map[event].append(cb)

  def has_hook(self, event):
    return event in self.cb_map

  def fire(self, event, *args, **kwargs):
    if event not in self.cb_map:
       print("no handler for", event)
       return

    handlers = self.cb_map[event]
    for handler in handlers:
      try:
        handler(event, *args, **kwargs)
      # except SupressEvent:
        # break
      except Exception as err:
        msg="error on event {ev}: {err} ({typ}) (in {hdl})" \
                .format(err=err, typ=type(err), ev=event, hdl=handler)
        print(msg)


if __name__ == '__main__':
  import subprocess
  up, down, left, right = 'Up', 'Down', 'Left', 'Right'
  win = fail = 'mod4'
  ctrl = control = 'control'
  shift = 'shift'
  alt = 'mod1'
  tab = 'Tab'

  wm = WM()

  @wm.hook("window_enter")
  def switch_focus(event, window):
    # do not switch focus when moving over root window
    if window == wm.root:
      return
    window.focus()
    window.rise()

  # RESIZE
  @wm.hook(wm.grab_key([ctrl, shift], right))
  def expand_width(event):
    wm.cur_desktop.cur_focus.resize(dx=20)

  @wm.hook(wm.grab_key([ctrl, shift], left))
  def shrink_width(event):
    wm.cur_desktop.cur_focus.resize(dx=-20)

  @wm.hook(wm.grab_key([ctrl, shift], up))
  def expand_width(event):
    wm.cur_desktop.cur_focus.resize(dy=-20)

  @wm.hook(wm.grab_key([ctrl, shift], down))
  def shrink_width(event):
    wm.cur_desktop.cur_focus.resize(dy=20)

  # MOVE
  @wm.hook(wm.grab_key([ctrl], right))
  def move_right(event):
    wm.cur_desktop.cur_focus.move(dx=20)

  @wm.hook(wm.grab_key([ctrl], left))
  def move_left(event):
    wm.cur_desktop.cur_focus.move(dx=-20)

  @wm.hook(wm.grab_key([ctrl], up))
  def move_up(event):
    wm.cur_desktop.cur_focus.move(dy=-20)

  @wm.hook(wm.grab_key([ctrl], down))
  def move_down(event):
    wm.cur_desktop.cur_focus.move(dy=20).warp()

  # FOCUS
  @wm.hook(wm.grab_key([ctrl], 'p'))
  def switch_windows(event):
    desktop = wm.cur_desktop
    cur = desktop.cur_focus
    cur_idx = desktop.windows.index(cur)
    nxt = desktop.windows[cur_idx-1]
    switch_focus("some_fake_ev", nxt)

  @wm.hook(wm.grab_key([ctrl], 'n'))
  def switch_windows(event):
    desktop = wm.cur_desktop
    cur = desktop.cur_focus
    cur_idx = desktop.windows.index(cur)
    nxt = desktop.windows[cur_idx+1]
    switch_focus("some_fake_ev", nxt)

  # OTHER
  @wm.hook(wm.grab_key([alt], 'x'))
  def spawn_console(event):
    subprocess.Popen("urxvt")

  @wm.hook(wm.grab_key([ctrl], 'm'))
  def maximize(event):
    wm.cur_desktop.cur_focus.toggle_maximize()

  # subprocess.Popen("xcalc")
  # subprocess.Popen("xterm")
  subprocess.Popen("urxvt")
  wm.loop()
  print("BYE!")