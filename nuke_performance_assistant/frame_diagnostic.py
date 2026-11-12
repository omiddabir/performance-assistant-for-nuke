"""Read-only evidence for unsupported Frame Server preference mappings.

Reads literal setting references in already loaded Foundry Python modules.
Never executes source, imports a server, or writes settings. Candidates are
reported for review, never used as automatic writable preference mappings.
"""
import ast
import inspect
import sys


def setting_candidates():
    result = []
    for name, module in list(sys.modules.items()):
        if not name.startswith('hiero.') or not any(word in name.lower() for word in ('frameserver', 'preferences')):
            continue
        try:
            source = inspect.getsource(module)
            if len(source) > 2000000: continue
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute): continue
                if node.func.attr not in ('value', 'setValue', 'boolValue', 'setBoolValue', 'intValue'): continue
                if not node.args or not isinstance(node.args[0], ast.Str): continue
                key = node.args[0].s
                result.append({'module': name, 'method': node.func.attr, 'key': key, 'line': node.lineno})
        except (OSError, TypeError, SyntaxError):
            continue
    return result


def playback_diagnostic():
    """Read-only API/key evidence. No guessed setting calls or preference writes."""
    result = {'api': [], 'source_keys': [], 'qt_numeric_cache_settings': []}
    modules = list(sys.modules.items())
    remaining = 8000000
    for name, module in modules:
        if module is None: continue
        if name in ('hiero.core', 'hiero.ui', '_fnpython', 'hiero.core._fnpython'):
            for attr in dir(module):
                if not any(w in attr.lower() for w in ('cache', 'memory')): continue
                obj = getattr(module, attr, None)
                if callable(obj):
                    result['api'].append({'module': name, 'name': attr,
                                          'help': (getattr(obj, '__doc__', '') or '')[:800]})
        if not name.startswith('hiero.') or remaining <= 0: continue
        try:
            source = inspect.getsource(module)
            if len(source) > 2000000: continue
            remaining -= len(source)
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute): continue
                if node.func.attr not in ('value', 'setValue', 'boolValue', 'setBoolValue', 'intValue'): continue
                if not node.args or not isinstance(node.args[0], ast.Str): continue
                key = node.args[0].s
                if any(w in key.lower() for w in ('cache', 'memory', 'playback')):
                    result['source_keys'].append({'module': name, 'method': node.func.attr,
                                                  'key': key, 'line': node.lineno})
        except (OSError, TypeError, SyntaxError):
            continue
    # Read existing numeric cache keys only. QSettings is not the authoritative
    # ApplicationSettings API: candidates must be verified before any mapping.
    qt = sys.modules.get('PySide6.QtCore') or sys.modules.get('PySide2.QtCore')
    if qt is not None:
        try:
            app = qt.QCoreApplication.instance()
            if app and app.organizationName() and app.applicationName():
                settings = qt.QSettings()
                import math
                for key in settings.allKeys():
                    if not any(w in key.lower() for w in ('cache', 'memory', 'playback')): continue
                    raw = settings.value(key)
                    if not isinstance(raw, (str, int, float, bool)): continue
                    try: value = float(raw)
                    except (ValueError, TypeError): continue
                    if math.isfinite(value):
                        result['qt_numeric_cache_settings'].append({'key': key, 'value': value})
        except (AttributeError, RuntimeError):
            pass
    return result
