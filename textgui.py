from useful.libgui import mywrapper, myinput, Border, VList, CMDInput, Text
import sys

# DOM
root = Border(
    VList(
        Border(Text(id='logwin'), label="Logs"),
        Border(CMDInput(id='cmdinpt'), label="CMD Input")
    )
)


@mywrapper
def gui(loop):
    root.initroot()

    # setup input
    inpt = myinput(timeout=0)

    def reader():
        key = next(inpt)
        if root.cur_focus:
            root.cur_focus.input(key)
    loop.add_reader(sys.stdin, reader)

    logwin = root['logwin']
    return logwin
