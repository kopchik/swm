from atom import AtomVault
import xcffib
from xcffib import xproto

conn = xcffib.connect()


def test_get_atom():
    # lookup a standard atom
    atoms = AtomVault(conn)
    WM_NAME = atoms.WM_NAME
    assert WM_NAME.id == xproto.Atom.WM_NAME

    # sanity check
    _NET_WM_NAME = atoms._NET_WM_NAME
    _NET_WM_NAME.name == "_NET_WM_NAME"
    assert _NET_WM_NAME.type == ('UTF8_STRING', 8)
    assert _NET_WM_NAME.name in atoms._atoms

    # lookup by integer id
    assert atoms[_NET_WM_NAME.id] == _NET_WM_NAME
