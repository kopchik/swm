#!/usr/bin/env python3

from useful.log import Log
from swm import WM, Desktop, prints, run_

import os.path

if 1:
    up, down, left, right = 'Up', 'Down', 'Left', 'Right'
    win = fail = 'mod4'
    ctrl = control = 'control'
    shift = 'shift'
    alt = 'mod1'
    tab = 'Tab'
    MouseL = 1
    MouseC = 2
    MouseR = 3
    log = Log("USER HOOKS")

    mod = win

    num_desktops = 9
    desktops = [Desktop(name=str(i)) for i in range(num_desktops)]
    wm = WM(desktops=desktops)

    orig_coordinates = None
    orig_geometry = None

    for i in range(1, num_desktops + 1):
        @wm.hook(wm.grab_key([mod], str(i)))
        def switch_to1(event, i=i):
            wm.switch_to_desk(i - 1)

    @wm.hook(wm.grab_mouse([alt], MouseL))
    def on_mouse(evhandler, evtype, xcb_ev):
        global orig_coordinates
        global orig_geometry
        cur_pos = xcb_ev.root_x, xcb_ev.root_y
        window = wm.cur_desktop.cur_focus
        if evtype == "ButtonPress":
            orig_coordinates = cur_pos
            orig_geometry = window.geometry
            prints(
                "orig_coord: {orig_coordinates}, orig_geom: {orig_geometry}")
        elif evtype == "ButtonRelease":
            orig_coordinates = None
            orig_geometry = None
        elif evtype == "MotionNotify":
            dx = cur_pos[0] - orig_coordinates[0]
            dy = cur_pos[1] - orig_coordinates[1]
            x = orig_geometry[0] + dx
            y = orig_geometry[1] + dy
            if x < 0 or y < 0:
                x = max(0, x)
                y = max(0, y)
            # if x < 0 or y < 0:
                # orig_coordinates = cur_pos
                # orig_geometry = window.geometry
            window.move(x=x, y=y)

    # There are a lot of windows created and most of them not supposed
    # to be managed by WM. Thus, this hook is pretty much useless
    # @wm.hook("window_create")
    # def window_create(event, window):
    #   print("new window", window)

    @wm.hook("window_enter")
    def switch_focus(event, window):
        # do not switch focus when moving over root window
        if window == wm.root:
            return
        window.show()
        window.focus()
        window.rise()
        wm.cur_desktop.cur_focus = window
        # window.warp()

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
    step = 100

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
    @wm.hook(wm.grab_key([mod], right))
    def move_right(event):
        # wm.cur_desktop.cur_focus.move(dx=step).warp()
        smart_snap('x', step)

    @wm.hook(wm.grab_key([mod], left))
    def move_left(event):
        # wm.cur_desktop.cur_focus.move(dx=-step).warp()
        smart_snap('x', -step)

    @wm.hook(wm.grab_key([mod], up))
    def move_up(event):
        # step = 5
        wm.cur_desktop.cur_focus.move(dy=-step).warp()

    @wm.hook(wm.grab_key([mod], down))
    def move_down(event):
        # step = 5
        wm.cur_desktop.cur_focus.move(dy=step).warp()

    # FOCUS
    @wm.hook(wm.grab_key([alt], 'Tab'))
    def next_window(event):
        desktop = wm.cur_desktop
        cur = desktop.cur_focus
        cur_idx = desktop.windows.index(cur)
        nxt = desktop.windows[cur_idx - 1]
        if nxt == wm.root:  # TODO: dirty hack because switch_focus does not switch to root
            nxt = desktop.windows[cur_idx - 2]
        switch_focus("some_fake_ev", nxt)

    @wm.hook(wm.grab_key([mod], 'n'))
    def prev_window(event):
        desktop = wm.cur_desktop
        windows = desktop.windows
        cur = desktop.cur_focus
        cur_idx = windows.index(cur)
        tot = len(windows)
        nxt = desktop.windows[(cur_idx + 1) % tot]
        switch_focus("some_fake_ev", nxt)

    # DESKTOP
    @wm.hook(wm.grab_key([mod], 'h'))
    def hide_window(event):
        desktop = wm.cur_desktop
        windows = desktop.windows
        cur = desktop.cur_focus
        cur_idx = windows.index(cur)
        cur.hide()
        # TODO: switch to next window?

    # SPAWN
    wm.hotkey(([mod], 'x'), 'urxvtcd -rv -fade 50 -fn "xft:Terminus:size=16" -fb "xft:Terminus:bold:size=16" -sl 10000 -si -tn xterm')
    wm.hotkey(([mod], 'd'), "dmenu_run")
    wm.hotkey(([alt], down), "asus-kbd-backlight down")
    wm.hotkey(([alt], up), "asus-kbd-backlight up")
    wm.hotkey(([ctrl, win], up), "sudo value.py --set /sys/class/backlight/intel_backlight/brightness --min=10 --max /sys/class/backlight/intel_backlight/max_brightness -- +10%")
    wm.hotkey(([ctrl, win], down), "sudo value.py --set /sys/class/backlight/intel_backlight/brightness --min=10 --max /sys/class/backlight/intel_backlight/max_brightness -- -10%")

    # OTHER
    @wm.hook(wm.grab_key([mod], 'w'))
    def kill_window(event):
        wm.cur_desktop.cur_focus.kill()

    @wm.hook(wm.grab_key([mod], 's'))
    def status(event):
        from useful.mstring import prints
        focus = wm.cur_desktop.cur_focus
        prints("root: {root}, focus: {focus}")
        for wid in sorted(wm.windows):
            window = wm.windows[wid]
            prints("{wid:<10} {window.name:<20} {window.mapped:<10}")

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

    # run("urxvt")
    run_("xsetroot -solid Teal")

    # DO NOT PUT ANY CONFIGURATION BELOW THIS LINE
    # because wm.loop is blocking.
    wm.loop()
