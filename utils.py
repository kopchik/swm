from useful.log import Log
from defs import ModMasks

from subprocess import Popen
from itertools import chain
import shlex
import os
log = Log("utils")


def run(cmd):
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    # os.setpgrp supressses signal forwarding to children  # TODO: test this
    return Popen(cmd, preexec_fn=os.setpgrp)


def run_(cmd):
    try:
        return run(cmd)
    except Exception as err:
        log.run_.error("failed to exec %s: %s" % (cmd, err))


def get_modmask(modifiers):
    result = 0
    for m in modifiers:
        assert m in ModMasks, "unknown modifier %s" % m
        result |= ModMasks[m]
    return result


def cycle_from(l, pos):
    for e in chain(l[pos+1:], l[:pos]):
        yield e
