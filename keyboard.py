from useful.log import Log

from xkeysyms import keysyms


class Keyboard:
    """ Just keyboard service functions. """

    def __init__(self, xcb_setup, conn):
        self._conn = conn
        self.code_to_syms = {}
        self.first_sym_to_code = {}
        self.log = Log("keyboard")

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
        # self.log(sorted(self.first_sym_to_code))
        return self.first_sym_to_code[sym]
