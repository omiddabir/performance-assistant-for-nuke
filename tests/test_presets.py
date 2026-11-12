import tempfile
import unittest
from pathlib import Path
from nuke_performance_assistant.presets import Presets, NAMES
from nuke_performance_assistant.policy import recommendations
from test_core import hardware, current

class PresetTests(unittest.TestCase):
    def test_all_three_editable_persisted_independently(self):
        with tempfile.TemporaryDirectory() as d:
            p = Presets(d)
            for index, name in enumerate(NAMES):
                p.save(name, {'threads': index + 2})
            fresh = Presets(d)
            for index, name in enumerate(NAMES):
                self.assertEqual(fresh.load(name, current(), hardware(), [])['threads'], index + 2)
            fresh.save('Shared', {'threads': 9})
            self.assertEqual(Presets(d).profiles['Comp focused']['threads'], 3)
            self.assertFalse((Path(d) / 'preferences17.1.nk').exists())
    def test_defaults_and_user_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            p = Presets(d)
            self.assertEqual(p.load('Comp focused', current(), hardware(), [])['threads'], 16)
            self.assertEqual(p.load('Shared', current(), hardware(), [])['threads'], 12)
            self.assertEqual(p.load('User preset', current(), hardware(), []), current())
    def test_external_edit_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Presets(d), Presets(d)
            a.save('Shared', {'threads': 4})
            with self.assertRaises(RuntimeError): b.save('Shared', {'threads': 3})
            self.assertEqual(Presets(d).profiles['Shared']['threads'], 4)
    def test_invalid_and_unknown_values(self):
        with tempfile.TemporaryDirectory() as d:
            p = Presets(d)
            for v in [float('nan'), float('inf'), -1, True, '8']:
                with self.assertRaises(ValueError): p.save('Shared', {'threads': v})
            p.save('Shared', {'threads': 4, 'unrelated': 9})
            self.assertNotIn('unrelated', p.profiles['Shared'])
    def test_missing_mapping_is_not_added(self):
        with tempfile.TemporaryDirectory() as d:
            p = Presets(d); p.save('Shared', {'threads': 4, 'workers': 2})
            self.assertNotIn('workers', p.load('Shared', {'threads': 16}, hardware(), []))

class BudgetTests(unittest.TestCase):
    def test_focused_exposes_all_cpu_on_small_and_large_systems(self):
        for cpus in [1, 2, 16, 32, 128]:
            h = hardware(); h['logical_cpus'] = cpus
            self.assertEqual(recommendations(h, current(), [], 'Comp focused')[0]['threads'], cpus)
    def test_joint_cache_and_noncache_reserves(self):
        for ram in [2, 8, 16, 32, 96, 512]:
            h = hardware(); h['ram_gb'] = ram
            values, _ = recommendations(h, current(), [], 'Comp focused')
            if 'comp_pct' in values:
                budget = ram * (values['comp_pct'] + values.get('timeline_pct', 5)) / 100
                self.assertLessEqual(budget + max(4, ram * .1) * 2, ram + 1e-8)
    def test_focused_does_not_max_out_blink(self):
        values, _ = recommendations(hardware(), current(), [current()['gpu']], 'Comp focused')
        self.assertEqual(values['blink_pct'], 40)
        self.assertEqual(values['texture_mb'] % 128, 0)
        self.assertLess(values['texture_mb'] / 1024 + 16 * values['blink_pct'] / 100, 16)
    def test_disk_budgets_scale_and_leave_reserve(self):
        for free in [0, 10, 50, 400, 900]:
            h = hardware(); h['disk']['free_gb'] = free
            values, _ = recommendations(h, current(), [], 'Comp focused')
            total = values.get('disk_gb', 0) + values.get('paint_disk_gb', 0)
            self.assertLessEqual(total, max(0, free - 100) * .8)
    def test_unknown_worker_cost_does_not_guess_process_count(self):
        self.assertNotIn('workers', recommendations(hardware(), current(), [], 'Comp focused')[0])
    def test_user_auto_is_noop(self):
        self.assertEqual(recommendations(hardware(), current(), [], 'User preset')[0], {})
