#!/usr/bin/env python3
# TODO: _NET_WM_STRUT_PARTIAL
# t = namedtuple("STRUT", "left right top bottom left_start_y left_end_y right_start_y right_end_y top_start_x top_end_x bottom_start_x bottom_end_x".split())
# t(0, 0, 0, 18, 0, 0, 0, 0, 0, 0, 0, 1919)
# WM_CLASS(STRING) = "dzen2", "dzen"

from useful.log import Log

from utils import run_
from wm import WM
from desktop import Desktop
from window import Window
from myosd import OSD
from textgui import gui
import asyncio
import os.path
import sys


from useful.prettybt import prettybt
sys.excepthook = prettybt

# USEFUL ALIASES
up, down, left, right = 'Up', 'Down', 'Left', 'Right'
win = fail = 'mod4'
ctrl = control = 'control'
shift = 'shift'
caps = 'Caps_Lock'
alt = 'mod1'
tab = 'Tab'
MouseL = 1
MouseC = 2
MouseR = 3
log = Log("USER HOOKS")
osd = OSD()

mod = win

# PRE-INIT
# switch to english just in case
run_("setxkbmap -layout en")

# create event loop and setup text GUI
loop = asyncio.new_event_loop()
# logwidget = gui(loop=loop)
# Log.file = logwidget


# INIT
num_desktops = 4
desktops = [Desktop(id=i, name=str(i + 1)) for i in range(num_desktops)]
wm = WM(desktops=desktops, loop=loop)


# MOUSE STUFF
orig_pos = None
orig_geometry = None

# move


@wm.hook(wm.grab_mouse([mod], MouseL))
def on_mouse_move(evhandler, evtype, xcb_ev):
    global orig_pos
    global orig_geometry
    cur_pos = xcb_ev.root_x, xcb_ev.root_y
    window = wm.cur_desktop.cur_focus
    if evtype == "ButtonPress":
        orig_pos = cur_pos
        orig_geometry = window.geometry
        log.on_mouse_move.debug(
            "orig_pos: {}, orig_geom: {}".format(orig_pos, orig_geometry))
    elif evtype == "ButtonRelease":
        orig_pos = None
        orig_geometry = None
    elif evtype == "MotionNotify":
        dx = cur_pos[0] - orig_pos[0]
        dy = cur_pos[1] - orig_pos[1]
        x = max(0, orig_geometry[0] + dx)
        y = max(0, orig_geometry[1] + dy)
        window.move(x=x, y=y)

# resize


@wm.hook(wm.grab_mouse([mod, alt], MouseL))
def on_mouse_resize(evhandler, evtype, xcb_ev):
    global orig_pos
    global orig_geometry
    cur_pos = xcb_ev.root_x, xcb_ev.root_y
    window = wm.cur_desktop.cur_focus
    if evtype == "ButtonPress":
        orig_pos = cur_pos
        orig_geometry = window.geometry
        log.on_mouse_resize.debug(
            "orig_pos: {}, orig_geom: {}".format(orig_pos, orig_geometry))
    elif evtype == "ButtonRelease":
        orig_pos = None
        orig_geometry = None
    elif evtype == "MotionNotify":
        dx = cur_pos[0] - orig_pos[0]
        dy = cur_pos[1] - orig_pos[1]
        # x = max(0, orig_geometry[0] + dx)
        # y = max(0, orig_geometry[1] + dy)
        window.resize(dx=dx, dy=dy)


# DESKTOP SWITCHING
cur_desk_idx = 0

for i in range(1, num_desktops + 1):
    @wm.hook(wm.grab_key([mod], str(i)))
    def switch_to(event, i=i):
        cur_desk_idx = i - 1
        wm.switch_to(cur_desk_idx)
        osd.write(cur_desk_idx)

    @wm.hook(wm.grab_key([shift, mod], str(i)))
    def teleport_window(event, i=i):
        window = wm.cur_desktop.cur_focus
        if not window:
            log.teleport_window.error("window is NONE!!!")
            return
        wm.relocate_to(window, desktops[i - 1])


@wm.hook(wm.grab_key([mod], right))
def next_desktop(event):
    global cur_desk_idx
    cur_desk_idx += 1
    cur_desk_idx %= num_desktops
    wm.switch_to(cur_desk_idx)
    osd.write(cur_desk_idx)


@wm.hook(wm.grab_key([mod], left))
def prev_desktop(event):
    global cur_desk_idx
    cur_desk_idx -= 1
    cur_desk_idx %= num_desktops
    wm.switch_to(cur_desk_idx)
    osd.write(cur_desk_idx)


# CUSTOMIZE WINDOWS
@wm.hook("new_window")
def on_window_create(event, window: Window):
    if window.name in ["dzen title", "XOSD", "panel"]:
        window.sticky = True
        window.can_focus = False
        window.above_all = True

prev_handler = None


@wm.hook("new_window")
def print_new_window_props(event, window: Window):
    logentry = log.on_window_create.notice
    run_("xprop -id %s" % window.wid)
    # props = window.list_props()
    # logentry("#####################")
    # logentry("new window %s" % window)
    # # logentry("attributes: %s" % )
    # unknown_props = []
    # for prop in props:
    #     try:
    #         value = window.get_prop(prop, unpack=str)
    #     except ValueError:
    #         unknown_props.append(prop)
    #     logentry("%s: %s" % (prop,value))
    # logentry("unknown props %s" % unknown_props)
    # logentry("_____________________")


@wm.hook("unknown_window")
def unknown_window(event, wid):
    run_("xprop -id %s" % wid)


@wm.hook("window_enter")
def on_window_enter(event, window):
    global prev_handler

    if prev_handler:
        prev_handler.cancel()

    if window == wm.root:
        return

    log._switch.debug("delaying activation of %s" % window)

    def _switch(window=window):
        log._switch.debug("okay, it's time to switch to %s" % window)
        wm.focus_on(window)
    prev_handler = loop.call_later(0.15, _switch)


# TODO: get rid of this function in favor of wm.focus_on()
def switch_focus(event, window, warp=False):
    # do not switch focus when moving over root window
    if window == wm.root:
        return
    wm.focus_on(window)
    osd.write(window)


def get_edges(windows, vert=False):
    vstart, vstop, hstart, hstop = [], [], [], []
    for window in windows:
        if not window.mapped:
            continue
        x, y, w, h = window.geometry
        vstart.append(x)
        vstop.append(x + w)
        hstart.append(y)
        hstop.append(y + h)
    return vstart, vstop, hstart, hstop


def snap_to(cur, step, edges):
    edges = sorted(edges)
    for edge in edges:
        if min(cur, cur + step) < edge < max(cur, cur + step):
            return edge
    return cur + step

# TODO: rename cur_focus to focus, cur_desktop to desktop


def smart_snap(attr, step):
    windows = wm.cur_desktop.windows
    window = wm.cur_desktop.cur_focus
    x, y, w, h = window.geometry
    vstart, vstop, hstart, hstop = get_edges(
        w for w in windows if w != window and w.mapped)
    if attr == 'width':
        cur = x + w
        snap = snap_to(cur, step, vstart + vstop)
        window.set_geometry(**{attr: (snap - x)})
    elif attr == 'height':
        cur = y + h
        snap = snap_to(cur, step, hstart + hstop)
        window.set_geometry(**{attr: (snap - y)})
    elif attr == 'x':
        cur = x
        snap = snap_to(cur, step, vstart + vstop)
        window.set_geometry(x=snap)
    window.warp()


# RESIZE
step = 200


@wm.hook(wm.grab_key([mod, alt], right))
def expand_width(event):
    smart_snap('width', step)


@wm.hook(wm.grab_key([mod, alt], left))
def shrink_width(event):
    smart_snap('width', -step)


@wm.hook(wm.grab_key([mod, alt], up))
def expand_height(event):
    # wm.cur_desktop.cur_focus.resize(dy=-step).warp()
    smart_snap('height', -step)


@wm.hook(wm.grab_key([mod, alt], down))
def shrink_height(event):
    # wm.cur_desktop.cur_focus.resize(dy=step).warp()
    smart_snap('height', step)


@wm.hook(wm.grab_key([mod], 'm'))
def maximize(event):
    wm.cur_desktop.cur_focus.toggle_maximize()


# MOVE

@wm.hook(wm.grab_key([alt], right))
def move_right(event):
    # wm.cur_desktop.cur_focus.move(dx=step).warp()
    smart_snap('x', step)


@wm.hook(wm.grab_key([alt], left))
def move_left(event):
    # wm.cur_desktop.cur_focus.move(dx=-step).warp()
    smart_snap('x', -step)


@wm.hook(wm.grab_key([alt], up))
def move_up(event):
    # step = 5
    wm.cur_desktop.cur_focus.move(dy=-step).warp()


@wm.hook(wm.grab_key([alt], down))
def move_down(event):
    # step = 5
    wm.cur_desktop.cur_focus.move(dy=step).warp()


# FOCUS
def cycle_from(l, pos):
    from itertools import chain
    for e in chain(l[pos:], l[:pos]):
        yield e


@wm.hook(wm.grab_key([alt], tab))
def next_window(event):
    desktop = wm.cur_desktop
    windows = desktop.windows
    cur = desktop.cur_focus
    idx = windows.index(cur)
    tot = len(windows)
    nxt = windows[(idx - 1) % tot]
    wm.focus_on(nxt, warp=True)


@wm.hook(wm.grab_key([mod], 'n'))
def prev_window(event):
    desktop = wm.cur_desktop
    windows = desktop.windows
    cur = desktop.cur_focus
    idx = windows.index(cur)
    tot = len(windows)
    nxt = windows[(idx + 1) % tot]
    wm.focus_on(nxt, warp=True)


# SPAWN
# terminals, etc
wm.hotkey(([mod], 'x'), 'urxvtcd -rv -fade 50 -fn "xft:Terminus:size=16" -fb "xft:Terminus:bold:size=16" -sl 10000 -si -tn xterm')
wm.hotkey(([mod], 'y'), 'xterm')
wm.hotkey(([mod], 'd'), "dmenu_run")
wm.hotkey(([mod], 'l'), "mylock")
# kbd layout
wm.hotkey(([], caps), "setxkbmap -layout us")
wm.hotkey(([shift], caps), "setxkbmap -layout ru")
# volume
wm.hotkey(([mod], 'period'), "sound_volume up")
wm.hotkey(([mod], 'comma'), "sound_volume down")
# brightness
wm.hotkey(([shift, alt], down), "asus-kbd-backlight down")
wm.hotkey(([shift, alt], up), "asus-kbd-backlight up")
wm.hotkey(([ctrl, win], up), "value.py --set /sys/class/backlight/intel_backlight/brightness  \
                                       --min=10  \
                                       --max /sys/class/backlight/intel_backlight/max_brightness  \
                                       -- +10%")
wm.hotkey(([ctrl, win], down), "value.py --set /sys/class/backlight/intel_backlight/brightness  \
                                         --min=10  \
                                         --max /sys/class/backlight/intel_backlight/max_brightness  \
                                         -- -10%")

# OTHER


# TODO: rewrite it to use wm.hide
@wm.hook(wm.grab_key([mod], 'h'))
def hide_window(event):
    desktop = wm.cur_desktop
    # windows = desktop.windows
    cur = desktop.cur_focus
    # cur_idx = windows.index(cur)
    cur.hide()
    # TODO: switch to next window?


@wm.hook(wm.grab_key([mod, shift], 'k'))
def kill_window(event):
    wm.cur_desktop.cur_focus.kill()


@wm.hook(wm.grab_key([mod], 'o'))
def osd_test(event):
    osd.write("OSD test output")


@wm.hook(wm.grab_key([mod], 'e'))
def log_print_separator(event):
    log.notice('========')
    log.notice("        ")


@wm.hook(wm.grab_key([mod], 's'))
def status(event):
    root = wm.root
    focus = wm.cur_desktop.cur_focus
    log.status.debug("root: {root}, focus: {focus}".format(
        root=root, focus=focus))
    for wid in sorted(wm.windows):
        window = wm.windows[wid]
        log.status.debug("{wid:<10} {window.name:<20} {window.mapped:<10}".format(
            wid=wid, window=window))

# restore windows, otherwise they will stay invisible


@wm.hook(wm.grab_key([mod, shift], 'q'))
def quit(event):
    wm.stop()


@wm.hook(wm.grab_key([mod, shift], 'r'))
def restart(event):
    log.notice("restarting WM")
    path = os.path.abspath(__file__)
    wm.replace(execv_args=(path, [path]))


@wm.hook("on_exit")
def on_exit(*args, **kwargs):
    # restore windows, otherwise they will stay invisible
    for window in wm.windows.values():
        window.show()

# set background
run_("xsetroot -solid Teal")
# replace default X-shaped cursor with something more suitable
run_("xsetroot -cursor_name left_ptr")


# DO NOT PUT ANY CONFIGURATION BELOW THIS LINE
# because wm.loop is blocking.
wm.loop()
