"""Atomic individual writes, rollback journal and optimistic conflict detection."""
import base64
import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path


def read_bytes(path):
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return None


def fingerprint(path):
    content = read_bytes(path)
    return None if content is None else hashlib.sha256(content).hexdigest()


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


class Store:
    def __init__(self, directory, version):
        self.directory = Path(directory)
        self.native = self.directory / ('preferences' + version + '.nk')
        self.folder = self.directory / 'performance_assistant' / version
        self.state = self.folder / 'state.json'
        self.journal = self.folder / 'pending.json'
        self.lock = self.folder / 'write.lock'
        self.refresh()

    def refresh(self):
        self.expected = (fingerprint(self.native), fingerprint(self.state))

    def load(self):
        raw = read_bytes(self.state)
        if raw is None:
            return {}
        result = json.loads(raw.decode('utf-8'))
        if not isinstance(result, dict) or result.get('schema') != 1:
            raise ValueError('Unknown Performance Assistant state format. No changes made.')
        return result

    def recover(self, during_rollback=False):
        """Called only by the panel. Never silently recover while Nuke is starting."""
        if not self.journal.exists():
            return False
        data = json.loads(self.journal.read_text(encoding='utf-8'))
        if not during_rollback and self.lock.exists():
            try:
                pid = int(self.lock.read_text())
            except (OSError, ValueError):
                raise RuntimeError('Unreadable save lock. Close other sessions and inspect the lock file.')
            if process_alive(pid):
                raise RuntimeError('Another Nuke session is saving preferences. Wait until it finishes.')
        # Targets come from this Store, never paths from JSON.
        for target, key in ((self.native, 'native'), (self.state, 'state')):
            current = fingerprint(target)
            if current not in (data[key + '_before_hash'], data[key + '_after_hash']):
                raise RuntimeError('Interrupted save plus external edits. Recover manually from the backup; no files changed.')
        for target, key in ((self.native, 'native'), (self.state, 'state')):
            before = data[key + '_before']
            if before is None:
                if target.exists():
                    target.unlink()
            else:
                atomic_write(target, base64.b64decode(before))
        self.journal.unlink()
        if self.lock.exists():
            self.lock.unlink()
        self.refresh()
        return True

    def commit(self, native_bytes, state):
        if self.native.is_symlink() or self.state.is_symlink():
            raise RuntimeError('Preferences are symlinked. Ask the pipeline owner to configure storage; no files changed.')
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise RuntimeError('Another save or interrupted transaction holds the write lock. Close other sessions and inspect ' + str(self.lock))
        with os.fdopen(fd, 'w') as stream:
            stream.write(str(os.getpid()))
        before_native, before_state = read_bytes(self.native), read_bytes(self.state)
        try:
            if (fingerprint(self.native), fingerprint(self.state)) != self.expected:
                raise RuntimeError('Preferences changed on disk after this panel opened. Restart Nuke to load them before applying.')
            if self.journal.exists():
                raise RuntimeError('An interrupted transaction requires recovery before saving.')
            after_state = json_bytes(state)
            stamp = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
            backup = self.folder / 'backups' / stamp
            for filename, content in (('preferences.nk', before_native), ('state.json', before_state)):
                if content is not None:
                    atomic_write(backup / filename, content)
            journal = {}
            for key, before, after in (('native', before_native, native_bytes), ('state', before_state, after_state)):
                journal[key + '_before'] = None if before is None else base64.b64encode(before).decode('ascii')
                journal[key + '_before_hash'] = None if before is None else hashlib.sha256(before).hexdigest()
                journal[key + '_after_hash'] = hashlib.sha256(after).hexdigest()
            atomic_write(self.journal, json_bytes(journal))
            try:
                atomic_write(self.state, after_state)
                atomic_write(self.native, native_bytes)
            except Exception:
                # Recovery retains the journal if rollback cannot complete.
                self.recover(during_rollback=True)
                raise
            self.journal.unlink()
            self.refresh()
            return str(backup)
        finally:
            if self.lock.exists():
                self.lock.unlink()


def process_alive(pid):
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return kernel.GetLastError() == 5
        code = ctypes.c_ulong()
        try:
            ok = kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
            return not ok or code.value == 259
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
