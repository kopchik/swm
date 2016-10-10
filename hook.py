from useful.log import Log

from collections import defaultdict
import traceback


class Hook:
    """ Simple callback dispatcher. """

    def __init__(self):
        self.cb_map = defaultdict(list)
        self.log = Log("hook")
        self.suppressed = set()

    def decor(self, event):
        def wrap(cb):
            self.register(event, cb)
            return cb
        return wrap
    __call__ = decor

    def register(self, event, cb):
        self.cb_map[event].append(cb)

    def has_hook(self, event):
        return event in self.cb_map

    def suppress(self, event):
        hook = self

        class Context:

            def __enter__(self):
                hook.log.debug("suppressing %s" % event)
                hook.suppressed.add(event)

            def __exit__(self, *args):
                hook.log.debug("un-suppressing %s" % event)
                if event in hook.suppressed:
                    hook.suppressed.remove(event)
                else:
                    hook.log.notice("uhm, event is not suppressed: %s" % event)
        return Context()

    def fire(self, event, *args, **kwargs):
        if event not in self.cb_map:
            self.log.notice("no handler for %s" % event)
            return

        if event in self.suppressed:
            self.log.debug(
                "event suppressed: {} {} {}".format(event, args, kwargs))
            return

        handlers = self.cb_map[event]
        for handler in handlers:
            try:
                handler(event, *args, **kwargs)
            # except SupressEvent:
                # break
            except Exception as err:
                # msg = "error on event {ev}: {err} ({typ}) (in {hdl})" \
                #     .format(err=err, typ=type(err), ev=event, hdl=handler)
                msg = traceback.format_exc()
                self.log.error(msg)

        # if DEBUG:
        #    time.sleep(0.03)
