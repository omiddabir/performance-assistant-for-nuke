"""Editable local snapshots with no fixed count limit. Saving a preset never writes Nuke preferences."""
import copy
import json
import os
from pathlib import Path
from .storage import atomic_write, json_bytes, fingerprint
from .specs import BY_KEY
from .policy import recommendations

def valid_name(name):
    return isinstance(name, str) and 0 < len(name.strip()) <= 80 and name == name.strip() and not any(ord(c) < 32 for c in name)

NAMES = ('Shared', 'Comp focused', 'User preset')

def clean_values(values):
    if not isinstance(values, dict):
        raise ValueError('Invalid preset values.')
    out = {}
    for key, value in values.items():
        if key not in BY_KEY:
            continue
        spec = BY_KEY[key]
        if spec.kind in ('float', 'int'):
            import math
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Invalid preset number: ' + key)
            if not spec.low <= value <= spec.high or (spec.kind == 'int' and int(value) != value):
                raise ValueError('Preset value outside range: ' + key)
        elif spec.kind == 'bool' and not isinstance(value, bool):
            raise ValueError('Invalid preset switch: ' + key)
        elif spec.kind in ('path', 'enum') and not isinstance(value, str):
            raise ValueError('Invalid preset text: ' + key)
        out[key] = value
    return out

class Presets:
    def __init__(self, folder):
        self.path = Path(folder) / 'presets.json'
        self.lock = Path(folder) / 'presets.lock'
        self.expected = fingerprint(self.path)
        self.profiles = {}
        self.planning = {}
        self.confirmed = {}
        self.selected = 'Shared'
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('schema') != 1 or not isinstance(data.get('presets'), dict):
                raise ValueError('Invalid preset file; existing file was not changed.')
            self.profiles = {name: clean_values(v) for name, v in data['presets'].items() if valid_name(name)}
            for name, value in data.get('worker_ram_gb', {}).items():
                if name in self.profiles and isinstance(value, (int, float)) and .25 <= value <= 65536:
                    self.planning[name] = value
            self.confirmed = {name: True for name, flag in data.get('worker_ram_confirmed', {}).items()
                              if flag is True and name in self.planning}
            if data.get('selected') in self.names():
                self.selected = data['selected']

    def names(self):
        return list(NAMES) + sorted(n for n in self.profiles if n not in NAMES)

    def load(self, name, current, hardware, devices):
        if name not in self.names():
            raise ValueError('Unknown preset.')
        if name in self.profiles:
            result = dict(current)
            result.update({k: v for k, v in self.profiles[name].items() if k in current})
            return result
        result = dict(current)
        if name in NAMES[:2]:
            result.update(recommendations(hardware, result, devices, name)[0])
        return result

    def rename(self, old, new):
        if old in NAMES or old not in self.profiles:
            raise ValueError('Only custom presets can be renamed.')
        if not valid_name(new) or new in self.names():
            raise ValueError('Choose a new unique preset name.')
        self._write(new, self.profiles[old], remove=old, worker_ram_gb=self.planning.get(old), worker_ram_confirmed=self.confirmed.get(old, False))

    def delete(self, name):
        if name in NAMES or name not in self.profiles:
            raise ValueError('Built-in presets cannot be deleted.')
        self._write('Shared', self.profiles.get('Shared', {}), remove=name, write_profile=False)

    def save(self, name, values, worker_ram_gb=None, worker_ram_confirmed=False):
        self._write(name, values, worker_ram_gb=worker_ram_gb, worker_ram_confirmed=worker_ram_confirmed)

    def _write(self, name, values, remove=None, worker_ram_gb=None, write_profile=True, worker_ram_confirmed=False):
        if not valid_name(name):
            raise ValueError('Use a non-empty name of at most 80 characters.')
        values = clean_values(values)
        if worker_ram_gb is not None and not (isinstance(worker_ram_gb, (int, float)) and .25 <= worker_ram_gb <= 65536):
            raise ValueError('Invalid RAM per worker estimate.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise RuntimeError('Preset file is symlinked; no changes made.')
        try:
            fd = os.open(str(self.lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise RuntimeError('Another preset save holds the lock.')
        try:
            os.close(fd)
            if fingerprint(self.path) != self.expected:
                raise RuntimeError('Presets changed in another window. Reopen the assistant.')
            profiles = copy.deepcopy(self.profiles)
            planning = dict(self.planning)
            confirmed = dict(self.confirmed)
            if remove is not None: confirmed.pop(remove, None)
            if worker_ram_gb is not None: confirmed[name] = worker_ram_confirmed is True
            if remove is not None: planning.pop(remove, None)
            if worker_ram_gb is not None: planning[name] = worker_ram_gb
            if remove is not None: profiles.pop(remove, None)
            merged = dict(profiles.get(name, {}))
            merged.update(values)
            if write_profile: profiles[name] = merged
            if self.path.exists():
                atomic_write(self.path.with_suffix('.json.bak'), self.path.read_bytes())
            atomic_write(self.path, json_bytes({'schema': 1, 'selected': name, 'presets': profiles, 'worker_ram_gb': planning, 'worker_ram_confirmed': confirmed}))
            self.profiles, self.selected, self.planning = profiles, name, planning
            self.confirmed = confirmed
            self.expected = fingerprint(self.path)
        finally:
            self.lock.unlink()
