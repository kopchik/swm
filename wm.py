from defs import XCB_CONN_ERRORS, SUPPORTED_ATOMS
from window import Window
from desktop import Desktop
from keyboard import Keyboard
from utils import run_, get_modmask
from hook import Hook

from xcffib.xproto import WindowError, AccessError, DrawableError
from xcffib.xproto import CW, WindowClass, EventMask, ConfigWindow
from xcffib import xproto
import xcffib.randr
import xcffib.xproto
import xcffib

from useful.log import Log
import traceback
import asyncio
import signal
import sys
import os


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
            c = self.conn.core.GetAtomName(atom)
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


class WM:
    """
        Provides basic building blocks to make a window manager.
        It hides many dirty details about XCB. It was intended
        to provide minimum functionality, the rest supposed to
        be implemented by user in configuration file.
    """
    root = None   # type: Window
    atoms = None  # type: AtomCache

    def __init__(self, display=None, desktops=None, loop=None):
        self.log = Log("WM")
        # INIT SOME BASIC STUFF
        self.hook = Hook()
        self.windows = {}  # mapping between window id and Window
        self.win2desk = {}

        if not display:
            display = os.environ.get("DISPLAY")

        try:
            self._conn = xcffib.connect(display=display)
        except xcffib.ConnectionException:
            sys.exit("cannot connect to %s" % display)

        self.atoms = AtomCache(self._conn)
        self.desktops = desktops or [Desktop()]
        self.cur_desktop = self.desktops[0]
        self.cur_desktop.show()

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
                #                EventMask.SubstructureNotify |
                #                EventMask.SubstructureRedirect |
                EventMask.EnterWindow |
                EventMask.LeaveWindow
                #                EventMask.PropertyChange
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
        self.root.set_prop('_NET_NUMBER_OF_DESKTOPS', len(self.desktops))
        self.root.set_prop('_NET_CURRENT_DESKTOP', 0)

        # TODO: set cursor

        # EVENTS THAT HAVE LITTLE USE FOR US...
        self.ignoreEvents = {
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
        }
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
        window_to_focus = sorted(self.windows.values())[-1].focus()
        self.cur_desktop.focus_on(window_to_focus, warp=True)

        # TODO: self.update_net_desktops()

        # SETUP EVENT LOOP
        if not loop:
            loop = asyncio.new_event_loop()
        self._eventloop = loop
        self._eventloop.add_signal_handler(signal.SIGINT, self.stop)
        self._eventloop.add_signal_handler(signal.SIGTERM, self.stop)
        self._eventloop.add_signal_handler(signal.SIGCHLD, self.on_sigchld)
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
        self.hook.register("PropertyNotify", self.on_property_notify)
        self.hook.register("ClientMessage", self.on_client_message)
        self.hook.register("DestroyNotify", self.on_window_destroy)
        self.hook.register("EnterNotify", self.on_window_enter)
        self.hook.register("ConfigureRequest", self.on_configure_window)
        self.hook.register("MotionNotify", self.on_mouse_event)
        self.hook.register("ButtonPress", self.on_mouse_event)
        self.hook.register("ButtonRelease", self.on_mouse_event)

    def on_property_notify(self, evname, xcb_event):
        # TODO: messy ugly code
        wid = xcb_event.window
        atom = self.atoms.get_name(xcb_event.atom)
        #window = self.windows.get(wid, Window(wm=self, wid=wid, mapped=True))
        self.log.error("PropertyNotify: %s" % atom)
        run_("xprop -id %s %s" % (wid, atom))

    def on_client_message(self, evname, xcb_event):
        self.log.error(dir(xcb_event))
        self.log.error("client message: %s" %
                       self.atoms.get_name(xcb_event.response_type))
        # 'bufsize', 'data', 'format', 'pack', 'response_type', 'sequence', 'synthetic', 'type', 'window']

    def on_sigchld(self):
        """ Rip orphans. """
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if (pid, status) == (0, 0):
                    # no child to rip
                    break
                self.log.notice("ripped child PID=%s" % pid)
            except ChildProcessError:
                break

    def on_map_request(self, evname, xcb_event):
        """ Map request is a request to draw the window on screen. """
        wid = xcb_event.window
        if wid not in self.windows:
            window = self.on_new_window(wid)
        else:
            window = self.windows[wid]
            self.log.on_map_request.debug("map request for %s" % window)
        window.show()
        if window.above_all:
            window.rise()
        if window.can_focus:
            window.focus()

    def on_new_window(self, wid):
        """ Registers new window. """
        window = Window(wm=self, wid=wid, mapped=True)
        # call configuration hood first
        # to setup attributes like 'sticky'
        self.hook.fire("new_window", window)
        self.log.CreateNotify.debug(
            "new window is ready for mapping: %s" % window)
        self.windows[wid] = window
        self.win2desk[window] = self.cur_desktop
        if window.sticky:
            for desktop in self.desktops:
                desktop.add(window)
        else:
            self.cur_desktop.windows.append(window)
        return window

    def on_map_notify(self, evname, xcb_event):
        wid = xcb_event.window
        if wid not in self.windows:
            # window is managed by the application, not by us
            # TODO: debug:
            window = Window(wm=self, wid=wid)
            self.log.on_map_notify.notice(window)
            self.log.on_map_notify.notice(window.list_props())
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
        assert isinstance(window, Window), "it's not a window: %s (%s)" % (
            window, type(window))

        for desktop in self.desktops:
            try:
                desktop.windows.remove(window)
                self.log.debug("%s removed from %s" % (self, desktop))
            except ValueError:
                pass
        del self.windows[wid]
        if window in self.win2desk:
            del self.win2desk[window]

    def on_window_enter(self, evname, xcb_event):
        wid = xcb_event.event
        if wid not in self.windows:
            self.log.on_window_enter.error("no window with wid=%s" % wid)
            self.hook.fire("unknown_window", wid)
            return
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
        self.log.grab_key.debug("intercept keys: %s %s" % (modifiers, key))

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

    def hotkey(self, keys, cmd):
        """ Setup hook to launch a command on specific hotkeys. """
        @self.hook(self.grab_key(*keys))
        def cb(event):
            run_(cmd)

    def focus_on(self, window, warp=False):
        """ Focuses on given window. """
        self.cur_desktop.focus_on(window, warp)

    def switch_to(self, desktop: Desktop):
        """ Switches to another desktop. """
        if isinstance(desktop, int):
            desktop = self.desktops[desktop]
        if self.cur_desktop == desktop:
            self.log.notice("attempt to switch to the same desktop")
            return
        self.log.debug("switching from {} to {}".format(
            self.cur_desktop, desktop))
        self.cur_desktop.hide()
        self.cur_desktop = desktop
        self.cur_desktop.show()
        # TODO: move this code to Desktop.show()
        self.root.set_prop('_NET_CURRENT_DESKTOP', desktop.id)

    def relocate_to(self, window: Window, to_desktop: Desktop):
        """ Relocates window to a specific desktop. """
        if window.sticky:
            self.log.debug(
                "%s is meant to be on all desktops, cannot relocate to specific one" % window)
            return

        from_desktop = self.cur_desktop

        if from_desktop == to_desktop:
            self.log.debug(
                "no need to relocate %s because remains on the same desktop" % window)
            return

        from_desktop.remove(window)
        to_desktop.add(window)

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
        """ Gets all windows in the system. """
        self.log.debug("performing scan of all mapped windows")
        q = self._conn.core.QueryTree(self.root.wid).reply()
        for wid in q.children:
            attrs = self._conn.core.GetWindowAttributes(wid).reply()
            # print(attrs, type(attrs))
            if attrs.map_state == xproto.MapState.Unmapped:
                self.log.scan.debug("window %s is not mapped, skipping" % wid)  # TODO
                continue
            if wid not in self.windows:
                self.on_new_window(wid)
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

    def stop(self, xserver_dead=False):
        """ Stop WM to quit. """
        self.hook.fire("on_exit")
        # display all hidden windows
        try:
            if not xserver_dead:
                for window in self.windows.values():
                    window.show()
                self.xsync()
        except Exception as err:
            self.log.stop.error("error on stop: %s" % err)
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

        # OK, kids, today I'll teach you how to write reliable enterprise
        # software! You just catch all the exceptions in the top-level loop
        # and ignore them. No, I'm kidding, these exceptions are no use
        # for us because we don't care if a window cannot be drawn or something.
        # We actually only need to handle just a few events and ignore the rest.
        # Exceptions happen because of the async nature of X.

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
                    self.log._xpoll.info("ignoring %s" % xcb_event)
                    continue
                self.log._xpoll.critical("got %s %s" % (evname, xcb_event))
                self.hook.fire(evname, xcb_event)
            except (WindowError, AccessError, DrawableError):
                self.log.debug("(minor exception)")
            except Exception as e:
                self.log._xpoll.error(traceback.format_exc())
                error_code = self._conn.has_error()
                if error_code:
                    error_string = XCB_CONN_ERRORS[error_code]
                    self.log.critical("Shutting down due to X connection error %s (%s)" %
                                      (error_string, error_code))
                    self.stop(xserver_dead=True)
                    break
        self.flush()  # xcb often doesn't flush implicitly
