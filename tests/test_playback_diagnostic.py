import sys
import types
import unittest
from unittest.mock import patch
from nuke_performance_assistant.frame_diagnostic import playback_diagnostic

class PlaybackDiagnosticTests(unittest.TestCase):
    def test_api_is_described_without_calling_it(self):
        called=[]
        def setCacheMemory(value):
            called.append(value)
        core=types.ModuleType('hiero.core')
        core.setCacheMemory=setCacheMemory
        with patch.dict(sys.modules, {'hiero.core':core}), patch('inspect.getsource', side_effect=OSError()):
            result=playback_diagnostic()
        self.assertFalse(called)
        self.assertTrue(any(x['name']=='setCacheMemory' for x in result['api']))
    def test_only_numeric_cache_settings_are_reported(self):
        class Settings:
            def allKeys(self): return ['cache/percent','cache/path','user/password','memory/limit']
            def value(self,key): return {'cache/percent':'10','cache/path':'C:/private','user/password':'123','memory/limit':'nan'}[key]
        app=types.SimpleNamespace(organizationName=lambda:'Foundry', applicationName=lambda:'Nuke')
        qt=types.SimpleNamespace(QCoreApplication=types.SimpleNamespace(instance=lambda:app), QSettings=Settings)
        with patch.dict(sys.modules, {'PySide6.QtCore':qt}), patch('inspect.getsource',side_effect=OSError()):
            result=playback_diagnostic()
        self.assertEqual(result['qt_numeric_cache_settings'], [{'key':'cache/percent','value':10.0}])
