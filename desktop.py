from useful.log import Log


class Desktop:
    """ Support for virtual desktops. """

    def __init__(self, id, windows=None, name=None):
        self.id = id
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
        self.hidden = True  # TODO: rename to active

    def show(self):
        self.hidden = False
        for window in self.were_mapped:
            self.log.debug("showing window %s" % window)
            window.show()
        else:
            self.log.debug("no windows on this desktop to show")
        self.were_mapped.clear()

        if self.cur_focus:
            self.cur_focus.focus()

        # TODO: self.wm.root.set_prop('_NET_CURRENT_DESKTOP', self.id)

    def hide(self):
        self.hidden = True
        for window in self.windows:
            if window.mapped:
                self.log.debug("hiding window %s" % window)
                window.hide()
                self.were_mapped.append(window)
        self.log.debug("followind windows were hidden: %s" % self.were_mapped)

    def add(self, window):
        self.windows.append(window)
        if self.hidden:
            self.were_mapped.append(window)
        else:
            window.show()
            window.focus()
            self.cur_focus = window

    def remove(self, window):
        if window not in self.windows:
            self.log.error("NO WINDOW %s" % window)
            self.log.error("current windows: %s", self.windows)
            return

        self.windows.remove(window)
        if not self.hidden:
            window.hide()
        if window == self.cur_focus:
            self.cur_focus = None

    def focus_on(self, window, warp=True):
        assert window in self.windows, "window %s is not on current desktop" % window
        assert not self.hidden, "cannot focus while desktop is hidden"
        # if self.cur_focus:
        #     self.cur_focus.lower()
        # Achtung! Order here is very important or focus will now work
        # correctly
        self.log("focusing on %s" % window)
        # window.show()
        window.rise()
        window.focus()
        if warp:
            window.warp()
        self.cur_focus = window

    def __repr__(self):
        return "Desktop(%s)" % self.name
