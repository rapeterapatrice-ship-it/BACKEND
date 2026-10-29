from contextvars import ContextVar


_audit_actor = ContextVar('audit_actor', default=None)


def set_audit_actor(actor):
    return _audit_actor.set(actor)


def reset_audit_actor(token):
    _audit_actor.reset(token)


def get_audit_actor():
    return _audit_actor.get()
