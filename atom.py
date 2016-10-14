from defs import PROPERTYMAP


class Atom:

    def __init__(self, name: str, id: int, type: str, rawtype: int):
        assert isinstance(name, str)
        assert isinstance(id, int)
        assert isinstance(type, (tuple, list))
        self.type = type
        self.name = name
        self.id = id
        self.rawtype = rawtype

    def __eq__(self, other):
        if not isinstance(other, Atom):
            return False

        if self.name == other.name:
            assert self.id == other.id
            assert self.type == other.type
            return True
        return False

    def __repr__(self):
        return "Atom(\"{name}\", {id}, {type})".format(
            name=self.name, id=self.id, type=self.type)


class AtomVault:
    """ Caches atoms, etc. """

    def __init__(self, conn):
        self.conn = conn
        self._atoms = {}

    def get_id(self, name: str):
        reply = self.conn.core.InternAtom(True, len(name), name).reply()
        atom = reply.atom
        return atom

    def get_name(self, id: int):
        c = self.conn.core.GetAtomName(id)
        name = c.reply().name.to_string()
        return name

    def __getitem__(self, name):
        if isinstance(name, int):
            name = self.get_name(name)
        return getattr(self, name)

    def __getattr__(self, name: str):
        if name not in self._atoms:
            try:
                type = PROPERTYMAP[name]
            except KeyError:
                raise Exception("unknown atom/property %s, please add it into PROPERTYMAP" % name)
            id = self.get_id(name)
            rawtype = self.get_id(type[0])
            atom = Atom(name, id, type, rawtype)
            self._atoms[name] = atom
        return self._atoms[name]
