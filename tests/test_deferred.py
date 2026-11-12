"""Deferred scheduling contract; native Qt/Nuke execution is a separate test."""
import sys
import types
import unittest
from unittest.mock import patch
from nuke_performance_assistant.deferred import defer
from nuke_performance_assistant.presentation import equivalent, format_value, change_summary

class SchedulingTests(unittest.TestCase):
    def test_bundled_qt_selected_for_each_major(self):
        for major in range(13, 18):
            queued = []
            timer = types.SimpleNamespace(singleShot=lambda delay, fn: queued.append((delay, fn)))
            binding = 'PySide6' if major >= 16 else 'PySide2'
            modules = {'nuke': types.SimpleNamespace(NUKE_VERSION_MAJOR=major),
                       binding: types.ModuleType(binding),
                       binding + '.QtCore': types.SimpleNamespace(QTimer=timer)}
            called = []
            with patch.dict(sys.modules, modules):
                defer(lambda: called.append(True))
            self.assertEqual(called, [])
            self.assertEqual(queued[0][0], 0)
            queued[0][1]()
            self.assertEqual(called, [True])

class PresentationTests(unittest.TestCase):
    def test_native_float_noise_is_not_a_change(self):
        self.assertTrue(equivalent(89.999999996022, 90.0))
        self.assertFalse(equivalent(90.0, 89.0))
        self.assertIn('No setting changes', change_summary({'comp_pct': 89.999999996022}, {'comp_pct': 90.0}))
    def test_numbers_round_only_for_display(self):
        self.assertEqual(format_value(89.999999996022), '90')
        self.assertEqual(format_value(15.9921875), '15.99')
        self.assertEqual(format_value(False), 'Off')
    def test_restart_is_visible_in_review(self):
        self.assertIn('(restart)', change_summary({'texture_mb': 1000}, {'texture_mb': 982}))
