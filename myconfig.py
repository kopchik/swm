#!/usr/bin/env python3
# TODO: _NET_WM_STRUT_PARTIAL
# t = namedtuple("STRUT", "left right top bottom left_start_y left_end_y right_start_y right_end_y top_start_x top_end_x bottom_start_x bottom_end_x".split())
# t(0, 0, 0, 18, 0, 0, 0, 0, 0, 0, 0, 1919)
# WM_CLASS(STRING) = "dzen2", "dzen"

from useful.log import Log

from swm import WM, Desktop, run_
from myosd import OSD
from textgui import gui
import os.path
import sys

from useful.prettybt import prettybt
sys.excepthook = prettybt

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

num_desktops = 4
desktops = [Desktop(name=str(i)) for i in range(num_desktops)]
wm = WM(desktops=desktops)
loop = wm._eventloop
logwidget = gui(loop=wm._eventloop)
Log.file = logwidget


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


@wm.hook(wm.grab_mouse([mod], MouseR))
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
        wm.switch_to(i - 1)

    @wm.hook(wm.grab_key([shift, mod], str(i)))
    def teleport_window(event, i=i):
        window = wm.cur_desktop.cur_focus
        if not window:
            log.teleport_window.error("window is NONE!!!")
            return
        wm.relocate_to(window, desktops[i])


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


# There are a lot of windows created and most of them not supposed
# to be managed by WM. Thus, this hook is pretty much useless
@wm.hook("new_window")
def on_window_create1(event, window):
    logentry = log.on_window_create.notice

    logentry("#####################")
    logentry("new window %s" % window)
    logentry("attributes: %s" % window.list_props())
    logentry("_____________________")

prev_handler = None


@wm.hook("window_enter")
def on_window_enter(event, window):
    global prev_handler

    if prev_handler:
        prev_handler.cancel()
    log._switch.debug("delaying activation of %s" % window)

    def _switch():
        log._switch.debug("okay, it's time to switch to %s" % window)
        switch_focus(event, window)
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


@wm.hook(wm.grab_key([mod, shift], right))
def expand_width(event):
    smart_snap('width', step)


@wm.hook(wm.grab_key([mod, shift], left))
def shrink_width(event):
    smart_snap('width', -step)


@wm.hook(wm.grab_key([mod, shift], up))
def expand_height(event):
    # wm.cur_desktop.cur_focus.resize(dy=-step).warp()
    smart_snap('height', -step)


@wm.hook(wm.grab_key([mod, shift], down))
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


@wm.hook(wm.grab_key([alt], tab))
def next_window(event):
    desktop = wm.cur_desktop
    cur = desktop.cur_focus
    cur_idx = desktop.windows.index(cur)
    nxt = desktop.windows[cur_idx - 1]
    if nxt == wm.root:  # TODO: dirty hack because switch_focus does not switch to root
        nxt = desktop.windows[cur_idx - 2]
    switch_focus("some_fake_ev", nxt, warp=True)


@wm.hook(wm.grab_key([mod], 'n'))
def prev_window(event):
    desktop = wm.cur_desktop
    windows = desktop.windows
    cur = desktop.cur_focus
    cur_idx = windows.index(cur)
    tot = len(windows)
    nxt = desktop.windows[(cur_idx + 1) % tot]
    switch_focus("some_fake_ev", nxt, warp=True)


# SPAWN
# terminals, etc
wm.hotkey(([mod], 'x'), 'urxvtcd -rv -fade 50 -fn "xft:Terminus:size=16" -fb "xft:Terminus:bold:size=16" -sl 10000 -si -tn xterm')
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


@wm.hook(wm.grab_key([mod], 'w'))
def kill_window(event):
    wm.cur_desktop.cur_focus.kill()


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

run_("xsetroot -solid Teal")

# DO NOT PUT ANY CONFIGURATION BELOW THIS LINE
# because wm.loop is blocking.
wm.loop()
