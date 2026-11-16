"""Nuke API boundary. Only explicit supported knobs are modified."""
import os
import math
from pathlib import Path
from .environment import env_has
from .specs import SPECS, BY_KEY, discover
from .storage import Store
from .hardware import disk_info
from .policy import validate
from .presentation import equivalent
from .frame_settings import discover_worker, FrameTransaction
from .limits import check_limits, RAM_GROUP


def user_directory():
    return Path(os.environ.get('NPA_NUKE_DIR', str(Path.home() / '.nuke'))).expanduser()


def version_key(nuke):
    return '{}.{}'.format(nuke.NUKE_VERSION_MAJOR, nuke.NUKE_VERSION_MINOR)


class Controller:
    def __init__(self, nuke):
        self.nuke = nuke
        if not 13 <= nuke.NUKE_VERSION_MAJOR <= 17:
            raise RuntimeError('This preview targets Nuke 13–17. New major versions need compatibility review.')
        self.prefs = nuke.toNode('preferences')
        if self.prefs is None:
            raise RuntimeError('Nuke Preferences are not available in this session.')
        self.store = Store(user_directory(), version_key(nuke))
        native_recovered = self.store.recover()
        self.state = self.store.load()
        self.mapping, self.unavailable = discover(self.prefs)
        self.worker_setting = discover_worker()
        self.frame_transaction = FrameTransaction(self.store.folder, self.worker_setting)
        frame_recovered = self.frame_transaction.recover(self.state)
        if native_recovered or frame_recovered:
            raise RuntimeError('An interrupted save was recovered. Restart Nuke before continuing.')
        if 'workers' not in self.mapping and self.worker_setting is not None:
            self.mapping['workers'] = ('frameserver/workercount', self.worker_setting)
            self.unavailable.pop('workers', None)
        self.thread_supported = env_has(nuke, 'threads')
        # Foundry ID 483961: 13.0v10 fixed unreliable thread limits.
        if (nuke.NUKE_VERSION_MAJOR, nuke.NUKE_VERSION_MINOR) == (13, 0) and nuke.NUKE_VERSION_RELEASE < 10:
            self.thread_supported = False
            self.unavailable['threads'] = 'Nuke 13.0 before v10 has a documented thread-limit bug (483961). Upgrade maintenance release.'
        elif not self.thread_supported:
            self.unavailable['threads'] = 'No compute-thread control exposed by this build.'
        self.initial = self.current()

    def current(self):
        result = {}
        for key, (_, knob) in self.mapping.items():
            spec = BY_KEY[key]
            v = knob.value()
            if spec.kind in ('int', 'float') and isinstance(v, (list, tuple)) and len(v) == 1:
                v = v[0]
            if spec.kind == 'int':
                v = int(v)
            elif spec.kind == 'float':
                v = float(v)
            elif spec.kind == 'bool':
                v = bool(v)
            result[key] = v
        if self.thread_supported:
            result['threads'] = int(self.nuke.env['threads'])
        return result

    def devices(self):
        return list(self.mapping['gpu'][1].values()) if 'gpu' in self.mapping else []

    def cache_path(self, value=None):
        override = os.environ.get('NUKE_DISK_CACHE')
        if override:
            return os.path.expandvars(os.path.expanduser(override))
        if value is not None and value != self.current().get('cache_path'):
            if value == '[getenv NUKE_TEMP_DIR]':
                return os.environ.get('NUKE_TEMP_DIR', '')
            return os.path.expandvars(os.path.expanduser(value))
        if 'cache_path' in self.mapping:
            knob = self.mapping['cache_path'][1]
            try:
                return knob.evaluate()
            except Exception:
                return os.path.expandvars(os.path.expanduser(knob.value()))
        return os.environ.get('NUKE_TEMP_DIR', '')

    def native_bytes(self):
        flags = self.nuke.TO_SCRIPT | self.nuke.WRITE_USER_KNOB_DEFS | self.nuke.WRITE_NON_DEFAULT_ONLY
        text = self.prefs.writeKnobs(flags)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError('Nuke did not serialize Preferences; nothing was saved.')
        return ('Preferences {\n' + text + '\n}\n').encode('utf-8')

    def _set(self, key, value):
        if key == 'threads':
            self.nuke.env['threads'] = int(value)
        else:
            self.mapping[key][1].setValue(value)
        got = self.current().get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            equal = abs(float(got) - float(value)) <= max(0.0001, abs(value) * 1e-6)
        else:
            equal = got == value
        if not equal:
            raise RuntimeError('{} was rejected or clamped by Nuke (requested {}, read {}).'.format(key, value, got))

    def check(self, proposed, hw, restoring=False):
        now = self.current()
        cpus = hw.get('logical_cpus')
        ram = hw.get('ram_gb')
        if not isinstance(cpus, (int, float)) or not math.isfinite(cpus) or cpus < 1 or cpus != int(cpus):
            return ['Enter a valid positive logical CPU count.'], []
        if ram is not None and (not isinstance(ram, (int, float)) or not math.isfinite(ram) or ram <= 0):
            return ['Enter valid system RAM, or zero for unknown.'], []
        for key in proposed:
            if key not in now:
                raise ValueError('Unsupported setting: ' + key)
        effective_hw = dict(hw)
        path = self.cache_path(proposed.get('cache_path'))
        effective_hw['disk'] = disk_info(path)
        errors, warnings = validate(proposed, now, effective_hw, self.devices())
        if not errors:
            checked = {k: v for k, v in proposed.items() if k in RAM_GROUP} if restoring else proposed
            limit_messages = check_limits(checked, now, effective_hw)
            if restoring:
                warnings.extend(limit_messages)
            else:
                errors.extend(limit_messages)
        if 'disk_gb' in proposed and os.environ.get('NUKE_DISK_CACHE_GB'):
            errors.append('NUKE_DISK_CACHE_GB controls the disk cache size in this session.')
        if 'cache_path' in proposed:
            if os.environ.get('NUKE_DISK_CACHE'):
                errors.append('NUKE_DISK_CACHE controls the cache path in this session.')
            p = Path(path)
            if '[' in str(p) or not p.is_absolute() or not p.is_dir() or not os.access(str(p), os.W_OK):
                errors.append('Choose an existing, writable absolute cache directory. New Tcl expressions are not accepted.')
        return errors, warnings

    def apply(self, proposed, hw, locks, mode, warnings_accepted=False, restoring=False):
        if getattr(self.nuke, 'executing', lambda: False)():
            raise RuntimeError('Wait for rendering to finish before changing performance settings.')
        now = self.current()
        errors, warnings = self.check(proposed, hw, restoring=restoring)
        if errors:
            raise ValueError('\n'.join(errors))
        if warnings and not warnings_accepted:
            raise ValueError('Review warnings before applying:\n' + '\n'.join(warnings))
        changed = {k: v for k, v in proposed.items() if not equivalent(now.get(k), v)}
        # A second window or a preference dialog must not be overwritten silently.
        if any(now.get(k) != self.initial.get(k) for k in changed):
            raise RuntimeError('Preferences changed while this panel was open. Reopen the assistant before applying.')
        previous = {k: now[k] for k in changed}
        saved = dict(self.state)
        saved.update(schema=1, locks=list(locks), mode=mode)
        if changed:
            saved['previous'] = previous
            saved['previous_threads'] = self.state.get('threads')
        if 'threads' in changed:
            saved['threads'] = proposed['threads']
        if restoring:
            saved['threads'] = self.state.get('previous_threads')
            saved['previous'] = {}
        external = 'workers' in changed and self.mapping.get('workers', (None, None))[1] is self.worker_setting and self.worker_setting is not None
        if external:
            saved['frame_transaction'] = self.frame_transaction.begin(now['workers'], changed['workers'])
        try:
            for key, value in changed.items():
                self._set(key, value)
            saved['last_applied'] = self.current()
            backup = self.store.commit(self.native_bytes(), saved)
        except Exception as exc:
            rollback_errors = []
            for key, value in previous.items():
                try:
                    self._set(key, value)
                except Exception as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
            if not rollback_errors and external:
                self.frame_transaction.finish()
            if rollback_errors:
                raise RuntimeError('{}\nRollback also failed: {}'.format(exc, '; '.join(rollback_errors)))
            raise
        self.state = saved
        if external:
            self.frame_transaction.finish()
        self.initial = self.current()
        restart = [BY_KEY[k].title for k in changed if BY_KEY[k].restart]
        return {'changed': list(changed), 'restart': restart, 'backup': backup}

    def diagnostic(self):
        from .frame_diagnostic import setting_candidates, playback_diagnostic
        return {'tool': '0.6.0-preview', 'nuke': version_key(self.nuke),
                'mappings': {key: {'name': name, 'class': knob.Class(), 'label': knob.label()}
                             for key, (name, knob) in self.mapping.items()},
                'unavailable': self.unavailable,
                'frame_server_setting_candidates': setting_candidates(),
                'playback_mapping_evidence': playback_diagnostic(),
                'cache_environment': {k: os.environ[k] for k in ('NUKE_TEMP_DIR', 'NUKE_DISK_CACHE', 'NUKE_DISK_CACHE_GB') if k in os.environ},
                'values': self.current(), 'native_preferences_file': str(self.store.native),
                'devices': self.devices(), 'saved_thread_limit': self.state.get('threads'),
                'loaded_vs_saved_differences': self.loaded_differences(),
                'preference_schema': [{'name': name, 'class': knob.Class(), 'label': knob.label()}
                                      for name, knob in sorted(self.prefs.knobs().items())]}

    def loaded_differences(self):
        now = self.current()
        return {key: {'saved': value, 'loaded': now.get(key)}
                for key, value in self.state.get('last_applied', {}).items()
                if key in now and not equivalent(now[key], value)}
