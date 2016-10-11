from defs import PROPERTYMAP
from xcffib.xproto import CW, EventMask

from xcffib import xproto

from useful.log import Log


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


class Window:
    sticky = False
    can_focus = True
    above_all = False
    mapped = False

    def __init__(self, wm, wid, mapped=True, name=None):
        from wm import WM  # TODO: dirtyhack to avoid circular imports
        assert isinstance(wm, WM), "wm must be an instance of WM"
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
        self._conn.core.MapWindow(self.wid)
        self.wm.xsync()
        self.mapped = True

    def hide(self):
        self._conn.core.UnmapWindow(self.wid)
        self.mapped = False

    def rise(self):
        """ Put window on top of others. TODO: what about focus? """
        return self.stackmode(xproto.StackMode.Above)

    def lower(self):
        """ Put window on top of others. TODO: what about focus? """
        return self.stackmode(xproto.StackMode.Below)

    def raiseorlower(self):
        """ Put window on top of others. TODO: what about focus? """
        return self.stackmode(xproto.StackMode.Opposite)

    def stackmode(self, mode):
        return self._conn.core.ConfigureWindow(self.wid,
                                               xproto.ConfigWindow.StackMode,
                                               [mode])

    def focus(self):
        """ Let window receive mouse and keyboard events.
            X expects window to be mapped.
        """
        if not self.mapped:
            self.show()
        #self.wm.cur_desktop.cur_focus = self
        # TODO: self.wm.root.set_property("_NET_ACTIVE_WINDOW", self.wid)
        self._conn.core.SetInputFocus(xproto.InputFocus.PointerRoot,
                                      self.wid, xproto.Time.CurrentTime)
        self.wm.xsync()  # it is here mandatory :(
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
                              1, height=screen.height - 1 - 18)  # TODO: 18 dirtyhack to place bottom panel
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

        # filter negative values
        values = [max(value, 0) for value in values]
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
        """ Returns https://tronche.com/gui/x/xlib/window-information/XGetWindowAttributes.html . """
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

    def list_props(self):
        reply = self.wm._conn.core.ListProperties(self.wid).reply()
        atoms = reply.atoms.list
        return [self.wm.atoms.get_name(atom) for atom in atoms]

    def __lt__(self, other):  # used for sorting and comparison
        return True

    def __repr__(self):
        name = self.name
        if len(name) > 20:
            name = name[:17] + '...'
        return "Window(%s, \"%s\")" % (self.wid, name)
