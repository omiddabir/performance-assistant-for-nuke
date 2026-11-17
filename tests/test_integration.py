"""Contract tests with a simulated Nuke API; not native Nuke certification."""
import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from test_core import FakeNuke, Knob, hardware
from nuke_performance_assistant.storage import Store


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.nuke = FakeNuke()
        self.ctx = patch.dict(os.environ, {'NPA_NUKE_DIR': self.tmp.name, 'NPA_DISABLE_STARTUP': '0'})
        self.ctx.start(); self.addCleanup(self.ctx.stop)
        self.modules = patch.dict(sys.modules, {'nuke': self.nuke})
        self.modules.start(); self.addCleanup(self.modules.stop)
        Store(self.tmp.name, '17.1').commit(b'Preferences {}', {'schema': 1, 'threads': 2})
    def run_startup(self, argv=('Nuke',)):
        from nuke_performance_assistant import startup
        with patch.object(sys, 'argv', list(argv)), patch('nuke_performance_assistant.hardware.usable_cpus', return_value=16):
            startup()
    def test_gui_restores_without_native_writes(self):
        path = Path(self.tmp.name) / 'preferences17.1.nk'; before = path.read_bytes()
        self.run_startup()
        self.assertEqual(self.nuke.env['threads'], 2)
        self.assertEqual(path.read_bytes(), before)
    def test_cli_explicit_limit_wins(self):
        for argv in (('Nuke', '-m', '6'), ('Nuke', '-m6')):
            self.run_startup(argv)
            self.assertEqual(self.nuke.env['threads'], 16)
    def test_headless_untouched(self):
        self.nuke.env['gui'] = False
        self.run_startup(); self.assertEqual(self.nuke.env['threads'], 16)
    def test_disable_switch(self):
        with patch.dict(os.environ, {'NPA_DISABLE_STARTUP': '1'}): self.run_startup()
        self.assertEqual(self.nuke.env['threads'], 16)
    def test_corrupt_state_nonfatal(self):
        (Path(self.tmp.name) / 'performance_assistant/17.1/state.json').write_text('{broken')
        self.run_startup(); self.assertEqual(self.nuke.env['threads'], 16)



    def test_saved_threads_replace_nondefault_start(self):
        self.nuke.env['threads'] = 7
        self.run_startup()
        self.assertEqual(self.nuke.env['threads'], 2)

    def test_saved_threads_respect_single_allowed_cpu(self):
        from nuke_performance_assistant import startup
        self.nuke.env['threads'] = 1
        with patch.object(sys, 'argv', ['Nuke']), patch('nuke_performance_assistant.hardware.usable_cpus', return_value=1):
            startup()
        self.assertEqual(self.nuke.env['threads'], 1)


class UsableCpuTests(unittest.TestCase):
    def test_cpu_count_and_affinity_minimum(self):
        from nuke_performance_assistant.hardware import usable_cpus
        for total, affinity, expected in ((16, {0}, 1), (2, {0,1,2,3}, 2), (None, {0}, 1)):
            with patch('os.cpu_count', return_value=total), patch('os.sched_getaffinity', return_value=affinity, create=True):
                self.assertEqual(usable_cpus(), expected)

    def test_detection_uses_shared_helper(self):
        from nuke_performance_assistant.hardware import detect
        with patch('nuke_performance_assistant.hardware.usable_cpus', return_value=3), patch('platform.system', return_value='Test'), patch('shutil.which', return_value=None):
            self.assertEqual(detect('/tmp')['logical_cpus'], 3)
