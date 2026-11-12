"""Regression for Nuke GlobalsEnvironment: indexed access, not a Python dict."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_core import FakeNuke
from nuke_performance_assistant.backend import Controller
from nuke_performance_assistant.storage import Store


class IndexedEnvironment:
    __iter__ = None
    def __init__(self, values): self._values = dict(values)
    def __getitem__(self, key):
        if not isinstance(key, str): raise TypeError('String keys only')
        return self._values[key]
    def __setitem__(self, key, value): self._values[key] = value


class EnvironmentRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'NPA_NUKE_DIR': self.temp.name, 'NPA_DISABLE_STARTUP': '0'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.nuke = FakeNuke()
        self.nuke.env = IndexedEnvironment({'threads': 16, 'gui': True})
    def test_original_membership_assumption_reproduces_error(self):
        with self.assertRaises(TypeError): 'threads' in self.nuke.env
        self.assertEqual(self.nuke.env['threads'], 16)
    def test_controller_accepts_noniterable_environment(self):
        control = Controller(self.nuke)
        self.assertEqual(control.current()['threads'], 16)
    def test_missing_threads_disabled(self):
        self.nuke.env = IndexedEnvironment({'gui': True})
        self.assertNotIn('threads', Controller(self.nuke).current())
    def test_startup_reads_and_sets_indexed_environment(self):
        from nuke_performance_assistant import startup
        Store(self.temp.name, '17.1').commit(b'Preferences {}', {'schema': 1, 'threads': 1})
        with patch.dict(sys.modules, {'nuke': self.nuke}), patch.object(sys, 'argv', ['Nuke']):
            startup()
        self.assertEqual(self.nuke.env['threads'], 1)
    def test_menu_registers_without_dict_get(self):
        calls = []
        class Menu:
            def addCommand(self, *args): calls.append(args)
        self.nuke.menu = lambda name: Menu()
        with patch.dict(sys.modules, {'nuke': self.nuke}):
            exec(compile(Path('menu.py').read_text(), 'menu.py', 'exec'), {})
        self.assertEqual(calls[0][0], 'Tools/Performance Assistant')
