"""The verb registry: a backend's verb modules decorate their handlers with register(*names), one name per
alias, and cli.main dispatches through HANDLERS."""

HANDLERS = {}


def register(*names):
    def wrap(fn):
        for n in names:
            HANDLERS[n] = fn
        return fn
    return wrap
