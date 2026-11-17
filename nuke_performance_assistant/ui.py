"""Compact native-styled Qt dialog. No external runtime dependencies in Nuke."""
import os
import copy
import math
import nuke
if nuke.NUKE_VERSION_MAJOR >= 16:
    from PySide6 import QtCore, QtWidgets
else:
    from PySide2 import QtCore, QtWidgets
from .backend import Controller
from .hardware import detect, disk_info
from .policy import recommendations, gpu_vram
from .presets import Presets, NAMES
from .specs import SPECS, normalized
from .limits import ceilings, check_limits
from .presentation import format_value, change_summary, equivalent


class AssistantPanel(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(AssistantPanel, self).__init__(parent)
        self.setWindowTitle('Performance Assistant 0.6.0-preview')
        self.resize(860, 640)
        self.control = Controller(nuke)
        self.presets = Presets(self.control.store.folder)
        self.hardware = detect(self.control.cache_path())
        self.fields, self.current_labels, self.drafts = {}, {}, {}
        self.max_labels = {}
        self.worker_drafts = {}
        self.busy, self.pending, self.closed = True, False, False
        self.current_name = self.presets.selected
        layout = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs)
        home = QtWidgets.QWidget()
        home_layout = QtWidgets.QVBoxLayout(home)
        self.tabs.addTab(home, 'Home')
        system_box = QtWidgets.QGroupBox('Detected system')
        system_layout = QtWidgets.QVBoxLayout(system_box)
        self.summary = QtWidgets.QLabel()
        self.summary.setTextFormat(QtCore.Qt.PlainText)
        self.summary.setWordWrap(True)
        system_layout.addWidget(self.summary)
        self.hardware_labels = {}
        grid = QtWidgets.QFormLayout()
        for key, title in [('cpu','CPU'), ('cores','Cores / threads'), ('ram','Usable RAM'), ('available','Available RAM at scan'), ('gpu','Selected device'), ('vram','Dedicated VRAM'), ('disk','Free cache disk')]:
            label = QtWidgets.QLabel(); label.setTextFormat(QtCore.Qt.PlainText); label.setWordWrap(True)
            self.hardware_labels[key] = label; grid.addRow(title, label)
        system_layout.addLayout(grid)
        home_layout.addWidget(system_box)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel('Preset'))
        self.mode = QtWidgets.QComboBox(); self.mode.addItems(self.presets.names())
        self.mode.setCurrentText(self.current_name)
        self.mode.setToolTip('Load an editable preset; nothing is applied yet.')
        row.addWidget(self.mode, 1)
        self.save_preset_button = self._button('Save preset', 'Save these values to the selected preset only.', self._save_preset)
        row.addWidget(self.save_preset_button)
        row.addWidget(self._button('New', 'Save a new local preset from these values.', self._new_preset))
        manage = QtWidgets.QPushButton('Manage')
        manage.setAutoDefault(False)
        manage.setToolTip('Rename or delete custom presets.')
        menu = QtWidgets.QMenu(manage)
        self.rename_action = menu.addAction('Rename custom preset')
        self.delete_action = menu.addAction('Delete custom preset')
        self.rename_action.triggered.connect(lambda: self._safe(self._rename_preset))
        self.delete_action.triggered.connect(lambda: self._safe(self._delete_preset))
        manage.setMenu(menu); row.addWidget(manage)
        home_layout.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.auto = self._button('Auto configure', 'Recalculate this preset from hardware; replaces staged edits.', self._auto)
        row.addWidget(self.auto)
        row.addWidget(self._button('Scan system', 'Refresh detected hardware; leave staged values unchanged.', self._scan))
        self.undo_auto = self._button('Undo auto', 'Restore the values staged before Auto configure.', self._undo_auto)
        self.undo_auto.setEnabled(False); row.addWidget(self.undo_auto); row.addStretch()
        self.auto_snapshot = None
        home_layout.addLayout(row)
        self.worker_ram = QtWidgets.QDoubleSpinBox(); self.worker_ram.setRange(.25, 65536)
        self.worker_ram_confirmed = self.presets.confirmed.get(self.current_name, False)
        self.worker_ram.setValue(self.presets.planning.get(self.current_name, 8))
        self.worker_ram.setToolTip('Estimated peak RAM per worker, including nodes and caches. Replace 8 GiB with a measured peak.')
        self.review_title = QtWidgets.QLabel('Pending changes')
        home_layout.addWidget(self.review_title)
        self.review = QtWidgets.QPlainTextEdit()
        self.review.setReadOnly(True)
        self.review.setToolTip('Pending changes: current value to proposed value.')
        home_layout.addWidget(self.review, 1)
        current = self.control.current()
        for group in ('CPU', 'GPU', 'Cache', 'Frame Server'):
            page = QtWidgets.QWidget(); form = QtWidgets.QFormLayout(page)
            form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
            for spec in (s for s in SPECS if s.group == group):
                if spec.key not in current:
                    field = QtWidgets.QLabel('Set in Nuke Preferences' if spec.key == 'timeline_pct' else 'Unavailable')
                    field.setToolTip(self.control.unavailable.get(spec.key, 'Not exposed by this Nuke build.'))
                    form.addRow(spec.title, field)
                    continue
                field = self._make_field(spec)
                tip = spec.help + (' Restart required.' if spec.restart else '')
                field.setToolTip(tip)
                label = QtWidgets.QLabel(spec.title); label.setToolTip(tip)
                wrap = QtWidgets.QWidget(); line = QtWidgets.QHBoxLayout(wrap)
                line.setContentsMargins(0, 0, 0, 0); line.addWidget(field, 1)
                if spec.kind == 'path':
                    line.addWidget(self._button('Browse', 'Choose an existing cache folder.', self._browse_cache))
                current_label = QtWidgets.QLabel('Current folder' if spec.kind == 'path' else 'Current: ' + format_value(current[spec.key]))
                current_label.setToolTip(str(current[spec.key]) if spec.kind == 'path' else 'Value currently loaded in Nuke.')
                line.addWidget(current_label)
                if spec.kind in ('int', 'float'):
                    maximum_label = QtWidgets.QLabel()
                    line.addWidget(maximum_label); self.max_labels[spec.key] = maximum_label
                self.current_labels[spec.key] = current_label
                form.addRow(label, wrap)
                self.fields[spec.key] = field
                self._set_value(spec.key, current[spec.key])
            if group == 'Frame Server':
                form.addRow('RAM per worker (GiB, estimate)', self.worker_ram)
                self.worker_estimate_state = QtWidgets.QLabel()
                form.addRow(self.worker_estimate_state)
                hint = QtWidgets.QLabel('Render a representative shot with one worker. Monitor its peak RAM in Task Manager, then enter that peak with headroom.')
                hint.setWordWrap(True)
                form.addRow(hint)
                note = QtWidgets.QLabel('Focus and export render limits: use Nuke Preferences.')
                note.setWordWrap(True)
                note.setToolTip('These mappings are not verified in this preview; they are left unchanged.')
                form.addRow(note)
            if group in ('Cache', 'Frame Server'):
                form.addRow(self._button('Open Nuke Preferences…', 'Close this preview and edit the native controls.', self._native_preferences))
            scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(page)
            self.tabs.addTab(scroll, group)
        self.status = QtWidgets.QLabel('Not applied.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        footer = QtWidgets.QHBoxLayout()
        self.export_button = self._button('Diagnostics', 'Export local diagnostics; nothing is uploaded.', self._export)
        footer.addWidget(self.export_button)
        footer.addStretch()
        self.restore_button = self._button('Restore', 'Restore the last applied changes; presets stay saved.', self._restore)
        self.apply_button = self._button('Apply', 'Apply and persist values in Nuke; does not save the preset.', self._apply)
        self.ok_button = self._button('OK', 'Apply values and close.', lambda: self._apply(close=True))
        self.cancel_button = self._button('Cancel', 'Close without applying; completed saves are kept.', self.reject)
        for button in (self.restore_button, self.apply_button, self.ok_button, self.cancel_button):
            footer.addWidget(button)
        layout.addLayout(footer)
        self._refresh_hardware()
        self._put(self.presets.load(self.current_name, current, self._hw(), self.control.devices()))
        self.mode.currentTextChanged.connect(self._switch)
        self.busy = False
        for field in (self.worker_ram,):
            field.valueChanged.connect(self._worker_edited)
            field.lineEdit().textEdited.connect(self._worker_edited)
        self._refresh_review()
        if self.control.loaded_differences():
            self.status.setText('Loaded settings differ from the last save. Review before applying.')

    def _worker_edited(self, value):
        if self.busy: return
        self.worker_ram_confirmed = True
        self._refresh_review()

    def _load_worker_estimate(self, name):
        self.worker_ram.blockSignals(True)
        peak, confirmed = self.worker_drafts.get(name, (self.presets.planning.get(name, 8), self.presets.confirmed.get(name, False)))
        self.worker_ram.setValue(peak)
        self.worker_ram.blockSignals(False)
        self.worker_ram_confirmed = confirmed

    def _button(self, text, tip, action):
        button = QtWidgets.QPushButton(text)
        button.setAutoDefault(False); button.setToolTip(tip)
        button.clicked.connect(lambda checked=False: self._safe(action))
        return button

    def _safe(self, action):
        try:
            action()
        except Exception as exc:
            self.status.setText(str(exc))
            nuke.message('Performance Assistant: ' + str(exc))

    def _make_field(self, spec):
        if spec.kind == 'enum':
            field = QtWidgets.QComboBox(); field.addItems(self.control.devices())
            field.currentTextChanged.connect(lambda text, key=spec.key: self._edited(key))
        elif spec.kind == 'bool':
            field = QtWidgets.QCheckBox()
            field.toggled.connect(lambda value, key=spec.key: self._edited(key))
        elif spec.kind == 'path':
            field = QtWidgets.QLineEdit()
            field.textChanged.connect(lambda text, key=spec.key: self._edited(key))
        else:
            field = QtWidgets.QSpinBox() if spec.kind == 'int' else QtWidgets.QDoubleSpinBox()
            field.setRange(spec.low, spec.high) if spec.kind != 'int' else field.setRange(int(spec.low), int(spec.high))
            if spec.kind == 'float': field.setDecimals(2)
            field.setKeyboardTracking(False)
            field.valueChanged.connect(lambda value, key=spec.key: self._edited(key))
        return field

    def _set_value(self, key, value):
        field = self.fields[key]
        override = {'disk_gb': 'NUKE_DISK_CACHE_GB', 'cache_path': 'NUKE_DISK_CACHE'}.get(key)
        if override and os.environ.get(override):
            value = self.control.current()[key]
            field.setEnabled(False)
            field.setToolTip(override + ' is set for this session.')
        spec = next(s for s in SPECS if s.key == key)
        if spec.kind == 'enum':
            if field.findText(value) < 0:
                field.addItem(value)  # Show stale preset value; validation prevents applying it.
            field.setCurrentText(value)
        elif spec.kind == 'bool': field.setChecked(value)
        elif spec.kind == 'path': field.setText(value)
        else:
            # Preserve legacy/preset values outside a new budget for explicit review.
            if value > field.maximum(): field.setMaximum(value)
            field.setValue(value)

    def _values(self):
        result = {}
        for spec in SPECS:
            if spec.key not in self.fields: continue
            field = self.fields[spec.key]
            if spec.kind == 'enum': value = field.currentText()
            elif spec.kind == 'bool': value = field.isChecked()
            elif spec.kind == 'path': value = field.text()
            else: value = field.value()
            result[spec.key] = value
        return result

    def _put(self, values):
        previous_busy = self.busy; self.busy = True
        try:
            for key, value in values.items():
                if key in self.fields: self._set_value(key, value)
        finally:
            self.busy = previous_busy

    def _refresh_hardware(self):
        self.summary.setText(self.hardware.get('os', 'System') + ' • Read-only hardware detection')
        self.summary.setToolTip('Only the display is rounded. Calculations use the full detected precision.')
        self._refresh_vram()

    def _refresh_vram(self):
        hw = self.hardware
        def memory(value):
            return 'Unknown' if value is None else '{:.1f} GiB'.format(value)
        device = self._values().get('gpu', '')
        labels = dict(cpu=hw.get('cpu', 'Unknown'),
                      cores='{} physical / {} logical'.format(hw.get('physical_cores') or 'Unknown', hw['logical_cpus']),
                      ram=memory(hw.get('ram_gb')), available=memory(hw.get('available_gb')),
                      gpu=device or 'Unknown', vram=memory(gpu_vram(device, hw)),
                      disk=memory(hw.get('disk', {}).get('free_gb')))
        for key, value in labels.items(): self.hardware_labels[key].setText(value)
        self.hardware_labels['ram'].setToolTip('Usable RAM reported by the OS; may be lower than installed module capacity.')
        self.hardware_labels['vram'].setToolTip('Dedicated memory matched to the selected device. Shared system RAM is not VRAM.')
        self.summary.setToolTip('\n'.join(hw.get('warnings', [])) or 'Display rounded; calculations use full detected precision.')

    def _hw(self):
        hw = copy.deepcopy(self.hardware)
        hw['worker_ram_gb'] = self.worker_ram.value()
        hw['worker_ram_confirmed'] = self.worker_ram_confirmed
        hw['disk'] = disk_info(self.control.cache_path(self._values().get('cache_path')))
        return hw

    def _refresh_review(self):
        values = self._values()
        hw = self._hw()
        limits = ceilings(hw, values)
        self.worker_estimate_state.setText('User-confirmed estimate' if self.worker_ram_confirmed else 'Unconfirmed estimate — one worker maximum')
        for key, label in self.max_labels.items():
            maximum, reason = limits[key]
            label.setText(('Est. max: ' if key == 'workers' else ('Max: ' if key == 'threads' else 'Budget max: ')) + (format_value(maximum) if maximum is not None else '?'))
            if key == 'workers' and not self.worker_ram_confirmed:
                label.setText('unconfirmed estimate: ' + format_value(maximum))
            if key in ('disk_gb', 'paint_disk_gb') and maximum is not None:
                combined = values.get('disk_gb', 0) + values.get('paint_disk_gb', 0)
                label.setText('Both caches: {:g} / {:g} GB'.format(combined, maximum))
                reason += '. Adjust either value before Apply.'
            label.setToolTip(reason)
            if maximum is not None:
                field = self.fields[key]
                field.blockSignals(True)
                field.setMaximum(max(field.minimum(), values[key], int(maximum) if isinstance(field, QtWidgets.QSpinBox) else maximum))
                field.blockSignals(False)
                label.setStyleSheet('color: #d99035;' if (combined if key in ('disk_gb', 'paint_disk_gb') else values[key]) > maximum + .0001 else '')
        changed = {k: v for k, v in values.items() if not equivalent(self.control.current().get(k), v)}
        errors = check_limits(changed, self.control.current(), hw)
        text = change_summary(self.control.current(), values)
        if errors: text += '\n\n' + '\n'.join(errors)
        self.review.setPlainText(text)
        self.review_title.setText('Pending changes ({}){}'.format(len(changed), ' — blocked: review limits' if errors else ''))
        self.apply_button.setEnabled(bool(changed) and not errors)
        self.rename_action.setEnabled(self.current_name not in NAMES)
        self.delete_action.setEnabled(self.current_name not in NAMES)
        free = hw.get('disk', {}).get('free_gb')
        self.hardware_labels['disk'].setText('Unknown' if free is None else '{:.1f} GiB'.format(free))
        self.auto.setEnabled(self.current_name in NAMES[:2])
        self.restore_button.setEnabled(bool(self.control.state.get('previous')))

    def _edited(self, key):
        if self.busy: return
        if key == 'gpu': self._refresh_vram()
        self.status.setText('Edited; not applied. Save preset to keep these edits.')
        self._refresh_review()

    def _switch(self, name):
        if self.busy: return
        self.drafts[self.current_name] = self._values()
        self.worker_drafts[self.current_name] = (self.worker_ram.value(), self.worker_ram_confirmed)
        self.auto_snapshot = None; self.undo_auto.setEnabled(False)
        try:
            self._load_worker_estimate(name)
            values = self.drafts.get(name)
            if values is None:
                values = self.presets.load(name, self.control.current(), self._hw(), self.control.devices())
            self._put(values)
            self.current_name = name
            self._load_worker_estimate(name)
            self._refresh_vram()
            self._refresh_review()
            self.status.setText(name + ' loaded; not applied.')
        except Exception as exc:
            self.mode.blockSignals(True); self.mode.setCurrentText(self.current_name); self.mode.blockSignals(False)
            nuke.message(str(exc))

    def _auto(self):
        if self.current_name not in NAMES[:2]: return
        self.auto_snapshot = self._values()
        self.undo_auto.setEnabled(True)
        inputs = self._values()
        native = self.control.current()
        if self.current_name == 'Comp focused' and inputs.get('gpu') == native.get('gpu'):
            for key in ('texture_mb', 'workers'):
                if key in native and key in inputs:
                    inputs[key] = max(native[key], inputs[key])
        values, reasons = recommendations(self._hw(), inputs, self.control.devices(), self.current_name)
        if 'blocked' in reasons:
            self.last_reasons = reasons
            self._refresh_review()
            self.status.setText(reasons['blocked'])
            return
        old_gpu = self._values().get('gpu')
        self._put(values)
        if self._values().get('gpu') != old_gpu: self._refresh_vram()
        self.last_reasons = reasons
        self.status.setText('Recalculated; not applied or saved to preset.' +
                            (' ' + ' '.join(reasons['blocked_groups'].values()) if reasons.get('blocked_groups') else ''))
        self._refresh_review()

    def _undo_auto(self):
        if self.auto_snapshot is None: return
        self._put(self.auto_snapshot); self.auto_snapshot = None
        self.undo_auto.setEnabled(False); self._refresh_vram(); self._refresh_review()
        self.status.setText('Auto suggestions undone; Nuke settings unchanged.')

    def _save_preset(self):
        values = self._values()
        changed = {k: v for k, v in values.items() if not equivalent(self.control.current().get(k), v)}
        errors, warnings = self.control.check(changed, self._hw())
        if errors: raise ValueError('\n'.join(errors))
        if warnings and not nuke.ask('\n'.join(warnings) + '\nSave preset anyway?'): return
        self.presets.save(self.current_name, values, worker_ram_gb=self.worker_ram.value(), worker_ram_confirmed=self.worker_ram_confirmed)
        self.drafts[self.current_name] = dict(values)
        self.status.setText(self.current_name + ' saved. Nuke settings unchanged.')

    def _reload_names(self, selected):
        self.mode.blockSignals(True)
        self.mode.clear(); self.mode.addItems(self.presets.names())
        self.mode.setCurrentText(selected); self.mode.blockSignals(False)
        self.current_name = selected
        self.auto_snapshot = None; self.undo_auto.setEnabled(False)
        self._refresh_review()

    def _new_preset(self):
        name, ok = QtWidgets.QInputDialog.getText(self, 'New preset', 'Name')
        if not ok: return
        name = name.strip()
        if name in self.presets.names(): raise ValueError('A preset with this name already exists.')
        # Store a snapshot; no native write. Oversized values remain reviewable on load.
        self.presets.save(name, self._values(), worker_ram_gb=self.worker_ram.value(), worker_ram_confirmed=self.worker_ram_confirmed)
        self.drafts[self.current_name] = self._values()
        self._reload_names(name)
        self.status.setText(name + ' saved locally; not applied.')

    def _rename_preset(self):
        old = self.current_name
        if old in NAMES: raise ValueError('Built-in names are kept; use New to make a copy.')
        name, ok = QtWidgets.QInputDialog.getText(self, 'Rename preset', 'Name', text=old)
        if not ok or name.strip() == old: return
        name = name.strip()
        self.presets.rename(old, name)
        self.drafts.pop(old, None)
        self.worker_drafts.pop(old, None)
        self._reload_names(name)
        self.status.setText('Renamed; unsaved field edits still need Save preset.')

    def _delete_preset(self):
        name = self.current_name
        if name in NAMES: raise ValueError('Built-in presets cannot be deleted.')
        if not nuke.ask('Delete preset "{}"?'.format(name)): return
        self.presets.delete(name); self.drafts.pop(name, None)
        self.worker_drafts.pop(name, None)
        self._put(self.presets.load('Shared', self.control.current(), self._hw(), self.control.devices()))
        self._load_worker_estimate('Shared')
        self._reload_names('Shared')
        self.status.setText('Preset deleted; Nuke settings unchanged.')

    def _native_preferences(self):
        menu = nuke.menu('Nuke')
        item = next((item for name in ('Edit/Preferences...', 'Edit/Preferences', 'Edit/Preferences…')
                     for item in [menu.findItem(name)] if item is not None), None)
        if item is None:
            nuke.message('Close the assistant and open Edit > Preferences > Performance.')
            return
        if any(not equivalent(self.control.current().get(k), v) for k, v in self._values().items()):
            if not nuke.ask('Close without applying staged values and open Nuke Preferences?'):
                return
        self.reject()
        QtCore.QTimer.singleShot(0, item.invoke)

    def _browse_cache(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Cache folder', self.control.cache_path())
        if path: self.fields['cache_path'].setText(path)

    def _scan(self):
        self.hardware = detect(self.control.cache_path(self._values().get('cache_path')))
        self._refresh_hardware()
        self._refresh_review()
        self.status.setText('Hardware refreshed. Values unchanged; review highlighted limits.')

    def _restore(self):
        previous = self.control.state.get('previous', {})
        if previous: self._queue(previous, restoring=True)

    def _apply(self, close=False):
        self._queue(self._values(), close=close)

    def _queue(self, values, restoring=False, close=False):
        if self.pending: return
        snapshot, hw, name = dict(values), self._hw(), self.current_name
        self.pending = True
        self.setEnabled(False)
        def run():
            try:
                if self.closed: return
                current = self.control.current()
                changed = {k: v for k, v in snapshot.items() if not equivalent(current.get(k), v)}
                if not changed:
                    self.status.setText('No pending changes.')
                    if close: self.accept()
                    return
                errors, warnings = self.control.check(changed, hw, restoring=restoring)
                if errors: raise ValueError('\n'.join(errors))
                message = change_summary(current, snapshot)
                message += '\n\n' + ('Restore these changes?' if restoring else 'Apply and save Nuke settings?')
                message += '\nOther unsaved Preferences are also saved. Stop background renders first.'
                if warnings: message += '\n' + '\n'.join(warnings)
                if not nuke.ask(message): return
                result = self.control.apply(changed, hw, [], name, warnings_accepted=True, restoring=restoring)
                current = self.control.current(); self._put(current)
                self.auto_snapshot = None; self.undo_auto.setEnabled(False)
                for key, label in self.current_labels.items():
                    if key == 'cache_path':
                        label.setText('Current folder'); label.setToolTip(current[key])
                    else:
                        label.setText('Current: ' + format_value(current[key]))
                self._refresh_review()
                status = 'Saved {} changes.'.format(len(result['changed']))
                if result['restart']: status += ' Restart Nuke.'
                self.status.setText(status)
                nuke.message(status)
                if close: self.accept()
            except Exception as exc:
                self.status.setText(str(exc)); nuke.message('Performance Assistant: ' + str(exc))
            finally:
                self.pending = False
                if not self.closed: self.setEnabled(True)
        try:
            QtCore.QTimer.singleShot(0, run)
        except Exception:
            self.pending = False; self.setEnabled(True); raise

    def _export(self):
        dialog = QtWidgets.QFileDialog(self, 'Save diagnostics')
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        dialog.setFileMode(QtWidgets.QFileDialog.AnyFile)
        dialog.setNameFilter('JSON files (*.json)')
        dialog.setDefaultSuffix('json')
        dialog.selectFile('performance_assistant_diagnostics.json')
        accepted = dialog.exec_() if hasattr(dialog, 'exec_') else dialog.exec()
        if accepted == QtWidgets.QDialog.Accepted and dialog.selectedFiles():
            path = dialog.selectedFiles()[0]
            from .storage import atomic_write, json_bytes
            data = self.control.diagnostic()
            data.update(limits=ceilings(self._hw(), self._values()), hardware=self._hw(), staged=self._values(), preset=self.current_name,
                        reasoning=getattr(self, 'last_reasons', {}))
            from .privacy import redact_diagnostics
            atomic_write(path, json_bytes(redact_diagnostics(data)))
            self.status.setText('Diagnostics saved locally.')

    def reject(self):
        if self.pending: return
        self.closed = True
        super(AssistantPanel, self).reject()

    def showModalDialog(self):
        try:
            return self.exec_() if hasattr(self, 'exec_') else self.exec()
        finally:
            self.closed = True
