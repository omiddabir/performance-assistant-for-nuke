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
from nuke_performance_assistant.policy import recommendations, PROPOSAL_GROUPS
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
            previous={'comp_pct':75,'workers':8}
            with self.assertRaisesRegex(ValueError,'Combined RAM'):
                control.apply(previous,h,[],'Comp focused',warnings_accepted=True)
            self.assertEqual(control.current()['workers'],1)
            self.assertFalse(control.store.native.exists())
            errors,warnings=control.check(previous,h,restoring=True)
            self.assertFalse(errors)
            self.assertTrue(any('192.00 GiB requested / 128.00 GiB available' in w for w in warnings))
            with self.assertRaisesRegex(ValueError,'Review warnings before applying'):
                control.apply(previous,h,[],'Comp focused',restoring=True)
            self.assertFalse(control.store.native.exists())
            control.apply(previous,h,[],'Comp focused',warnings_accepted=True,restoring=True)
            self.assertEqual(control.current()['workers'],8)
            self.assertEqual(control.current()['comp_pct'],75)

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
        for ram,free,group in ((8,400,'ram'),(64,5,'disk')):
            h=hardware(); h.update(ram_gb=ram,worker_ram_gb=8,worker_ram_confirmed=False)
            h['disk']['free_gb']=free
            c=current(); v,why=recommendations(h,c,[c['gpu']],'Comp focused')
            self.assertIn(group,why['blocked_groups'])
            self.assertNotIn('blocked',why)
            self.assertIn('threads',v)
            for key in PROPOSAL_GROUPS[group]:
                self.assertNotIn(key,v)
                if key in c: self.assertEqual(dict(c,**v)[key],c[key])

    def test_low_disk_does_not_block_other_groups(self):
        for ram in (128,256,1024):
            for free in (0,1,5):
                h=hardware(); h.update(ram_gb=ram,worker_ram_gb=8,worker_ram_confirmed=False)
                h['disk']['free_gb']=free
                for mode in ('Shared','Comp focused'):
                    c=current(); v,why=recommendations(h,c,[c['gpu']],mode)
                    self.assertEqual(set(why['blocked_groups']),{'disk'})
                    self.assertNotIn('blocked',why)
                    for key in ('threads','comp_pct','workers','texture_mb','blink_pct'):
                        self.assertIn(key,v)
                    self.assertFalse(check_limits(v,c,h))
                    merged=dict(c,**v)
                    self.assertLessEqual(ram_budget(h,merged)['used'],ram)
                    self.assertLessEqual(merged['texture_mb']/1024+16*merged['blink_pct']/100,16*.8)
                    self.assertEqual(merged['disk_gb'],c['disk_gb'])

    def test_gpu_group_failure_preserves_other_groups(self):
        h=hardware(); h['gpus'][0]['vram_gb']=4
        c=current(); c['texture_mb']=100000
        v,why=recommendations(h,c,[c['gpu']],locks=('texture_mb',))
        self.assertIn('gpu',why['blocked_groups'])
        self.assertIn('comp_pct',v); self.assertIn('disk_gb',v)
        self.assertTrue(all(k not in v for k in PROPOSAL_GROUPS['gpu']))


class InvariantSweepTests(unittest.TestCase):
    def assert_safe(self,h,c,proposal,blocked):
        v=dict(c,**proposal)
        for group,keys in PROPOSAL_GROUPS.items():
            if group in blocked:
                self.assertTrue(blocked[group])
                for key in keys:
                    self.assertNotIn(key,proposal)
                    if key in c: self.assertEqual(v[key],c[key])
        # Independent arithmetic oracle for each proposed group.
        ram=h['ram_gb']; peak=h['worker_ram_gb']
        if 'ram' not in blocked:
            used=max(4.,ram*.1)+max(4.,ram*.1)+ram*(v['comp_pct']+v['timeline_pct'])/100.+v['workers']*peak
            self.assertLessEqual(used,ram+1e-8)
            if not h['worker_ram_confirmed']: self.assertLessEqual(v['workers'],1)
        vram=h['gpus'][0]['vram_gb']
        if 'gpu' not in blocked and vram is not None:
            used_gpu=v['texture_mb']/1024.+(0 if v.get('blink_disabled') else vram*v['blink_pct']/100.)
            self.assertLessEqual(used_gpu,vram*.8+1e-8)
        if 'disk' not in blocked:
            disk=h['disk']; capacity=max(0.,disk['free_gb']-max(20.,disk['total_gb']*.1))*1024**3/1e9
            self.assertLessEqual(v['disk_gb']+v['paint_disk_gb'],capacity+1e-8)
        if 'cpu' not in blocked: self.assertLessEqual(v['threads'],h['logical_cpus'])
        if 'shape' not in blocked:
            for key in ('playback_pct','paint_pct'): self.assertTrue(0<=v[key]<=100)
        self.assertFalse(check_limits(proposal,c,h))

    def test_full_capacity_sweep_presets_and_auto(self):
        rng=random.Random(20261115)
        scenarios=set(); cases=set(); variants=0
        blocked_cases={g:set() for g in ('ram','gpu','disk','all-groups')}
        with tempfile.TemporaryDirectory() as folder:
            presets=Presets(folder)
            for ram in range(8,1025):
                for vram in [None]+list(range(4,49)):
                    cpus=rng.randint(2,128)
                    free_gb=(5.,4000.,rng.uniform(5,4000))[(ram+(vram or 0))%3]
                    scenario=(ram,vram,cpus,free_gb)
                    scenarios.add(scenario)
                    for confirmed in (False,True):
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
                            case=(scenario,mode); cases.add(case); variants+=1
                            proposal,why=recommendations(h,c,['GPU'],mode)
                            loaded=presets.load(mode,c,h,['GPU'])
                            self.assertEqual(loaded,dict(c,**proposal))
                            blocked=why.get('blocked_groups',{})
                            for group in ('ram','gpu','disk'):
                                if group in blocked: blocked_cases[group].add(case)
                            if 'blocked' in why:
                                blocked_cases['all-groups'].add(case)
                                self.assertEqual(proposal,{})
                                self.assertEqual(loaded,c)
                            self.assert_safe(h,c,proposal,blocked)
        self.assertEqual(len(scenarios),46782)
        self.assertEqual(len(cases),93564)
        self.assertEqual(variants,187128)
        for group in ('ram','gpu','disk'): self.assertGreater(len(blocked_cases[group]),0)
        print('\nCAPACITY SWEEP seed=20261115 unique_hardware={} x presets=2 cases={} estimate_variants={} blocked={}'.format(
            len(scenarios),len(cases),variants,{k:len(v) for k,v in blocked_cases.items()}),flush=True)

    def test_restore_sweep(self):
        rng=random.Random(51217); over=0
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{'NPA_NUKE_DIR':folder}):
            for index in range(512):
                h=hardware(); h.update(ram_gb=rng.randint(8,1024),logical_cpus=128,
                                      worker_ram_gb=rng.choice((.5,2.,8.,32.)),worker_ram_confirmed=True)
                n=FakeNuke()
                n.prefs._knobs['cache'].setValue(rng.randint(1,90))
                n.prefs._knobs['worker'].setValue(rng.randint(1,16))
                control=Controller(n)
                previous={'comp_pct':rng.randint(1,90),'workers':rng.randint(1,16)}
                ram=h['ram_gb']
                used=2*max(4.,ram*.1)+ram*(previous['comp_pct']+5)/100+previous['workers']*h['worker_ram_gb']
                is_over=used>ram+1e-8
                errors,warnings=control.check(previous,h,restoring=True)
                self.assertFalse(errors)
                ram_warnings=[w for w in warnings if w.startswith('Combined RAM budget')]
                self.assertEqual(bool(ram_warnings),is_over)
                if is_over:
                    over+=1
                    self.assertIn('{:.2f} GiB requested / {:.2f} GiB available'.format(used,ram),ram_warnings[0])
                if warnings:
                    before=control.current()
                    with self.assertRaisesRegex(ValueError,'Review warnings before applying'):
                        control.apply(previous,h,[],'Shared',restoring=True)
                    self.assertEqual(control.current(),before)
                control.apply(previous,h,[],'Shared',restoring=True,warnings_accepted=True)
                for k,v in previous.items(): self.assertEqual(control.current()[k],v)
        self.assertGreater(over,0); self.assertLess(over,512)
        print('RESTORE SWEEP seed=51217 pairs=512 over_ram={} within_ram={}'.format(over,512-over),flush=True)

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


class PartialApplyTests(unittest.TestCase):
    def test_other_groups_apply_with_oversized_disk_values_untouched(self):
        from test_native15 import fixture
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{'NPA_NUKE_DIR':folder}):
            n=FakeNuke(); n.prefs=fixture(); control=Controller(n)
            h=hardware(); h['ram_gb']=128; h['disk']['free_gb']=5
            before=control.current()
            changes,reasons=recommendations(h,before,[before['gpu']],'Shared')
            self.assertEqual(set(reasons['blocked_groups']),{'disk'})
            with patch('nuke_performance_assistant.backend.disk_info',return_value=h['disk']):
                errors,warnings=control.check(changes,h)
                self.assertFalse(errors)
                control.apply(changes,h,[],'Shared',warnings_accepted=True)
            self.assertEqual(control.current()['disk_gb'],before['disk_gb'])
            self.assertEqual(control.current()['paint_disk_gb'],before['paint_disk_gb'])
            self.assertEqual(control.current()['threads'],changes['threads'])
            self.assertEqual(control.current()['comp_pct'],changes['comp_pct'])
            self.assertEqual(control.current()['texture_mb'],changes['texture_mb'])
