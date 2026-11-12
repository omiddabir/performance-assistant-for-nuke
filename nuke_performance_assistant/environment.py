"""Access Nuke's GlobalsEnvironment through its indexed API only."""
_MISSING = object()


def env_value(nuke, key, default=None):
    try:
        return nuke.env[key]
    except (LookupError, TypeError, AttributeError, RuntimeError):
        return default


def env_has(nuke, key):
    return env_value(nuke, key, _MISSING) is not _MISSING
