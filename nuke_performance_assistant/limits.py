"""Coupled planning ceilings. These are budgets, never performance guarantees."""
import math
from .specs import BY_KEY


def ceilings(hw, values):
    from .policy import gpu_vram
    out = {k: (s.high, 'Percentage/application planning range') for k, s in BY_KEY.items()
           if s.kind in ('int', 'float')}
    def put(k, value, reason):
        if value is not None and math.isfinite(value):
            out[k] = (max(0, min(BY_KEY[k].high, math.floor(value * 100) / 100)), reason)
    put('frame_timeout', 10, 'Normal Preferences slider range; timeout is not a hardware capacity')
    put('blink_pct', 50, 'Conservative Blink cache ceiling')
    cpus = max(1, int(hw.get('logical_cpus') or 1))
    put('threads', cpus, 'Available logical CPUs')
    ram = hw.get('ram_gb')
    worker_peak = hw.get('worker_ram_gb', 8.)
    worker_max = cpus
    if ram and ram > 0:
        reserve = max(4., ram * .1) + max(4., ram * .1)
        total_pct = max(0., (ram - reserve) / ram * 100)
        put('comp_pct', total_pct - values.get('timeline_pct', 5), 'RAM minus OS, processing and timeline budgets')
        put('timeline_pct', total_pct - values.get('comp_pct', 0), 'RAM minus OS, processing and comp budgets')
        if worker_peak and worker_peak > 0:
            available = min(ram, hw.get('available_gb') if hw.get('available_gb') is not None else ram)
            worker_max = min(cpus, max(0, int(max(0, available - max(4, ram * .2)) / worker_peak)))
    put('workers', worker_max, 'Estimated from available RAM and RAM per worker; test a representative shot')
    vram = gpu_vram(values.get('gpu', ''), hw)
    if vram and vram > 0:
        put('texture_mb', math.floor(vram * 1024 * max(0, .8 - (0 if values.get('blink_disabled') else values.get('blink_pct', 0) / 100))), 'Shared VRAM budget; 20% retained for display and processing')
        put('blink_pct', min(50, max(0, 80 - values.get('texture_mb', 0) / (vram * 1024) * 100)), 'Shared VRAM budget; 20% retained for display and processing')
    else:
        out['texture_mb'] = (None, 'Dedicated VRAM unknown; verify manually')
        out['blink_pct'] = (None, 'Dedicated VRAM unknown; verify manually')
    disk = hw.get('disk', {})
    free, total = disk.get('free_gb'), disk.get('total_gb')
    if free is not None and total is not None:
        # Disk probes use GiB, while native fields are labelled GB. Budget in decimal GB.
        budget = max(0, free - max(20, total * .1)) * (1024 ** 3 / 1e9)
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
    groups = [('threads',), ('workers',), ('frame_timeout',), ('comp_pct', 'timeline_pct'),
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
    return errors
