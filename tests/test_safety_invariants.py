"""Deterministic safety tests; no Nuke, external packages or random global state."""
import json
import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_core import hardware, current, FakeNuke
from nuke_performance_assistant.limits import ceilings, check_limits, ram_budget
from nuke_performance_assistant.policy import recommendations
from nuke_performance_assistant.presets import Presets
from nuke_performance_assistant.backend import Controller


class CoupledRamTests(unittest.TestCase):
    def test_original_overcommit_blocks_either_peer_and_enable(self):
        h = hardware(); h.update(ram_gb=128, worker_ram_gb=8, worker_ram_confirmed=True)
        c = current(); c.update(comp_pct=75, timeline_pct=5, workers=8)
        for changed in ({'comp_pct':75}, {'workers':8}, {'frame_server':True}):
            errors = check_limits(changed, c, h)
            self.assertTrue(any('Combined RAM' in e for e in errors), errors)
        self.assertLess(ceilings(h,c)['comp_pct'][0],75)
        self.assertLess(ceilings(h,c)['workers'][0],8)

    def test_exact_boundary_and_one_step_over(self):
        h=hardware(); h.update(ram_gb=100, worker_ram_gb=5, worker_ram_confirmed=True)
        c=current(); c.update(comp_pct=55, timeline_pct=5, workers=4)
        self.assertAlmostEqual(ram_budget(h,c)['used'],100)
        self.assertFalse(check_limits({'comp_pct':55,'workers':4},c,h))
        self.assertEqual(ceilings(h,c)['comp_pct'][0],55)
        self.assertEqual(ceilings(h,c)['workers'][0],4)
        self.assertTrue(check_limits({'comp_pct':55.01},c,h))
        self.assertTrue(check_limits({'workers':5},c,h))

    def test_unconfirmed_default_caps_proposed_and_allowed(self):
        h=hardware(); h.update(ram_gb=1024, worker_ram_gb=8, worker_ram_confirmed=False)
        c=current(); c.update(comp_pct=20, timeline_pct=5, workers=8, frame_server=True)
        self.assertEqual(ceilings(h,c)['workers'][0],1)
        self.assertIn('unconfirmed estimate',ceilings(h,c)['workers'][1])
        self.assertTrue(check_limits({'workers':2},c,h))
        for mode in ('Shared','Comp focused'):
            proposal, why=recommendations(h,c,[c['gpu']],mode)
            self.assertNotIn('blocked',why)
            self.assertEqual(proposal['workers'],1)

    def test_backend_blocks_before_write_even_warnings_accepted_or_restore(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{'NPA_NUKE_DIR':folder}):
            n=FakeNuke(); control=Controller(n)
            h=hardware(); h.update(ram_gb=128,worker_ram_gb=8,worker_ram_confirmed=True)
            for restore in (False,True):
                with self.assertRaisesRegex(ValueError,'Combined RAM'):
                    control.apply({'comp_pct':75,'workers':8},h,[],'Comp focused',
                                  warnings_accepted=True,restoring=restore)
                self.assertEqual(control.current()['workers'],1)
                self.assertFalse(control.store.native.exists())

    def test_saved_default_is_not_confirmation_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Presets(folder); p.save('A',{'workers':1},worker_ram_gb=8)
            self.assertFalse(Presets(folder).confirmed.get('A',False))
            p.save('A',{'workers':2},worker_ram_gb=9,worker_ram_confirmed=True)
            p=Presets(folder); self.assertTrue(p.confirmed['A'])
            p.rename('A','B'); p=Presets(folder)
            self.assertTrue(p.confirmed['B']); self.assertEqual(p.planning['B'],9)
            p.delete('B'); self.assertNotIn('B',Presets(folder).confirmed)
            # Old files contain only the numeric default; never infer user confirmation.
            data=json.loads(p.path.read_text()); data.pop('worker_ram_confirmed',None)
            data['presets']['Legacy']={'workers':8}; data['worker_ram_gb']['Legacy']=8
            p.path.write_text(json.dumps(data))
            self.assertFalse(Presets(folder).confirmed.get('Legacy',False))

    def test_tiny_ram_and_disk_fail_closed(self):
        for ram,free in ((8,400),(64,5)):
            h=hardware(); h.update(ram_gb=ram,worker_ram_gb=8,worker_ram_confirmed=False)
            h['disk']['free_gb']=free
            v,why=recommendations(h,current(),[current()['gpu']],'Comp focused')
            self.assertEqual(v,{})
            self.assertIn('blocked',why)


class InvariantSweepTests(unittest.TestCase):
    def assert_safe(self,h,c,v):
        # Independent arithmetic oracle, not an assertion against the production helper.
        ram=h['ram_gb']; peak=h['worker_ram_gb']
        used=max(4.,ram*.1)+max(4.,ram*.1)+ram*(v['comp_pct']+v['timeline_pct'])/100.+v['workers']*peak
        self.assertLessEqual(used,ram+1e-8)
        vram=h['gpus'][0]['vram_gb']
        if vram is not None:
            used_gpu=v['texture_mb']/1024.+(0 if v.get('blink_disabled') else vram*v['blink_pct']/100.)
            self.assertLessEqual(used_gpu,vram*.8+1e-8)
        else:
            for key in ('texture_mb','blink_pct'):
                self.assertLessEqual(v[key],c[key])
        disk=h['disk']; capacity=max(0.,disk['free_gb']-max(20.,disk['total_gb']*.1))*1024**3/1e9
        self.assertLessEqual(v['disk_gb']+v['paint_disk_gb'],capacity+1e-8)
        if not h['worker_ram_confirmed']:
            self.assertLessEqual(v['workers'],1)
        self.assertFalse(check_limits(v,c,h))

    def test_full_capacity_sweep_presets_and_auto(self):
        rng=random.Random(20261115)
        count=accepted=blocked=0
        with tempfile.TemporaryDirectory() as folder:
            presets=Presets(folder)
            for ram in range(8,1025):
                for vram in [None]+list(range(4,49)):
                    for confirmed in (False,True):
                        cpus=rng.randint(2,128)
                        free_gb=(5.,4000.,rng.uniform(5,4000))[(ram+(vram or 0))%3]
                        h=hardware(); h.update(ram_gb=ram,logical_cpus=cpus,
                            worker_ram_gb=(rng.choice((.5,2.,8.,16.,32.)) if confirmed else 8.),
                            worker_ram_confirmed=confirmed)
                        h['gpus']=[{'name':'GPU','vram_gb':vram}]
                        h['disk']={'free_gb':free_gb*1e9/1024**3,
                                   'total_gb':max(100.,free_gb*1.5)*1e9/1024**3}
                        c=current(); c.update(gpu='GPU',threads=cpus,workers=rng.randint(1,16),
                            comp_pct=rng.randint(1,90),texture_mb=rng.randint(1,40000),
                            blink_pct=rng.randint(1,100),disk_gb=rng.randint(1,2000),
                            paint_disk_gb=rng.randint(1,2000),frame_server=True)
                        for mode in ('Shared','Comp focused'):
                            proposal,why=recommendations(h,c,['GPU'],mode)
                            loaded=presets.load(mode,c,h,['GPU'])
                            count+=2  # Auto and built-in preset loading entry points.
                            if 'blocked' in why:
                                blocked+=2
                                self.assertEqual(proposal,{})
                                self.assertEqual(loaded,c)
                                self.assertTrue(check_limits(c,c,h))
                            else:
                                accepted+=2
                                merged=dict(c,**proposal)
                                self.assertEqual(loaded,merged)
                                self.assert_safe(h,c,merged)
        self.assertEqual(count,374256)
        self.assertGreater(accepted,100000)
        self.assertGreater(blocked,0)
        print('\nCAPACITY SWEEP seed=20261115 cases={} accepted={} blocked={}'.format(count,accepted,blocked),flush=True)

    def test_unknown_capacities_never_increase(self):
        rng=random.Random(71517); count=0
        for i in range(2048):
            h=hardware(); h.update(ram_gb=None,logical_cpus=None,worker_ram_gb=8,worker_ram_confirmed=False,gpus=[],disk={})
            c=current()
            for key in ('threads','workers','comp_pct','timeline_pct','texture_mb','blink_pct','disk_gb','paint_disk_gb'):
                c[key]=rng.randint(1,80)
            for mode in ('Shared','Comp focused'):
                changes,why=recommendations(h,c,[c['gpu']],mode)
                for key in ('threads','workers','comp_pct','timeline_pct','texture_mb','blink_pct','disk_gb','paint_disk_gb'):
                    self.assertLessEqual(changes.get(key,c[key]),c[key])
                count+=1
        print('UNKNOWN CAPACITY SWEEP seed=71517 cases={}'.format(count),flush=True)
