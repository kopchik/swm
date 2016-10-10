#!/usr/bin/env python3

import subprocess
import shlex

CMD = 'osd_cat -A center -l 1 -c white -p bottom -f -*-*-bold-*-*-*-72-120-*-*-*-*-*-* -c red -s 5'


class OSD:

    def __init__(self, cmd=CMD):
        self.pipe = subprocess.Popen(shlex.split(cmd), stdin=subprocess.PIPE)

    def write(self, s):
        s = str(s)
        if not s.endswith('\n'):
            s = s + '\n'
        self.pipe.stdin.write(bytes(s, 'ascii', errors='ignore'))
        self.pipe.stdin.flush()

if __name__ == '__main__':
    osd = OSD()
    osd.write('1')
