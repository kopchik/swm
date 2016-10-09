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

from collections import defaultdict
import subprocess
import asyncio
import traceback
import signal
import shlex
import time
import sys
import os

from xcffib.xproto import WindowError, AccessError, DrawableError
from xcffib.xproto import CW, WindowClass, EventMask, ConfigWindow
from xcffib import xproto
import xcffib.randr
import xcffib.xproto
import xcffib

from defs import XCB_CONN_ERRORS, WINDOW_TYPES, \
    PROPERTYMAP, SUPPORTED_ATOMS, ModMasks
from xkeysyms import keysyms

from useful.mstring import prints
from useful.log import Log

DEBUG = True


def run(cmd):
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    # os.setpgrp supressses signal forwarding to children  # TODO: test this
    return subprocess.Popen(cmd, preexec_fn=os.setpgrp)


def run_(cmd):
    try:
        return run(cmd)
    except Exception as err:
        print("failed to exec %s: %s" % (cmd, err))


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

AttributeMasks = MaskMap(CW)


# TODO: stolen from qtile. Probably, we want to re-factor it.
class AtomCache:

    def __init__(self, conn):
        self.conn = conn
        self.atoms = {}
        self.reverse = {}

        # We can change the pre-loads not to wait for a return
        # for name in WINDOW_TYPES.keys():
        #     self.insert(name=name)

        # for i in dir(xproto.Atom):
        #     if not i.startswith("_"):
        #         self.insert(name=i, atom=getattr(xproto.Atom, i))

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


def get_modmask(modifiers):
    result = 0
    for m in modifiers:
        assert m in ModMasks, "unknown modifier %s" % m
        result |= ModMasks[m]
    return result


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


# TODO: suppress events
class Desktop:
    """ Support for virtual desktops. """

    def __init__(self, windows=None, name=None):
        if not name:
            name = "(desktop %s)" % id(self)
        self.log = Log("desktop %s" % name)
        if not windows:
            windows = []
        self.windows = windows
        self.name = name
        self.cur_focus = None
        self.prev_focus = None
        self.were_mapped = []

    def get_prev_focus(self):
        raise NotImplementedError

    def get_next_focus(self):
        raise NotImplementedError

    def show(self):
        for window in self.were_mapped:
            self.log.debug("showing window %s" % window)
            window.show()
        else:
            self.log.debug("no windows on this desktop to show")
        self.were_mapped.clear()

    def hide(self):
        for window in self.windows:
            if window.mapped:
                self.log.debug("hiding window %s" % window)
                window.hide()
                self.were_mapped.append(window)
        self.log.debug("followind windows were hidden: %s" % self.were_mapped)

    def window_add(self, window):
        if not self.cur_focus:
            self.cur_focus = window
        raise NotImplementedError

    def window_remove(self, window):
        self.windows.remove(window)
        raise NotImplementedError

    def __repr__(self):
        return "Desktop(%s)" % self.name


class Window:

    def __init__(self, wm, wid, mapped=True, name=None):
        assert isinstance(wm, WM), "wid must be an instance of WM"
        assert isinstance(wid, int), "wid must be int"
        self.wid = wid
        self.wm = wm
        self._conn = self.wm._conn
        self.prev_geometry = None
        self.name = name or self.get_name()  # TODO: this is not updated
        # do it after self.name is set (so repr works)
        self.log = Log(str(self))
        self.mapped = mapped
        # subscribe for notifications
        self._conn.core.ChangeWindowAttributesChecked(
            wid, CW.EventMask, [EventMask.EnterWindow])

    def show(self):
        self.log.show.debug("showing")
        self._conn.core.MapWindow(self.wid)  # TODO: is sync needed?
        self.wm.xsync()
        self.mapped = True

    def hide(self):
        self._conn.core.UnmapWindow(self.wid)
        self.mapped = False

    def rise(self):
        """ Put window on top of others. TODO: what about focus? """
        mode = xproto.StackMode.Above
        self._conn.core.ConfigureWindow(self.wid,
                                        xproto.ConfigWindow.StackMode,
                                        [mode])

    def focus(self):
        """ Let window receive mouse and keyboard events.
            X expects window to be mapped.
        """
        if not self.mapped:
            self.show()
        self.wm.cur_desktop.cur_focus = self
        # TODO: self.wm.root.set_property("_NET_ACTIVE_WINDOW", self.wid)
        self._conn.core.SetInputFocus(xproto.InputFocus.PointerRoot,
                                      self.wid, xproto.Time.CurrentTime)
        return self

    def kill(self):
        """ This is what happens to windows when Alt-F4 or Ctrl-w is pressed. """
        self._conn.core.KillClient(self.wid)

    def move(self, x=None, y=None, dx=0, dy=0):
        """ Like set_geometry, but with sanity check. """
        if dx or dy:
            x, y, width, height = self.geometry
            x += dx
            y += dy
        x = max(x, 0)
        y = max(y, 0)
        self.set_geometry(x=x, y=y)
        return self

    def resize(self, x=None, y=None, dx=0, dy=0):
        """ Like set_geometry, but with sanity check. """
        assert not ((x and y) and (dx or dy)), "wrong arguments"
        if x and y:
            width = x
            height = y
        else:
            x, y, width, height = self.geometry
            width += dx
            height += dy
        width = max(5, width)
        height = max(5, height)
        self.set_geometry(width=width, height=height)
        return self

    def toggle_maximize(self):
        if self.prev_geometry:
            self.set_geometry(*self.prev_geometry)
            self.prev_geometry = None
        else:
            self.prev_geometry = self.geometry
            screen = self.wm.xrandr.screen
            self.set_geometry(x=0, y=0, width=screen.width -
                              1, height=screen.height - 1)
            self.rise()

    @property
    def geometry(self):
        geom = self._conn.core.GetGeometry(self.wid).reply()
        return [geom.x, geom.y, geom.width, geom.height]

    def set_geometry(self, x=None, y=None, width=None, height=None):
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
        # TODO: what the hell is *Checked and check?
        self._conn.core.ConfigureWindowChecked(self.wid, mask, values).check()

    def get_name(self):
        # TODO: set self.name?
        to_try = [
            ("_NET_WM_VISIBLE_NAME", "UTF8_STRING"),
            ("_NET_WM_NAME", "UTF8_STRING"),
            (xproto.Atom.WM_NAME, xproto.GetPropertyType.Any),
        ]
        for prop, typ in to_try:
            name = self.get_prop(prop, typ, unpack=str)
            if name:
                print("NAME", name)
                return name
        return "(no name)"

    def warp(self):
        """ Does not work under Xephyr :( """
        x, y, width, height = self.geometry
        self._conn.core.WarpPointer(
            0, self.wid,                    # src_window, dst_window
            0, 0,                           # src_x, src_y
            0, 0,                           # src_width, src_height
            width // 2, height // 2         # dest_x, dest_y
        )
        self.wm.xsync()
        return self

    def get_attributes(self):
        return self._conn.core.GetWindowAttributes(self.wid).reply()

    def set_attr(self, **kwargs):
        mask, values = AttributeMasks(**kwargs)
        self.wm._conn.core.ChangeWindowAttributesChecked(
            self.wid, mask, values
        )

    def get_prop(self, prop, typ=None, unpack=None):
        """
            Return the contents of a property as a GetPropertyReply. If unpack
            is specified, a tuple of values is returned.  The type to unpack,
            either `str` or `int` must be specified.
        """
        if typ is None:
            if prop not in PROPERTYMAP:
                raise ValueError(
                    "Must specify type for unknown property."
                )
            else:
                typ, _ = PROPERTYMAP[prop]

        r = self._conn.core.GetProperty(
            False, self.wid,
            self.wm.atoms[prop] if isinstance(prop, (str, bytes)) else prop,
            self.wm.atoms[typ] if isinstance(typ, (str, bytes)) else typ,
            0, (2 ** 32) - 1
        ).reply()

        if not r.value_len:
            if unpack:
                return []
            return None
        elif unpack:
            # Should we allow more options for unpacking?
            if unpack is int:
                return r.value.to_atoms()
            elif unpack is str:
                return r.value.to_string()
        else:
            return r

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
        name = self.name
        if len(name) > 20:
            name = name[:17] + '...'
        return "Window(%s, \"%s\")" % (self.wid, name)


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
                q.keysyms[
                    i * q.keysyms_per_keycode:(i + 1) * q.keysyms_per_keycode]
        for k, s in self.code_to_syms.items():
            if s[0] and not s[0] in self.first_sym_to_code:
                self.first_sym_to_code[s[0]] = k

    def key_to_code(self, key):
        assert key in keysyms, "unknown key"  # TODO: generate warning
        sym = keysyms[key]
        return self.first_sym_to_code[sym]


class WM:
    """
        Provides basic building blocks to make a window manager.
        It hides many dirty details about XCB. It was intended
        to provide minimum functionality, the rest supposed to
        be implemented by user in configuration file.
    """
    root = None   # type: Window
    atoms = None  # type: AtomCache

    def __init__(self, display=None, desktops=None):
        self.log = Log("WM")
        # INIT SOME BASIC STUFF
        self.hook = Hook()
        self.windows = {}
        if not display:
            display = os.environ.get("DISPLAY")

        try:
            self._conn = xcffib.connect(display=display)
        except xcffib.ConnectionException:
            sys.exit("cannot connect to %s" % display)

        self.atoms = AtomCache(self._conn)
        self.desktops = desktops or [Desktop()]
        self.cur_desktop = self.desktops[0]

        # CREATE ROOT WINDOW
        xcb_setup = self._conn.get_setup()
        xcb_screens = [i for i in xcb_setup.roots]
        self.xcb_default_screen = xcb_screens[self._conn.pref_screen]
        root_wid = self.xcb_default_screen.root
        self.root = Window(self, root_wid, name="root", mapped=True)
        self.windows[root_wid] = self.root
#        for desktop in self.desktops:
#            desktop.windows.append(self.root)

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
        self.root.set_prop('_NET_SUPPORTED', [
                           self.atoms[x] for x in SUPPORTED_ATOMS])

        # PRETEND TO BE A WINDOW MANAGER
        supporting_wm_check_window = self.create_window(-1, -1, 1, 1)
        supporting_wm_check_window.set_prop('_NET_WM_NAME', "SWM")
        self.root.set_prop('_NET_SUPPORTING_WM_CHECK',
                           supporting_wm_check_window.wid)

        # TODO: set cursor

        # EVENTS THAT HAVE LITTLE USE FOR US...
        self.ignoreEvents = set([
            "KeyRelease",
            "ReparentNotify",
            # "CreateNotify",
            # DWM handles this to help "broken focusing windows".
            # "MapNotify",
            "ConfigureNotify",
            "LeaveNotify",
            "FocusOut",
            "FocusIn",
            "NoExposure",
        ])
        # KEYBOARD
        self.kbd = Keyboard(xcb_setup, self._conn)

        # FLUSH XCB BUFFER
        self.xsync()    # apply settings
        # the event loop is not yet there, but we might have some pending
        # events...
        self._xpoll()
        # TODO: self.grabMouse

        # NOW IT'S TIME TO GET PHYSICAL SCREEN CONFIGURATION
        self.xrandr = Xrandr(root=self.root, conn=self._conn)

        # GET LIST OF ALL PRESENT WINDOWS AND FOCUS ON THE LAST
        self.scan()     #
        self.cur_desktop.cur_focus = sorted(self.windows.values())[-1].focus()

        # TODO: self.update_net_desktops()

        # SETUP EVENT LOOP
        self._eventloop = asyncio.new_event_loop()
        self._eventloop.add_signal_handler(signal.SIGINT, self.stop)
        self._eventloop.add_signal_handler(signal.SIGTERM, self.stop)
        self._eventloop.set_exception_handler(
            lambda loop, ctx: self.log.error(
                "Got an exception in {}: {}".format(loop, ctx))
        )
        fd = self._conn.get_file_descriptor()
        self._eventloop.add_reader(fd, self._xpoll)

        # HANDLE STANDARD EVENTS
        self.hook.register("MapRequest", self.on_map_request)
        self.hook.register("MapNotify", self.on_map_notify)
        self.hook.register("UnmapNotify", self.on_window_unmap)
        self.hook.register("KeyPress", self.on_key_press)
        # self.hook.register("KeyRelease", self.on_key_release)
        # self.hook.register("CreateNotify", self.on_window_create)
        self.hook.register("DestroyNotify", self.on_window_destroy)
        self.hook.register("EnterNotify", self.on_window_enter)
        self.hook.register("ConfigureRequest", self.on_configure_window)
        self.hook.register("MotionNotify", self.on_mouse_event)
        self.hook.register("ButtonPress", self.on_mouse_event)
        self.hook.register("ButtonRelease", self.on_mouse_event)

    def on_map_request(self, evname, xcb_event):
        """ Map request is a request to draw the window on screen. """
        wid = xcb_event.window
        if wid not in self.windows:
            window = Window(self, wid, mapped=True)
            self.log.CreateNotify.debug(
                "new window for ready for mapping: %s" % window)
            self.windows[wid] = window
            self.cur_desktop.windows.append(window)
        else:
            window = self.windows[wid]
            self.log.CreateNotify.debug("map request for %s" % window)
        window.show()
        window.focus()

    def on_map_notify(self, evname, xcb_event):
        wid = xcb_event.window
        if wid not in self.windows:
            # window is managed by the application, not by us
            return
        window = self.windows[wid]
        window.mapped = True
        self.log.on_map_notify.debug("map notify for %s" % window)

    def on_window_unmap(self, evname, xcb_event):
        wid = xcb_event.window
        if wid not in self.windows:
            return
        window = self.windows[wid]
        window.mapped = False
        self.hook.fire("window_unmap", window)

    def on_window_destroy(self, evname, xcb_event):
        wid = xcb_event.window
        if wid not in self.windows:
            return
        window = self.windows[wid]
        for desktop in self.desktops:
            try:
                desktop.windows.remove(window)
                print("%s removed from %s" % (self, desktop))
            except ValueError:
                pass
        del self.windows[wid]

    def on_window_enter(self, evname, xcb_event):
        wid = xcb_event.event
        window = self.windows[wid]
        self.log.on_window_enter("window_enter: %s %s" % (wid, window))
        self.hook.fire("window_enter", window)

    def grab_key(self, modifiers, key, owner_events=False, window=None):
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
        self.flush()  # TODO: do we need this?
        return event

    def on_key_press(self, evname, xcb_event):
        # TODO: ignore capslock, scrolllock and other modifiers?
        modmap = xcb_event.state
        keycode = xcb_event.detail
        event = ("on_key_press", modmap, keycode)
        self.hook.fire(event)

    def on_key_release(self, evname, xcb_event):
        modmap = xcb_event.state
        keycode = xcb_event.detail
        event = ("on_key_release", modmap, keycode)
        self.hook.fire(event)

    def grab_mouse(self, modifiers, button, owner_events=False, window=None):
        # http://www.x.org/archive/X11R7.7/doc/man/man3/xcb_grab_button.3.xhtml
        wid = (window or self.root).wid
        event_mask = xcffib.xproto.EventMask.ButtonPress |    \
            xcffib.xproto.EventMask.ButtonRelease |  \
            xcffib.xproto.EventMask.Button1Motion
        modmask = get_modmask(modifiers)
        pointer_mode = xproto.GrabMode.Async      # I don't know what it is
        keyboard_mode = xproto.GrabMode.Async     # do not block other keyboard events
        confine_to = xcffib.xproto.Atom._None     # do not restrict cursor movements
        cursor = xcffib.xproto.Atom._None         # do not change cursor
        event = ("on_mouse", modmask, button)     # event to be used in hooks

        self._conn.core.GrabButton(
            owner_events,
            wid,
            event_mask,
            pointer_mode,
            keyboard_mode,
            confine_to,
            cursor,
            button,
            modmask,
        )
        self.flush()  # TODO: do we need this?
        return event

    def switch_to_desk(self, desktop):
        #with self.hook.suppress("EnterNotify"):
            if isinstance(desktop, int):
                desktop = self.desktops[desktop]
            self.log.debug("switching from {} to {}".format(
                self.cur_desktop, desktop))
            self.cur_desktop.hide()
            self.cur_desktop = desktop
            self.cur_desktop.show()

    def on_mouse_event(self, evname, xcb_event):
        """evname is one of ButtonPress, ButtonRelease or MotionNotify."""
        # l = [(attr, getattr(xcb_event, attr)) for attr in sorted(dir(xcb_event)) if not attr.startswith('_')]
        # print(evname)
        # print(l)
        modmask = xcb_event.state & 0xff  # TODO: is the mask correct?
        if evname == 'MotionNotify':
            button = 1  # TODO
        else:
            button = xcb_event.detail

        event = ("on_mouse", modmask, button)
        # print(event)
        self.hook.fire(event, evname, xcb_event)

    def on_configure_window(self, _, event):
            # This code is so trivial that I just took it from fpwm as is :)
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
        """ Create a window. Right now only used for initialization, see __init__. """
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
            attrs = self._conn.core.GetWindowAttributes(wid).reply()
            # print(attrs, type(attrs))
            if attrs.map_state == xproto.MapState.Unmapped:
                self.log.scan.debug("window %s is not mapped, skipping" % wid)
                continue
            if wid not in self.windows:
                window = Window(wid=wid, wm=self, mapped=True)
                self.windows[wid] = window
                self.cur_desktop.windows.append(window)
        self.log.scan.info("the following windows are active: %s" %
                           sorted(self.windows.values()))

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
        self.hook.fire("on_exit")
        # display all hidden windows
        for window in self.windows.values():
            window.show()
        self.xsync()
        self.log.stop.debug("stopping event loop")
        self._eventloop.stop()

    def replace(self, execv_args):
        self.log.notice("replacing current process with %s" % (execv_args,))
        self.stop()
        import os
        os.execv(*execv_args)

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
                xcb_event = self._conn.poll_for_event()
                if not xcb_event:
                    break
                evname = xcb_event.__class__.__name__
                if evname.endswith("Event"):
                    evname = evname[:-5]
                if evname in self.ignoreEvents:
                    self.log._xpoll.debug("ignoring %s" % xcb_event)
                    continue
                self.log._xpoll.debug("got %s" % evname)
                self.hook.fire(evname, xcb_event)
            # OK, kids, today I'll teach you how to write reliable enterprise
            # software! You just catch all the exceptions in the top-level loop
            # and ignore them. No, I'm kidding, these exceptions are no use
            # for us because we don't care if a window cannot be drawn or something.
            # We actually only need to handle just a few events and ignore the rest.
            # Exceptions happen because of the async nature of X.
            except (WindowError, AccessError, DrawableError):
                self.log.debug("(minor exception)")
            except Exception as e:
                error_code = self._conn.has_error()
                if error_code:
                    error_string = XCB_CONN_ERRORS[error_code]
                    self.log.critical("Shutting down due to X connection error %s (%s)" %
                                      (error_string, error_code))
                    self.stop()
                    break
                traceback.print_exc()
        self.flush()  # xcb often doesn't flush implicitly

    def hotkey(self, keys, cmd):
        @self.hook(self.grab_key(*keys))
        def cb(event):
            run_(cmd)


# class SupressEvent(Exception):
#   """ Raise this one in callback if further callbacks shouldn't be called. """


class Hook:
    """ Simple callback dispatcher. """

    def __init__(self):
        self.cb_map = defaultdict(list)
        self.log = Log("hook")
        self.suppressed = set()

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

    def suppress(self, event):
        hook = self

        class Context:

            def __enter__(self):
                hook.log.debug("suppressing %s" % event)
                hook.suppressed.add(event)

            def __exit__(self, *args):
                hook.log.debug("un-suppressing %s" % event)
                if event in hook.suppressed:
                    hook.suppressed.remove(event)
                else:
                    hook.log.notice("uhm, event is not suppressed: %s" % event)
        return Context()

    def fire(self, event, *args, **kwargs):
        if event not in self.cb_map:
            self.log.notice("no handler for %s" % event)
            return

        if event in self.suppressed:
            self.log.debug(
                "event suppressed: {} {} {}".format(event, args, kwargs))
            return

        handlers = self.cb_map[event]
        for handler in handlers:
            try:
                handler(event, *args, **kwargs)
            # except SupressEvent:
                # break
            except Exception as err:
                msg = "error on event {ev}: {err} ({typ}) (in {hdl})" \
                    .format(err=err, typ=type(err), ev=event, hdl=handler)
                self.log.error(msg)

        #if DEBUG:
        #    time.sleep(0.03)
