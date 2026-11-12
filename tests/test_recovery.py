import base64
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from nuke_performance_assistant.storage import Store, atomic_write, json_bytes
from nuke_performance_assistant.backend import Controller
from test_core import FakeNuke, hardware


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s = Store(self.tmp.name, '17.1')
        self.oldstate = json_bytes({'schema': 1, 'threads': 2})
        self.newstate = json_bytes({'schema': 1, 'threads': 4})
        self.s.folder.mkdir(parents=True)
        journal = {}
        for key, before, after in (('native', b'old', b'new'), ('state', self.oldstate, self.newstate)):
            journal[key + '_before'] = base64.b64encode(before).decode('ascii')
            journal[key + '_before_hash'] = hashlib.sha256(before).hexdigest()
            journal[key + '_after_hash'] = hashlib.sha256(after).hexdigest()
        atomic_write(self.s.journal, json_bytes(journal))
        atomic_write(self.s.native, b'old')
        atomic_write(self.s.state, self.newstate)
    def test_partial_commit_recovered(self):
        self.assertTrue(self.s.recover())
        self.assertEqual(self.s.native.read_bytes(), b'old')
        self.assertEqual(self.s.state.read_bytes(), self.oldstate)
        self.assertFalse(self.s.journal.exists())
    def test_new_external_edit_not_overwritten(self):
        self.s.native.write_bytes(b'external')
        with self.assertRaises(RuntimeError): self.s.recover()
        self.assertEqual(self.s.native.read_bytes(), b'external')
        self.assertTrue(self.s.journal.exists())
    def test_live_save_not_recovered(self):
        self.s.lock.write_text(str(os.getpid()))
        with self.assertRaises(RuntimeError): self.s.recover()
        self.assertEqual(self.s.state.read_bytes(), self.newstate)
    def test_symlink_native_not_overwritten(self):
        self.s.journal.unlink()
        self.s.native.unlink()
        target = Path(self.tmp.name) / 'studio.nk'; target.write_bytes(b'studio')
        try: self.s.native.symlink_to(target)
        except OSError: self.skipTest('symlink creation not available')
        self.s.refresh()
        with self.assertRaises(RuntimeError): self.s.commit(b'new', {'schema': 1})
        self.assertEqual(target.read_bytes(), b'studio')
        self.assertTrue(self.s.native.is_symlink())


class VersionAndPersistenceTests(unittest.TestCase):
    def test_target_major_versions_with_simulated_api(self):
        for major in range(13, 18):
            with self.subTest(major=major), tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'NPA_NUKE_DIR': d}):
                n = FakeNuke(); n.NUKE_VERSION_MAJOR = major
                c = Controller(n)
                c.apply({'comp_pct': 40}, hardware(), ['comp_pct'], 'Shared', warnings_accepted=True)
                self.assertEqual(c.current()['comp_pct'], 40)
                self.assertEqual(c.store.load()['locks'], ['comp_pct'])
    def test_saved_loaded_difference_report(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'NPA_NUKE_DIR': d}):
            n = FakeNuke(); c = Controller(n)
            c.apply({'comp_pct': 40}, hardware(), [], 'Shared', warnings_accepted=True)
            n.prefs._knobs['cache'].setValue(45)
            c2 = Controller(n)
            self.assertEqual(c2.loaded_differences()['comp_pct'], {'saved': 40., 'loaded': 45.})
    def test_busy_render_prevents_apply(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'NPA_NUKE_DIR': d}):
            n = FakeNuke(); n.executing = lambda: True
            c = Controller(n)
            with self.assertRaises(RuntimeError): c.apply({'comp_pct': 40}, hardware(), [], 'Shared')
            self.assertEqual(c.current()['comp_pct'], 50)
