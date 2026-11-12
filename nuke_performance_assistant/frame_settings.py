"""Explicit ApplicationSettings adapter and recoverable cross-store writes.

Worker key confirmed in Nuke 15.1v2's FnNsFrameServer.workerCount source.
Other builds require the same installed source evidence; no guessed keys.
"""
import inspect
import json
import os
import sys
import uuid
from .storage import json_bytes, process_alive

KEY = 'frameserver/workercount'

class WorkerSetting:
    def __init__(self, settings): self.settings = settings
    def value(self): return int(self.settings.value(KEY))
    def setValue(self, value): self.settings.setValue(KEY, str(int(value)))
    def Class(self): return 'ApplicationSettings<int>'
    def label(self): return 'frame server processes to run'


def discover_worker():
    core = sys.modules.get('hiero.core')
    bridge = sys.modules.get('hiero.ui.nuke_bridge.FnNsFrameServer')
    if core is None or bridge is None: return None
    try:
        source = inspect.getsource(bridge.workerCount)
        if KEY not in source or 'ApplicationSettings' not in source: return None
        knob = WorkerSetting(core.ApplicationSettings())
        if not 1 <= knob.value() <= 256: return None
        return knob
    except (AttributeError, TypeError, ValueError, OSError, RuntimeError):
        return None

class FrameTransaction:
    def __init__(self, folder, knob):
        self.path = folder / 'frame_pending.json'
        self.knob = knob
        self.token = None

    def recover(self, state):
        if not self.path.exists(): return False
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if state.get('frame_transaction') == data['token']:
            self.path.unlink()  # Native/state commit finished; only cleanup was interrupted.
            return False
        if process_alive(data['pid']):
            raise RuntimeError('A Frame Server save is active. Close the other assistant/session first.')
        if self.knob is None:
            raise RuntimeError('Frame Server recovery requires ApplicationSettings in this Nuke build.')
        current = self.knob.value()
        if current not in (data['before'], data['after']):
            raise RuntimeError('Frame Server changed after an interrupted save. No settings overwritten.')
        self.knob.setValue(data['before'])
        if self.knob.value() != data['before']: raise RuntimeError('Frame Server recovery failed.')
        self.path.unlink()
        return True

    def begin(self, before, after):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        data = dict(token=token, pid=os.getpid(), before=before, after=after)
        fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(json_bytes(data)); stream.flush(); os.fsync(stream.fileno())
        self.token = token
        return token

    def finish(self):
        if self.token is not None:
            self.path.unlink()
            self.token = None
