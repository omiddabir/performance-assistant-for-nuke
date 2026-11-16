"""Run inside Nuke using compile(path). Removes installation hook only."""
import os
import time
from pathlib import Path
import nuke
from nuke_performance_assistant.storage import atomic_write

root = Path(os.environ.get('NPA_NUKE_DIR', str(Path.home() / '.nuke'))).expanduser()
file = root / 'init.py'
start, end = '# BEGIN NUKE PERFORMANCE ASSISTANT', '# END NUKE PERFORMANCE ASSISTANT'
text = file.read_text(encoding='utf-8')
if text.count(start) != 1 or text.count(end) != 1:
    raise RuntimeError('Expected exactly one installer block. For a manual install, remove only its pluginAddPath line.')
a, b = text.index(start), text.index(end) + len(end)
if b <= a:
    raise RuntimeError('Malformed installer block. No changes made.')
updated = text[:a] + text[b:]
compile(updated, str(file), 'exec')
backup = root / ('init.py.npa-uninstall-backup-' + time.strftime('%Y%m%d-%H%M%S'))
if backup.exists():
    raise RuntimeError('Backup already exists; retry later.')
atomic_write(backup, file.read_bytes())
atomic_write(file, updated.encode('utf-8'))
nuke.message('Performance Assistant 0.6.0-preview installation hook removed. Restart Nuke.\nSaved native preferences and backups remain.\nUse Restore Previous Settings before uninstalling if you want to revert changes.')
