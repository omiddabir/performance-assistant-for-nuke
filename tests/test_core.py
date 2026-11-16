import ast
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from nuke_performance_assistant.policy import recommendations, validate
from nuke_performance_assistant.hardware import parse_nvidia, detect
from nuke_performance_assistant.specs import discover
from nuke_performance_assistant.storage import Store, atomic_write, fingerprint
from nuke_performance_assistant.backend import Controller


def hardware():
    return {'logical_cpus': 16, 'ram_gb': 64, 'worker_ram_gb': 1., 'worker_ram_confirmed': True, 'gpus': [
        {'name': 'NVIDIA GeForce RTX 4070 Ti SUPER', 'vram_gb': 16}],
        'disk': {'free_gb': 400, 'total_gb': 1000}}


def current():
    return {'threads': 16, 'workers': 8, 'comp_pct': 90., 'timeline_pct': 10.,
            'playback_pct': 50., 'paint_pct': 90., 'disk_gb': 100., 'paint_disk_gb': 100.,
            'gpu': 'NVIDIA GeForce RTX 4070 Ti SUPER', 'texture_mb': 1000, 'blink_pct': 50.}


class Knob:
    def __init__(self, label, value, cls='Double_Knob', choices=()):
        self._label, self._value, self.cls, self.choices = label, value, cls, choices
        self.fail = False
        self.clamp = None
    def label(self): return self._label
    def Class(self): return self.cls
    def value(self): return self._value
    def values(self): return self.choices
    def arraySize(self): return 1
    def evaluate(self): return self._value
    def setValue(self, v):
        if self.fail: raise RuntimeError('injected knob failure')
        self._value = min(v, self.clamp) if self.clamp is not None else v


class Prefs:
    def __init__(self, knobs): self._knobs = knobs
    def knobs(self): return self._knobs
    def writeKnobs(self, flags):
        return '\n'.join(k + ' ' + str(v.value()) for k, v in self._knobs.items())


class FakeNuke:
    NUKE_VERSION_MAJOR, NUKE_VERSION_MINOR, NUKE_VERSION_RELEASE = 17, 1, 2
    TO_SCRIPT, WRITE_USER_KNOB_DEFS, WRITE_NON_DEFAULT_ONLY = 1, 2, 4
    def __init__(self):
        self.env = {'threads': 16, 'gui': True}
        self.prefs = Prefs({'cache': Knob('comp cache size (%)', 50.),
                            'worker': Knob('frame server processes to run*', 1, 'Int_Knob'),
                            'unrelated': Knob('autosave', 42)})
    def toNode(self, name): return self.prefs
    def tprint(self, text): pass


class PolicyTests(unittest.TestCase):
    def test_budgets_not_maxima(self):
        v, why = recommendations(hardware(), current(), [current()['gpu']])
        self.assertLess(v['threads'], 16)
        self.assertLess(v['comp_pct'], 90)
        self.assertEqual(v['workers'], 1)
        self.assertTrue(all(why[k] for k in v))
        self.assertLessEqual(v['disk_gb'] + v['paint_disk_gb'], 150)
    def test_locked_fields_never_changed(self):
        v, _ = recommendations(hardware(), current(), [current()['gpu']], locks=list(current()))
        self.assertEqual(v, {})
    def test_unknown_ram_and_vram(self):
        h = hardware(); h['ram_gb'] = None; h['gpus'] = []
        v, _ = recommendations(h, current(), [current()['gpu']])
        self.assertNotIn('comp_pct', v); self.assertNotIn('blink_pct', v)
    def test_tiny_system(self):
        h = hardware(); h.update(logical_cpus=1, ram_gb=2)
        v, _ = recommendations(h, current(), [current()['gpu']])
        self.assertEqual(v, {}); self.assertIn('blocked', _)
    def test_multiple_gpus_not_guessed(self):
        c = current(); c['gpu'] = 'CPU'
        v, _ = recommendations(hardware(), c, ['CPU', 'GPU A', 'GPU B'])
        self.assertNotIn('gpu', v)
        self.assertNotIn('texture_mb', v)
    def test_single_gpu_selected(self):
        c = current(); device = c['gpu']; c['gpu'] = 'CPU'
        v, _ = recommendations(hardware(), c, ['CPU', device])
        self.assertEqual(v['gpu'], device); self.assertIn('texture_mb', v)
    def test_low_disk_no_increase(self):
        h = hardware(); h['disk']['free_gb'] = 5
        v, _ = recommendations(h, current(), [current()['gpu']])
        self.assertNotIn('disk_gb', v)
    def test_invalid_numeric_inputs(self):
        for v in (float('nan'), float('inf'), -1, True, '80'):
            self.assertTrue(validate({'comp_pct': v}, current(), hardware(), [current()['gpu']])[0])
    def test_thread_oversubscription(self):
        self.assertTrue(validate({'threads': 17}, current(), hardware(), [current()['gpu']])[0])
    def test_dangerous_vram_rejected(self):
        self.assertTrue(validate({'texture_mb': 16000}, current(), hardware(), [current()['gpu']])[0])
    def test_subcache_limits_can_overlap(self):
        errors, _ = validate({'playback_pct': 80, 'paint_pct': 80}, current(), hardware(), [current()['gpu']])
        self.assertFalse(errors)
    def test_nvidia_parse(self):
        result = parse_nvidia('NVIDIA RTX, 16376, GPU-123\nNVIDIA bad, N/A, x\n')
        self.assertEqual(len(result), 1); self.assertAlmostEqual(result[0]['vram_gb'], 15.992, places=2)


class DiscoveryTests(unittest.TestCase):
    def test_exact_label_type_guard(self):
        p = Prefs({'correct': Knob('comp cache size (%)', 50),
                   'wrong': Knob('comp cache size (%)', '50', 'String_Knob')})
        found, _ = discover(p)
        self.assertEqual(found['comp_pct'][0], 'correct')
    def test_ambiguous_disabled(self):
        p = Prefs({'a': Knob('comp cache size (%)', 50), 'b': Knob('comp cache size (%)', 40)})
        found, missing = discover(p)
        self.assertNotIn('comp_pct', found); self.assertIn('Ambiguous', missing['comp_pct'])
    def test_no_fuzzy_match(self):
        found, _ = discover(Prefs({'x': Knob('other comp cache size (%)', 50)}))
        self.assertNotIn('comp_pct', found)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name, '17.1')
    def test_roundtrip_and_backups(self):
        self.store.commit(b'Preferences {\na 1\n}', {'schema': 1, 'threads': 8})
        backup = self.store.commit(b'Preferences {\na 2\n}', {'schema': 1, 'threads': 6})
        self.assertEqual(self.store.load()['threads'], 6)
        self.assertIn(b'a 1', (Path(backup) / 'preferences.nk').read_bytes())
    def test_external_edit_rejected(self):
        self.store.native.write_bytes(b'external')
        with self.assertRaises(RuntimeError): self.store.commit(b'new', {'schema': 1})
        self.assertEqual(self.store.native.read_bytes(), b'external')
    def test_write_failure_rolls_back_both_files(self):
        self.store.commit(b'old', {'schema': 1, 'threads': 4})
        original = atomic_write
        triggered = [False]
        def fail(path, content):
            if Path(path) == self.store.native and not triggered[0]:
                triggered[0] = True
                raise OSError('disk full')
            return original(path, content)
        with patch('nuke_performance_assistant.storage.atomic_write', side_effect=fail):
            with self.assertRaises(OSError): self.store.commit(b'new', {'schema': 1, 'threads': 8})
        self.assertEqual(self.store.native.read_bytes(), b'old')
        self.assertEqual(self.store.load()['threads'], 4)
        self.assertFalse(self.store.journal.exists())
    def test_active_lock_blocks_save(self):
        self.store.folder.mkdir(parents=True)
        self.store.lock.write_text(str(os.getpid()))
        with self.assertRaises(RuntimeError): self.store.commit(b'new', {'schema': 1})
        self.assertTrue(self.store.lock.exists())
    def test_versions_are_separate(self):
        other = Store(self.tmp.name, '15.0')
        self.store.commit(b'17', {'schema': 1})
        other.commit(b'15', {'schema': 1})
        self.assertEqual(self.store.native.read_bytes(), b'17')


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'NPA_NUKE_DIR': self.tmp.name})
        self.env.start(); self.addCleanup(self.env.stop)
        self.nuke = FakeNuke(); self.control = Controller(self.nuke)
    def test_apply_persist_restore_preserves_unrelated(self):
        self.control.apply({'comp_pct': 40, 'threads': 12}, hardware(), [], 'Shared', warnings_accepted=True)
        fresh = Controller(self.nuke)
        self.assertEqual(fresh.state['threads'], 12)
        self.assertIn(b'unrelated 42', fresh.store.native.read_bytes())
        fresh.apply(fresh.state['previous'], hardware(), [], 'Shared', restoring=True, warnings_accepted=True)
        self.assertEqual(fresh.current()['comp_pct'], 50)
        self.assertIsNone(fresh.state['threads'])
    def test_knob_failure_rolls_back(self):
        self.nuke.prefs._knobs['worker'].fail = True
        with self.assertRaises(RuntimeError):
            self.control.apply({'comp_pct': 40, 'workers': 2}, hardware(), [], 'Shared', warnings_accepted=True)
        self.assertEqual(self.control.current()['comp_pct'], 50)
        self.assertFalse(self.control.store.native.exists())
    def test_clamp_caught(self):
        self.nuke.prefs._knobs['cache'].clamp = 45
        with self.assertRaises(RuntimeError):
            self.control.apply({'comp_pct': 60}, hardware(), [], 'Shared', warnings_accepted=True)
        self.assertFalse(self.control.store.native.exists())
    def test_stale_panel_rejected(self):
        self.nuke.prefs._knobs['cache'].setValue(60)
        with self.assertRaises(RuntimeError): self.control.apply({'comp_pct': 40}, hardware(), [], 'Shared', warnings_accepted=True)
    def test_early_13_thread_bug(self):
        self.nuke.NUKE_VERSION_MAJOR = 13; self.nuke.NUKE_VERSION_MINOR = 0; self.nuke.NUKE_VERSION_RELEASE = 1
        c = Controller(self.nuke)
        self.assertNotIn('threads', c.current())
    def test_unknown_future_major_fails_closed(self):
        self.nuke.NUKE_VERSION_MAJOR = 18
        with self.assertRaises(RuntimeError): Controller(self.nuke)
    def test_python37_syntax(self):
        for path in Path('.').rglob('*.py'):
            if '__pycache__' not in str(path):
                ast.parse(path.read_text(encoding='utf-8'), filename=str(path), feature_version=(3, 7))


if __name__ == '__main__': unittest.main()
