"""Names/classes/labels from a native Nuke 15.1v2 diagnostic.
Numeric values below are synthetic fixtures, not measured user values.
"""
import unittest
from test_core import Knob, Prefs, FakeNuke
from nuke_performance_assistant.specs import discover

OBSERVED = (
 ('FrameServerRenderTimeout', 'Array_Knob', 'FrameServerRenderTimeout', 1),
 ('BlinkCacheMemoryPercentage', 'Array_Knob', 'blink cache memory percentage', 50),
 ('CacheLimit', 'Array_Knob', 'cache memory usage (%)', 90),
 ('DisableBlinkCache', 'Boolean_Knob', 'disable blink cache', False),
 ('DiskCachePath', 'File_Knob', 'disk cache', '/tmp'),
 ('PaintCacheGB', 'Array_Knob', 'paint disk cache size (GB)', 100),
 ('PaintCacheLimit', 'Array_Knob', 'nuke memory available for paint (%)', 90),
 ('PlaybackLimit', 'Array_Knob', 'playback cache memory (%)', 50),
 ('RenderWithFrameServer', 'Boolean_Knob', '', False),
 ('diskCacheGB', 'Array_Knob', 'disk cache size (GB)', 100),
 ('selectedGPUDeviceIndex', 'Enumeration_Knob', 'GPU Device', 'NVIDIA GeForce RTX 4070 Ti SUPER'),
 ('selectedGPUDeviceName', 'EvalString_Knob', '', 'NVIDIA GeForce RTX 4070 Ti SUPER'),
 ('selectedGPUDeviceNum', 'Array_Knob', '', 0),
 ('viewer_texture_vram', 'Array_Knob', 'gpu texture cache memory (Mb)', 1000),
 ('TimelineDiskCacheLimit', 'Array_Knob', 'limit to (GB)', 10),
 ('TimelineDiskCachePath', 'File_Knob', 'timeline disk cache', '/other'),
 ('RAMCacheFrameColor', 'ColorChip_Knob', 'RAM cached frames', 0),
)


def fixture():
    return Prefs({name: Knob(label, value, cls) for name, cls, label, value in OBSERVED})


class Nuke15MappingTests(unittest.TestCase):
    def test_all_twelve_observed_controls_are_mapped(self):
        found, missing = discover(fixture())
        self.assertEqual(len(found), 12)
        self.assertEqual(set(missing), {'workers', 'timeline_pct'})
        self.assertEqual(found['gpu'][0], 'selectedGPUDeviceIndex')
        self.assertEqual(found['comp_pct'][0], 'CacheLimit')
        self.assertEqual(found['playback_pct'][0], 'PlaybackLimit')
        self.assertEqual(found['cache_path'][0], 'DiskCachePath')
    def test_timeline_disk_and_colors_are_not_mistaken_for_comp(self):
        found, _ = discover(fixture())
        names = {name for name, knob in found.values()}
        self.assertNotIn('TimelineDiskCacheLimit', names)
        self.assertNotIn('RAMCacheFrameColor', names)
        self.assertNotIn('selectedGPUDeviceNum', names)
    def test_vector_array_is_not_accepted(self):
        prefs = fixture(); prefs._knobs['CacheLimit'].arraySize = lambda: 3
        found, missing = discover(prefs)
        self.assertNotIn('comp_pct', found)
        self.assertIn('type/shape', missing['comp_pct'])
    def test_known_id_precedes_duplicate_display_label(self):
        prefs = fixture(); prefs._knobs['custom'] = Knob('comp cache size (%)', 42)
        found, _ = discover(prefs)
        self.assertEqual(found['comp_pct'][0], 'CacheLimit')
    def test_known_id_wrong_class_is_not_replaced_with_guess(self):
        prefs = fixture(); prefs._knobs['CacheLimit'].cls = 'ColorChip_Knob'
        prefs._knobs['custom'] = Knob('comp cache size (%)', 42)
        found, _ = discover(prefs)
        self.assertNotIn('comp_pct', found)

class Native15SaveTests(unittest.TestCase):
    def test_observed_scalar_controls_roundtrip_and_metadata_untouched(self):
        import tempfile
        import os
        from unittest.mock import patch
        from test_core import hardware
        from nuke_performance_assistant.backend import Controller
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'NPA_NUKE_DIR': directory}):
            nuke = FakeNuke()
            nuke.NUKE_VERSION_MAJOR, nuke.NUKE_VERSION_MINOR = 15, 1
            nuke.NUKE_VERSION_RELEASE = 2
            nuke.prefs = fixture()
            h = hardware(); h['ram_gb'] = 128
            control = Controller(nuke)
            before = control.current()
            proposed = {'threads': 12, 'comp_pct': 42, 'texture_mb': 982,
                        'blink_pct': 25, 'paint_pct': 50, 'disk_gb': 30,
                        'paint_disk_gb': 10}
            with patch('nuke_performance_assistant.backend.disk_info', return_value={'free_gb': 174.2}):
                control.apply(proposed, h, ['texture_mb'], 'Shared', warnings_accepted=True)
                fresh = Controller(nuke)
                self.assertEqual(fresh.state['locks'], ['texture_mb'])
                for key, value in proposed.items():
                    self.assertEqual(fresh.current()[key], value)
                self.assertEqual(nuke.prefs._knobs['selectedGPUDeviceNum'].value(), 0)
                self.assertEqual(nuke.prefs._knobs['TimelineDiskCacheLimit'].value(), 10)
                errors, warnings = fresh.check(fresh.state['previous'], h, restoring=True)
                self.assertFalse(errors)
                self.assertTrue(any('147.20 GiB requested / 128.00 GiB available' in w for w in warnings))
                with self.assertRaisesRegex(ValueError, 'Review warnings before applying'):
                    fresh.apply(fresh.state['previous'], h, [], 'Shared', restoring=True)
                self.assertEqual(fresh.current()['comp_pct'], 42)
                fresh.apply(fresh.state['previous'], h, [], 'Shared', warnings_accepted=True, restoring=True)
                self.assertEqual(fresh.current(), before)
