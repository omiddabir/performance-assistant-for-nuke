"""Real Qt widgets with simulated Nuke backend; not native Nuke certification."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
import importlib
import unittest
from unittest.mock import patch
from test_core import FakeNuke, hardware
try:
    from PySide6 import QtWidgets
except ImportError:
    QtWidgets = None

@unittest.skipIf(QtWidgets is None, 'Optional Qt test runtime is not installed')
class QtPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.nuke = FakeNuke(); self.messages = []
        self.nuke.message = self.messages.append; self.nuke.ask = lambda s: True
        self.mods = patch.dict(sys.modules, {'nuke': self.nuke}); self.mods.start(); self.addCleanup(self.mods.stop)
        self.env = patch.dict(os.environ, {'NPA_NUKE_DIR': self.tmp.name}); self.env.start(); self.addCleanup(self.env.stop)
        sys.modules.pop('nuke_performance_assistant.ui', None)
        self.ui = importlib.import_module('nuke_performance_assistant.ui')
        h = hardware(); h.update(os='Windows', cpu='Test CPU', physical_cores=8, warnings=[])
        with patch.object(self.ui, 'detect', return_value=h): self.panel = self.ui.AssistantPanel()
        self.addCleanup(self.panel.deleteLater)
    def drain(self): self.app.processEvents()
    def test_compact_tabs_footer_and_tooltips(self):
        self.assertEqual([self.panel.tabs.tabText(i) for i in range(self.panel.tabs.count())], ['Home','CPU','GPU','Cache','Frame Server'])
        self.assertFalse(hasattr(self.panel, 'locks'))
        for field in self.panel.fields.values(): self.assertTrue(field.toolTip())
        self.assertFalse(hasattr(self.panel, 'cpu_input'))
        self.assertIn('GiB', self.panel.hardware_labels['ram'].text())
    def test_edit_save_reopen_all_profiles_without_native_write(self):
        for name, count in [('Shared', 7), ('Comp focused', 14), ('User preset', 5)]:
            self.panel.mode.setCurrentText(name)
            self.panel.fields['threads'].setValue(count)
            self.panel._save_preset()
        from nuke_performance_assistant.presets import Presets
        profiles = Presets(self.panel.control.store.folder)
        self.assertEqual(profiles.profiles['Shared']['threads'], 7)
        self.assertEqual(profiles.profiles['Comp focused']['threads'], 14)
        self.assertEqual(profiles.profiles['User preset']['threads'], 5)
        self.assertFalse(self.panel.control.store.native.exists())
    def test_switch_retains_unsaved_drafts(self):
        self.panel.fields['threads'].setValue(7)
        self.panel.mode.setCurrentText('Comp focused')
        self.panel.mode.setCurrentText('Shared')
        self.assertEqual(self.panel.fields['threads'].value(), 7)
    def test_deferred_apply_then_restore(self):
        self.nuke.executing = lambda: True
        self.panel._apply()
        self.assertFalse(self.panel.control.store.native.exists())
        self.nuke.executing = lambda: False
        self.drain()
        self.assertTrue(self.panel.control.store.native.exists(), self.messages)
        self.panel._restore(); self.drain()
        self.assertEqual(self.nuke.env['threads'], 16)
    def test_cancel_save_confirmation_no_changes(self):
        self.nuke.ask = lambda s: False
        self.panel._apply(); self.drain()
        self.assertFalse(self.panel.control.store.native.exists())
        self.assertTrue(self.panel.isEnabled())
    def test_busy_execution_still_blocks_write(self):
        self.nuke.executing = lambda: True
        self.panel._apply(); self.drain()
        self.assertFalse(self.panel.control.store.native.exists())
        self.assertIn('rendering', self.messages[-1])
    def test_double_apply_is_single_save(self):
        with patch.object(self.panel.control, 'apply', wraps=self.panel.control.apply) as apply:
            self.panel._apply(); self.panel._apply(); self.drain()
            self.assertEqual(apply.call_count, 1)
    def test_user_auto_disabled_and_focused_full_threads(self):
        self.panel.mode.setCurrentText('User preset')
        self.assertFalse(self.panel.auto.isEnabled())
        self.panel.mode.setCurrentText('Comp focused')
        self.panel.fields['threads'].setValue(5)
        self.panel._auto()
        self.assertEqual(self.panel.fields['threads'].value(), 16)

    def test_diagnostic_dialog_is_save_mode_with_json_suffix(self):
        from unittest.mock import MagicMock
        import json
        from pathlib import Path
        target = Path(self.tmp.name) / 'diagnostic.json'
        dialog = MagicMock()
        dialog.exec_.return_value = self.ui.QtWidgets.QDialog.Accepted
        dialog.selectedFiles.return_value = [str(target)]
        cls = self.ui.QtWidgets.QFileDialog
        with patch.object(self.ui.QtWidgets, 'QFileDialog', return_value=dialog) as factory:
            factory.AcceptSave, factory.AnyFile = cls.AcceptSave, cls.AnyFile
            self.panel._export()
        dialog.setAcceptMode.assert_called_once_with(cls.AcceptSave)
        dialog.setDefaultSuffix.assert_called_once_with('json')
        self.assertEqual(json.loads(target.read_text())['tool'], '0.5.2-preview')
        self.assertFalse(self.panel.control.store.native.exists())

    def test_diagnostic_cancel_does_not_write(self):
        from unittest.mock import MagicMock
        from pathlib import Path
        target = Path(self.tmp.name) / 'diagnostic.json'
        dialog = MagicMock(); dialog.exec_.return_value = self.ui.QtWidgets.QDialog.Rejected
        dialog.selectedFiles.return_value = [str(target)]
        with patch.object(self.ui.QtWidgets, 'QFileDialog', return_value=dialog):
            self.panel._export()
        self.assertFalse(target.exists())

    def test_custom_profile_create_rename_delete_and_estimate(self):
        from nuke_performance_assistant.presets import Presets
        self.panel.worker_ram.setValue(12)
        with patch.object(self.ui.QtWidgets.QInputDialog, 'getText', return_value=('My comp', True)):
            self.panel._new_preset()
        self.assertEqual(self.panel.current_name, 'My comp')
        self.assertFalse(self.panel.auto.isEnabled())
        self.assertEqual(Presets(self.panel.control.store.folder).planning['My comp'], 12)
        with patch.object(self.ui.QtWidgets.QInputDialog, 'getText', return_value=('My render', True)):
            self.panel._rename_preset()
        self.assertNotIn('My comp', self.panel.presets.names())
        self.panel._delete_preset()
        self.assertNotIn('My render', self.panel.presets.names())
        self.assertFalse(self.panel.control.store.native.exists())

    def test_stale_preset_value_visible_and_apply_rejected(self):
        self.panel.presets.save('Other machine', {'threads': 32})
        self.panel.mode.addItem('Other machine')
        self.panel.mode.setCurrentText('Other machine')
        self.assertEqual(self.panel.fields['threads'].value(), 32)
        self.assertIn('16', self.panel.max_labels['threads'].text())
        self.panel._apply(); self.drain()
        self.assertFalse(self.panel.control.store.native.exists())
        self.assertIn('exceeds', self.messages[-1])

    def test_hardware_readonly_precise_and_auto_no_confirmation(self):
        self.panel.hardware['ram_gb'] = 93.6472549
        self.panel._refresh_hardware()
        self.assertEqual(self.panel._hw()['ram_gb'], 93.6472549)
        self.assertEqual(self.panel.hardware_labels['ram'].text(), '93.6 GiB')
        self.assertFalse(hasattr(self.panel, 'ram_input'))
        self.panel.fields['threads'].setValue(5)
        before = self.panel._values()
        with patch.object(self.nuke, 'ask', side_effect=AssertionError('No auto confirmation allowed')):
            self.panel._auto()
        self.assertEqual(self.panel.fields['threads'].value(), 12)
        self.assertFalse(self.panel.control.store.native.exists())
        self.panel._undo_auto()
        self.assertEqual(self.panel._values(), before)

    def test_noop_ok_closes_without_save_or_confirmation(self):
        self.panel._put(self.panel.control.current())
        with patch.object(self.nuke, 'ask', side_effect=AssertionError('No changes')):
            self.panel._apply(close=True); self.drain()
        self.assertFalse(self.panel.control.store.native.exists())
        self.assertEqual(self.panel.result(), self.ui.QtWidgets.QDialog.Accepted)

    def test_unknown_gpu_does_not_inherit_old_vram(self):
        from nuke_performance_assistant.policy import gpu_vram
        self.panel.hardware['gpus'] = [{'name':'GPU A','vram_gb':15.9921875}]
        self.panel._refresh_hardware()
        self.assertEqual(gpu_vram('GPU A',self.panel._hw()),15.9921875)
        self.assertIsNone(gpu_vram('GPU B',self.panel._hw()))
