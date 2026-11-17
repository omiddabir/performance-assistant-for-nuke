import os
import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_core import hardware, current, FakeNuke
from nuke_performance_assistant.limits import ceilings, check_limits
from nuke_performance_assistant.policy import recommendations
from nuke_performance_assistant.presets import Presets
from nuke_performance_assistant.frame_settings import WorkerSetting, FrameTransaction, discover_worker, KEY
from nuke_performance_assistant.backend import Controller

class LimitsTests(unittest.TestCase):
    def test_cpu_scales(self):
        for count in (1, 8, 32, 128):
            h = hardware(); h['logical_cpus'] = count
            self.assertEqual(ceilings(h, current())['threads'][0], count)
            self.assertTrue(check_limits({'threads': count+1}, current(), h))
    def test_coupled_disk(self):
        h = hardware(); c = current()
        maximum = ceilings(h, c)['disk_gb'][0]
        self.assertAlmostEqual(maximum, (400-100)*1024**3/1e9, places=2)
        self.assertTrue(check_limits({'disk_gb': maximum-1}, c, h))
        self.assertFalse(check_limits({'disk_gb': 100}, c, h))
    def test_gpu_coupled_and_disable(self):
        h = hardware(); c = current(); c['blink_pct'] = 40
        first = ceilings(h,c)['texture_mb'][0]
        c['blink_pct'] = 60
        self.assertLess(ceilings(h,c)['texture_mb'][0], first)
        c['blink_disabled'] = True
        self.assertGreater(ceilings(h,c)['texture_mb'][0], first)
    def test_unknown_gpu_not_fake_capacity(self):
        h=hardware(); h['gpus']=[]
        self.assertIsNone(ceilings(h,current())['texture_mb'][0])
    def test_worker_estimate_and_available_memory(self):
        h=hardware(); h.update(worker_ram_gb=8, available_gb=32)
        c = current(); c.update(comp_pct=25, timeline_pct=5)
        self.assertEqual(ceilings(h,c)['workers'][0], 4)
        h['available_gb']=0
        self.assertEqual(ceilings(h,c)['workers'][0], 0)
    def test_worker_auto_gpu_conservative_cpu_scales(self):
        h=hardware(); h['worker_ram_gb']=8
        self.assertEqual(recommendations(h,current(),[current()['gpu']], 'Comp focused')[0]['workers'],1)
        c=current(); c['gpu']='Use CPU'
        self.assertEqual(recommendations(h,c,['Use CPU'],'Comp focused')[0]['workers'],4)
    def test_no_unrelated_legacy_clamping(self):
        self.assertFalse(check_limits({'threads':8},current(),hardware()))
        self.assertTrue(check_limits({'comp_pct':89},current(),hardware()))

class CustomPresetTests(unittest.TestCase):
    def test_many_unicode_profiles_roundtrip_and_rename_delete(self):
        with tempfile.TemporaryDirectory() as d:
            p=Presets(d)
            for i in range(35): p.save('شات '+str(i), {'threads':i+1})
            q=Presets(d); self.assertEqual(len(q.names()),38)
            q.rename('شات 1','My Shot'); q.delete('شات 2')
            r=Presets(d)
            self.assertEqual(r.profiles['My Shot']['threads'],2)
            self.assertNotIn('شات 2',r.names())
            self.assertNotIn('شات 1',r.names())
    def test_delete_keeps_unsaved_builtin_default(self):
        with tempfile.TemporaryDirectory() as d:
            p=Presets(d); p.save('Shot',{'threads':3}); p.delete('Shot')
            self.assertNotIn('Shared', Presets(d).profiles)
            self.assertEqual(Presets(d).load('Shared',current(),hardware(),[])['threads'],12)

    def test_conflict_and_builtin_protection(self):
        with tempfile.TemporaryDirectory() as d:
            p=Presets(d); p.save('Shot',{'threads':8}); q=Presets(d)
            p.save('Other',{'threads':4})
            with self.assertRaises(RuntimeError): q.rename('Shot','New')
            with self.assertRaises(ValueError): p.delete('Shared')
            with self.assertRaises(ValueError): p.rename('Comp focused','New')
            with self.assertRaises(ValueError): p.save(' ',{})

class Settings:
    def __init__(self): self.count='8'; self.reject=False
    def value(self,key): assert key==KEY; return self.count
    def setValue(self,key,value):
        assert key==KEY
        if self.reject: raise RuntimeError('write rejected')
        self.count=value

class FrameTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.settings=Settings(); self.knob=WorkerSetting(self.settings)
        self.env=patch.dict(os.environ,{'NPA_NUKE_DIR':self.tmp.name}); self.env.start(); self.addCleanup(self.env.stop)
    def controller(self):
        n=FakeNuke(); del n.prefs._knobs['worker']
        with patch('nuke_performance_assistant.backend.discover_worker',return_value=self.knob): return Controller(n)
    def test_discovery_no_modules_no_import(self):
        with patch.dict(sys.modules,{'hiero.core':None,'hiero.ui.nuke_bridge.FnNsFrameServer':None}):
            self.assertIsNone(discover_worker())
    def test_discovery_evidence_required(self):
        bridge=types.SimpleNamespace(workerCount=lambda:8)
        core=types.SimpleNamespace(ApplicationSettings=lambda:self.settings)
        with patch.dict(sys.modules,{'hiero.core':core,'hiero.ui.nuke_bridge.FnNsFrameServer':bridge}):
            with patch('inspect.getsource',return_value="settings = hiero.core.ApplicationSettings(); return int(settings.value('frameserver/workercount'))"):
                self.assertEqual(discover_worker().value(),8)
            with patch('inspect.getsource',return_value='return 8'):
                self.assertIsNone(discover_worker())
    def test_apply_restore_and_failure_rolls_back_external(self):
        c=self.controller()
        c.apply({'workers':2},hardware(),[],'Shared',warnings_accepted=True)
        self.assertEqual(self.knob.value(),2)
        self.assertFalse(c.frame_transaction.path.exists())
        c.apply(c.state['previous'],hardware(),[],'Shared',warnings_accepted=True,restoring=True)
        self.assertEqual(self.knob.value(),8)
        with patch.object(c.store,'commit',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): c.apply({'workers':1},hardware(),[],'Shared',warnings_accepted=True)
        self.assertEqual(self.knob.value(),8)
        self.assertFalse(c.frame_transaction.path.exists())
    def test_failed_external_write_retains_journal_if_rollback_fails(self):
        c=self.controller(); self.settings.reject=True
        with self.assertRaises(RuntimeError): c.apply({'workers':1},hardware(),[],'Shared',warnings_accepted=True)
        self.assertTrue(c.frame_transaction.path.exists())
    def test_crash_recovery_and_committed_cleanup(self):
        t=FrameTransaction(Path(self.tmp.name),self.knob)
        token=t.begin(8,2); self.knob.setValue(2)
        with patch('nuke_performance_assistant.frame_settings.process_alive',return_value=False):
            self.assertTrue(t.recover({}))
        self.assertEqual(self.knob.value(),8)
        t=FrameTransaction(Path(self.tmp.name),self.knob)
        token=t.begin(8,2); self.knob.setValue(2)
        self.assertFalse(t.recover({'frame_transaction':token}))
        self.assertEqual(self.knob.value(),2)
    def test_active_writer_and_external_change_not_overwritten(self):
        t=FrameTransaction(Path(self.tmp.name),self.knob); t.begin(8,2)
        with self.assertRaises(RuntimeError): t.recover({})
        self.knob.setValue(4)
        with patch('nuke_performance_assistant.frame_settings.process_alive',return_value=False):
            with self.assertRaises(RuntimeError): t.recover({})
        self.assertEqual(self.knob.value(),4)
