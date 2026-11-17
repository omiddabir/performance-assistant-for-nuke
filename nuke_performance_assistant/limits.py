"""Coupled planning ceilings. These are budgets, never performance guarantees."""
import math
from .specs import BY_KEY


RAM_GROUP = ('comp_pct', 'timeline_pct', 'workers', 'frame_server')


def positive(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def ram_budget(hw, values):
    """One conservative RAM ledger, in GiB, shared by planning and validation.

    Count every configured worker, even while Frame Server is disabled, so enabling
    it later cannot silently consume memory already promised to the main process.
    An unmapped timeline retains a 5% allowance. Peaks remain estimates, not caps.
    """
    ram = hw.get('ram_gb')
    peak = hw.get('worker_ram_gb', 8.)
    confirmed = hw.get('worker_ram_confirmed') is True and positive(peak)
    if not positive(peak):
        peak = 8.
    if not positive(ram):
        return dict(known=False, confirmed=confirmed, peak=peak)
    os_reserve = max(4., ram * .1)
    processing = max(4., ram * .1)
    comp = ram * values.get('comp_pct', 0) / 100.
    timeline = ram * values.get('timeline_pct', 5) / 100.
    workers = values.get('workers', 0)
    used = os_reserve + processing + comp + timeline + workers * peak
    return dict(known=True, confirmed=confirmed, peak=peak, ram=ram,
                os_reserve=os_reserve, processing_reserve=processing,
                comp_cache=comp, timeline=timeline, worker_count=workers,
                used=used, remaining=ram-used)


def disk_budget(hw):
    disk = hw.get('disk', {})
    free, total = disk.get('free_gb'), disk.get('total_gb')
    if (isinstance(free, (int, float)) and math.isfinite(free) and free >= 0
            and positive(total)):
        return max(0., free - max(20., total * .1)) * (1024 ** 3 / 1e9)
    return None


def ceilings(hw, values):
    from .policy import gpu_vram
    out = {k: (s.high, 'Percentage/application planning range') for k, s in BY_KEY.items()
           if s.kind in ('int', 'float')}
    def put(k, value, reason):
        if value is not None and math.isfinite(value):
            out[k] = (max(0, min(BY_KEY[k].high, math.floor(value * 100 + 1e-9) / 100)), reason)
    put('frame_timeout', 10, 'Normal Preferences slider range; timeout is not a hardware capacity')
    put('blink_pct', 50, 'Conservative Blink cache ceiling')
    cpus = max(1, int(hw.get('logical_cpus') or 1))
    put('threads', cpus, 'Available logical CPUs')
    ledger = ram_budget(hw, values)
    worker_max = 1
    if ledger['known']:
        spare = ledger['remaining']
        put('comp_pct', values.get('comp_pct', 0) + spare / ledger['ram'] * 100,
            'Shared RAM allowance after OS, processing, timeline and workers')
        put('timeline_pct', values.get('timeline_pct', 5) + spare / ledger['ram'] * 100,
            'Shared RAM allowance after OS, processing, comp cache and workers')
        worker_max = min(cpus, max(0, math.floor(ledger['worker_count'] + spare / ledger['peak'] + 1e-10)))
        available = hw.get('available_gb')
        if available is not None and math.isfinite(available):
            worker_max = min(worker_max, max(0, math.floor(available / ledger['peak'])))
    else:
        for key in ('comp_pct', 'timeline_pct'):
            out[key] = (None, 'System RAM unknown; increases are blocked')
    if not ledger['confirmed']:
        worker_max = min(1, worker_max)
    put('workers', worker_max, 'User-confirmed worker estimate; shared RAM allowance' if ledger['confirmed']
        else 'unconfirmed estimate; measure one worker before allowing more than one')
    vram = gpu_vram(values.get('gpu', ''), hw)
    if positive(vram):
        put('texture_mb', math.floor(vram * 1024 * max(0, .8 - (0 if values.get('blink_disabled') else values.get('blink_pct', 0) / 100))), 'Shared VRAM budget; 20% retained for display and processing')
        put('blink_pct', min(50, max(0, 80 - values.get('texture_mb', 0) / (vram * 1024) * 100)), 'Shared VRAM budget; 20% retained for display and processing')
    else:
        out['texture_mb'] = (None, 'Dedicated VRAM unknown; verify manually')
        out['blink_pct'] = (None, 'Dedicated VRAM unknown; verify manually')
    budget = disk_budget(hw)
    if budget is not None:
        for key in ('disk_gb', 'paint_disk_gb'):
            put(key, budget, 'Total allowance shared by both disk caches')
    else:
        out['disk_gb'] = out['paint_disk_gb'] = (None, 'Disk capacity unknown')
    return out


def check_limits(changed, current, hw):
    values = dict(current, **changed)
    limits = ceilings(hw, values)
    errors = []
    # Validate coupled peers only when their group changes. Existing oversize preferences
    # remain visible and are not silently rewritten when an unrelated field is edited.
    groups = [('threads',), ('frame_timeout',), RAM_GROUP,
              ('texture_mb', 'blink_pct', 'blink_disabled', 'gpu')]
    for group in groups:
        if not any(k in changed for k in group): continue
        for key in group:
            if key not in values or key not in limits: continue
            if key == 'blink_pct' and values.get('blink_disabled'): continue
            maximum, reason = limits[key]
            if maximum is not None and values[key] > maximum + .0001:
                errors.append('{} exceeds budget max {:g}. {}'.format(BY_KEY[key].title, maximum, reason))
    if {'disk_gb', 'paint_disk_gb', 'cache_path'}.intersection(changed):
        maximum = limits['disk_gb'][0]
        combined = values.get('disk_gb', 0) + values.get('paint_disk_gb', 0)
        if maximum is not None and combined > maximum + .0001:
            errors.append('Combined disk caches: {:g} GB requested, {:g} GB available after reserve.'.format(combined, maximum))
    if set(RAM_GROUP).intersection(changed):
        ledger = ram_budget(hw, values)
        if ledger['known'] and ledger['remaining'] < -1e-8:
            errors.append('Combined RAM budget exceeds physical RAM: {:.2f} GiB requested / {:.2f} GiB available (OS + processing + comp + timeline + workers).'.format(ledger['used'], ledger['ram']))
        if not ledger['known']:
            for key in ('comp_pct', 'timeline_pct', 'workers'):
                if values.get(key, 0) > current.get(key, 0):
                    errors.append('System RAM unknown; cannot increase ' + key)
    for key in ('texture_mb', 'blink_pct', 'disk_gb', 'paint_disk_gb'):
        if key in changed and limits[key][0] is None and values[key] > current.get(key, 0):
            errors.append('Capacity unknown; cannot increase ' + key)
    return errors
