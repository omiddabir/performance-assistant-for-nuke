"""Run in Nuke's Script Editor with exec(compile(open(PATH).read(), PATH, 'exec'))."""
import os
from pathlib import Path
import nuke

# Locate this file when executed with compile(filename=...).
import inspect
source = Path(inspect.currentframe().f_code.co_filename).resolve().parent
if not (source / 'nuke_performance_assistant' / '__init__.py').is_file():
    raise RuntimeError('Run install.py using compile with its actual absolute file path.')
directory = Path(os.environ.get('NPA_NUKE_DIR', str(Path.home() / '.nuke'))).expanduser()
directory.mkdir(parents=True, exist_ok=True)
path = directory / 'init.py'
start, end = '# BEGIN NUKE PERFORMANCE ASSISTANT', '# END NUKE PERFORMANCE ASSISTANT'
line = 'nuke.pluginAddPath({!r})'.format(source.as_posix())
block = '\n{}\nimport nuke\n{}\n{}\n'.format(start, line, end)
old = path.read_text(encoding='utf-8') if path.exists() else ''
if start in old:
    raise RuntimeError('Already installed. Edit the existing marked block if moving the folder.')
# Do not rewrite a non-UTF8 startup file or a syntactically broken file.
compile(old + block, str(path), 'exec')
from importlib.util import spec_from_file_location, module_from_spec
spec = spec_from_file_location('npa_install_storage', str(source / 'nuke_performance_assistant' / 'storage.py'))
module = module_from_spec(spec)
spec.loader.exec_module(module)
if path.exists():
    import time
    backup = directory / ('init.py.npa-backup-' + time.strftime('%Y%m%d-%H%M%S'))
    if backup.exists():
        raise RuntimeError('Backup already exists; retry later.')
    module.atomic_write(backup, path.read_bytes())
module.atomic_write(path, (old + block).encode('utf-8'))
nuke.message('Performance Assistant 0.6.0-preview installed. Keep the extracted folder in this location and restart Nuke.\nTools > Performance Assistant')
