"""Nuke Performance Assistant. No hardware scans or preference writes on import."""
__version__ = '0.6.0-preview'
from .environment import env_value, env_has


def startup():
    """Restore only the compute thread limit; native Preferences load other settings."""
    import os
    import sys
    import nuke
    if not env_value(nuke, 'gui', False) or not 13 <= nuke.NUKE_VERSION_MAJOR <= 17:
        return
    if os.environ.get('NPA_DISABLE_STARTUP') == '1':
        return
    if any(arg == '-m' or (arg.startswith('-m') and arg[2:].isdigit()) for arg in sys.argv[1:]):
        return  # Explicit launcher flags win; background/farm renders are never altered.
    if (nuke.NUKE_VERSION_MAJOR, nuke.NUKE_VERSION_MINOR) == (13, 0) and nuke.NUKE_VERSION_RELEASE < 10:
        return
    try:
        from .backend import user_directory, version_key
        from .storage import Store
        store = Store(user_directory(), version_key(nuke))
        if store.journal.exists():
            nuke.tprint('Performance Assistant: interrupted save detected. Open the assistant for recovery.')
            return
        value = store.load().get('threads')
        from .hardware import usable_cpus
        limit = usable_cpus()
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= limit and env_has(nuke, 'threads'):
            nuke.env['threads'] = value
    except Exception as exc:
        nuke.tprint('Performance Assistant startup skipped: ' + str(exc))


def show():
    import nuke
    try:
        from .ui import AssistantPanel
        panel = AssistantPanel()
        try:
            panel.showModalDialog()
        finally:
            panel.closed = True
    except Exception as exc:
        import traceback
        traceback.print_exc()
        nuke.message('Performance Assistant: ' + str(exc))
