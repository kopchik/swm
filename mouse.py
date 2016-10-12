from useful.log import Log

class Mouse:
    def  __init__(self, conn, root):
        self.conn = conn
        self.root = root
        self.log = Log("mouse")

    def move(self, x=None, y=None, dx=0, dy=0, window=None):
        if window is None:
            window = self.root
        xcb_reply = self.conn.core.QueryPointer(window.wid).reply()
        new_x = xcb_reply.win_x
        new_y = xcb_reply.win_y
        if x:
            new_x = x
        if y:
            new_y = y
        if dx:
            new_x += dx
        if dy:
            new_y += dy
        self.log.debug("relocating to ({}, {})".format(new_x, new_y))
        self.conn.core.WarpPointerChecked(
            0, window.wid,  # src_window, dst_window
            0, 0,           # src_x, src_y
            0, 0,           # src_width, src_height
            new_x, new_y    # dest_x, dest_y
        )
