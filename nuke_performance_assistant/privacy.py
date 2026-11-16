"""Redact the assembled support export without modifying internal diagnostics."""
import copy
import ctypes
import getpass
import os
import platform
import re
import socket
from urllib.parse import unquote, quote

GENERIC = {'nuke', 'cache', 'user', 'admin', 'administrator', 'root', 'temp', 'home', 'localhost'}


def short_home(home):
    try:
        api = ctypes.windll.kernel32.GetShortPathNameW
        api.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        api.restype = ctypes.c_uint
        size = api(home, None, 0)
        if size:
            buf = ctypes.create_unicode_buffer(size)
            if 0 < api(home, buf, size) < size:
                return buf.value
    except (AttributeError, OSError, ValueError):
        pass
    return ''


def identities():
    home = os.path.expanduser('~')
    short = short_home(home)
    entries = [(home, '<home>'), (short, '<home>')]
    if short:
        entries.append((short.replace('\\', '/').rstrip('/').split('/')[-1], '<user>'))
    try:
        entries.append((getpass.getuser(), '<user>'))
    except Exception:
        pass
    for key in ('USERNAME', 'USER', 'LOGNAME'):
        entries.append((os.environ.get(key, ''), '<user>'))
    for getter in (socket.gethostname, platform.node):
        try:
            entries.append((getter(), '<computer>'))
        except OSError:
            pass
    entries.append((os.environ.get('COMPUTERNAME', ''), '<computer>'))
    return [(value, replacement) for value, replacement in entries
            if len(value) >= 3 and value.casefold() not in GENERIC]


def generic_path(value, preferences=False):
    value = unquote(value).replace('\\', '/')
    if value.startswith('[') and value.endswith(']'):
        return value
    if '<folder>' in value or value.startswith('<network share>'):
        return value
    if preferences:
        return '<home>/.nuke/' + value.rstrip('/').split('/')[-1]
    if value.startswith('//'):
        return '<network share>'
    # Only preserve install locations explicitly identifying Nuke.
    if re.match(r'(?i)(?:[a-z]:/Program Files(?: \(x86\))?/|/Applications/|/usr/local/)(?:[^/]+/)*Nuke[^/]*(?:/|$)', value):
        return value
    root = ''
    if re.match(r'(?i)^[a-z]:/', value):
        root = value[:3]
    elif value.startswith('/'):
        root = '/'  # Do not expose potentially identifying mount names.
    elif value.startswith('<home>'):
        root = '<home>/'
    else:
        return value if not '/' in value else '<folder>'
    last = value.rstrip('/').split('/')[-1]
    return root + '<folder>' + ('/' + last if last.lower() in ('nuke', '.nuke', 'temp') else '')


def redact_diagnostics(data, include_schema=False):
    result = copy.deepcopy(data)
    schema = result.pop('preference_schema', None)
    if schema is not None:
        result['preference_schema_count'] = len(schema)
        if include_schema:
            result['preference_schema'] = schema
    for gpu in result.get('hardware', {}).get('gpus', []):
        gpu.pop('uuid', None)
    entries = sorted(identities(), key=lambda item: len(item[0]), reverse=True)

    def scrub(text):
        if re.fullmatch(r'\[getenv [A-Za-z_][A-Za-z_0-9]*\]', text):
            return text
        for identity, replacement in entries:
            variants = {identity, identity.replace('\\', '/'), identity.replace('/', '\\')}
            variants.update(quote(v, safe='') for v in list(variants))
            variants.update(quote(v, safe='/\\:') for v in list(variants))
            for variant in sorted(variants, key=len, reverse=True):
                text = re.sub(r'(?:(?<![\w])|(?<=%2f)|(?<=%5c))' + re.escape(variant) + r'(?![\w])',
                              lambda match: replacement, text, flags=re.IGNORECASE)
        return text

    def walk(value, path=()):
        if isinstance(value, dict):
            return {key: walk(item, path+(key,)) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item, path) for item in value]
        if isinstance(value, tuple):
            return tuple(walk(item, path) for item in value)
        if isinstance(value, str):
            if path == ('native_preferences_file',):
                value = generic_path(value, preferences=True)
            elif (path == ('hardware','disk','path') or 'cache_environment' in path
                  or (path and path[-1] == 'cache_path')):
                value = generic_path(value)
            # Remove absolute paths from free text too, including evidence/help strings.
            value = re.sub(r'(?:[A-Za-z]:[\\/](?!<)|\\\\(?!<)|(?<![\w<>])/(?![<\s]))[^\n\r;"<>]*',
                           lambda m: generic_path(m.group(0)), value)
            return scrub(value)
        return value
    result = walk(result)
    result['privacy'] = {'level': 'redacted', 'removed': ['user name', 'computer name', 'GPU UUID', 'folder paths', 'full preference list'],
                         'note': 'Hardware model, OS, Nuke version and setting values are still included.'}
    return result
