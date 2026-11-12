import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class InstallerTests(unittest.TestCase):
    def test_install_then_uninstall_preserves_existing_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); init = root / 'init.py'
            old = '# Existing pipeline configuration\nanswer = 42\n'
            init.write_text(old, encoding='utf-8')
            nuke = types.SimpleNamespace(message=lambda message: None)
            with patch.dict(os.environ, {'NPA_NUKE_DIR': directory}), patch.dict(sys.modules, {'nuke': nuke}):
                script = Path('install.py').resolve()
                exec(compile(script.read_text(), str(script), 'exec'), {})
                installed = init.read_text()
                self.assertTrue(installed.startswith(old))
                self.assertIn('nuke.pluginAddPath', installed)
                with self.assertRaises(RuntimeError):
                    exec(compile(script.read_text(), str(script), 'exec'), {})
                self.assertEqual(init.read_text(), installed)
                script = Path('uninstall.py').resolve()
                exec(compile(script.read_text(), str(script), 'exec'), {})
                self.assertEqual(init.read_text().strip(), old.strip())
                self.assertTrue(list(root.glob('init.py.npa-backup-*')))
