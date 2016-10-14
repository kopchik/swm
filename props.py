from defs import CARDINAL, ATOM
from atom import Atom

from xcffib import xproto

class Props:

    def __init__(self, window, conn, atoms):
        self.window = window
        self.atoms = atoms
        self.conn = conn

    def __getitem__(self, prop):
        if isinstance(prop, str):
            prop = self.atoms[prop]

        typ, typ_fmt = prop.type
        wid = self.window.wid
        r = self.conn.core.GetProperty(
            False,           # delete
            wid,             # window id
            prop.id,
            prop.rawtype,
            0,               # long_offset,
            (2 ** 32) - 1    # long_length
        ).reply()

        if typ == CARDINAL:
            return r.value.to_atoms()[0]
        elif typ in ["STRING", "UTF8_STRING"]:
            return r.value.to_utf8()
        elif typ == ATOM:
            return [self.atoms[id] for id in r.value.to_atoms()]
        else:
            raise Exception("Uknown type {}".format(typ))

    def __setitem__(self, prop, value):
        if isinstance(prop, str):
            prop = self.atoms[prop]

        _, type_fmt = prop.type
        wid = self.window.wid

        # pack data into a format readable by xcffib
        if isinstance(value, str):
            value = value.encode()
        elif isinstance(value, int):
            value = [value]
        elif isinstance(value, list):
            l = []
            for v in value:
                if isinstance(v, int):
                    l.append(v)
                if isinstance(v, Atom):
                    l.append(v.id)
                elif isinstance(v, str):
                    atom = self.atoms[v]
                    l.append(atom)
                else:
                    raise Exception(
                        "unknow type %s in array %s" %
                        (type(v), value))
            value = l
        else:
            raise Exception("unknown type %s" % type(value))

        self.conn.core.ChangePropertyChecked(
            xproto.PropMode.Replace,
            wid,
            prop.id,
            prop.rawtype,
            type_fmt,  # Format - 8, 16, 32
            len(value),
            value
        ).check()

    def __dir__(self):
        wid = self.window.wid
        reply = self.conn.core.ListProperties(wid).reply()
        ids = reply.atoms.list
        return [self.atoms[id] for id in ids]
