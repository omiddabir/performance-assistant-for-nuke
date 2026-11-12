"""Explainable starting budgets, not measured optimal settings or Foundry presets."""
import math
from .specs import normalized, BY_KEY


def gpu_vram(device, hardware):
    name = normalized(device)
    matches = [g for g in hardware.get('gpus', []) if normalized(g['name']) == name]
    if len(matches) == 1:
        return matches[0].get('vram_gb')
    return None


def recommendations(hw, current, devices, mode='Shared', locks=()):
    """Capacity budgets, not a benchmark. Never equate cache size with compute speed.

    Comp focused exposes every logical CPU. Cache budgets subtract OS, non-cache
    processing and timeline allowances. Unknown capacities preserve current values.
    Frame Server count needs a measured per-worker peak, not CPU count alone.
    """
    values, reasons = {}, {}
    if mode == 'User preset':
        return values, reasons
    focused = mode in ('Comp focused', 'Nuke focused')
    def put(key, value, reason):
        if key in current and key not in locks:
            values[key], reasons[key] = value, reason
    cpus = max(1, int(hw.get('logical_cpus') or 1))
    threads = cpus if focused else max(1, cpus - max(1, math.ceil(cpus * .25)))
    put('threads', threads, 'All logical CPUs.' if focused else 'Reserve 25% for other work.')
    ram = hw.get('ram_gb')
    if ram and math.isfinite(ram) and ram > 0:
        os_reserve = max(4., ram * (.10 if focused else .30))
        working = max(4., ram * (.10 if focused else .15))
        # The timeline budget is independent, not a sub-cache of comp RAM.
        timeline_pct = 3 if focused else 5
        if 'timeline_pct' in current and 'timeline_pct' not in locks:
            put('timeline_pct', timeline_pct, 'Separate timeline reserve.')
        else:
            timeline_pct = current.get('timeline_pct', 5)
        cache_gb = max(0., ram - os_reserve - working - ram * timeline_pct / 100.)
        pct = min(80, int(math.floor(100 * cache_gb / ram)))
        if pct >= 1:
            put('comp_pct', pct, 'RAM minus OS, processing and timeline reserves.')
        else:
            reasons['comp_pct'] = 'Unchanged: insufficient RAM after operating-system and processing reserves.'
        # Overlapping sub-limits allow either activity to use the parent cache.
        put('playback_pct', 90 if focused else 50, 'Shared parent comp cache; no extra RAM allocation.')
        put('paint_pct', 90 if focused else 50, 'Shared parent comp cache; no extra RAM allocation.')
        reasons['workers'] = 'Unchanged: per-worker RAM and VRAM cost require a representative render.'
    selected = current.get('gpu')
    options = [d for d in devices if normalized(d) not in
               ('cpu', 'usecpu', 'nogpudevice', 'none', 'default', 'automatic', 'auto')]
    if selected not in options and len(options) == 1 and 'gpu' not in locks:
        selected = options[0]
        put('gpu', selected, 'Only explicit GPU available.')
    vram = gpu_vram(selected, hw) if selected else None
    if vram and math.isfinite(vram) and vram > 0:
        # Quantize down; no artificial minimum exceeding a small GPU's capacity.
        texture = int(min(4096 if focused else 2048, vram * 1024 * (.125 if focused else .0625)) // 128) * 128
        if focused and selected == current.get('gpu'):
            from .limits import ceilings
            planned = dict(current, **values)
            if 'blink_pct' in current and 'blink_pct' not in locks:
                planned['blink_pct'] = 40
            ceiling = ceilings(hw, planned)['texture_mb'][0]
            texture = min(int(ceiling), max(texture, int(current.get('texture_mb', 0))))
        if texture >= 1:
            put('texture_mb', texture, 'Keep the larger of the current limit and the VRAM baseline, within the shared GPU budget.' if focused else 'Shared VRAM baseline.')
        # Foundry prefers 40% in most cases; do not maximize this cache.
        put('blink_pct', 40 if focused else 25, 'Foundry baseline; remaining VRAM is available for processing.')
    free, total = (hw.get('disk', {}).get(k) for k in ('free_gb', 'total_gb'))
    if free is not None and total is not None and all(math.isfinite(x) and x >= 0 for x in (free, total)):
        reserve = max(20., total * .10)
        budget = max(0., free - reserve) * (.80 if focused else .50)
        # Joint budget: preserve locked cache limits when using legacy callers.
        fixed = sum(current.get(k, 0) for k in ('disk_gb', 'paint_disk_gb') if k in locks)
        remaining = max(0., budget - fixed)
        keys = [k for k in ('disk_gb', 'paint_disk_gb') if k in current and k not in locks]
        if remaining >= len(keys) and keys:
            if len(keys) == 2 and remaining >= 4:
                paint = max(1, int(remaining * .25))
                put('paint_disk_gb', paint, '25% of joint cache allowance.')
                put('disk_gb', int(remaining) - paint, 'Joint allowance after free-space reserve.')
            elif len(keys) == 1:
                put(keys[0], int(remaining), 'Remaining joint cache allowance.')
    if 'workers' in current and 'workers' not in locks and hw.get('worker_ram_gb') and hw.get('ram_gb'):
        from .limits import ceilings
        cap = ceilings(hw, dict(current, **values))['workers'][0]
        # CPU and RAM planning allowance. GPU peak is unknown: use one worker
        # until the user opts into more after measuring a representative shot.
        gpu_active = normalized(selected or '') not in ('', 'cpu', 'usecpu', 'none')
        count = 1 if gpu_active else min(int(cap), max(1, threads // 4))
        if focused and current.get('frame_server') and gpu_active:
            count = min(int(cap), current['workers'])
            if cap >= 1:
                put('workers', count, 'Retain configured GPU workers within the estimated RAM ceiling; verify VRAM on the shot.')
        elif cap >= 1: put('workers', max(1, count), 'Estimated RAM budget; GPU renders start with one worker to avoid VRAM duplication.' if gpu_active else 'CPU/RAM starting budget; measure peak memory per worker.')
    # Frame Server enablement and timeout are deliberate workflow choices.
    return values, reasons


def validate(values, current, hw, devices):
    errors, warnings = [], []
    merged = dict(current, **values)
    for key, value in values.items():
        spec = BY_KEY.get(key)
        if not spec:
            errors.append('Unknown setting: ' + key)
            continue
        if spec.kind in ('int', 'float'):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                errors.append(spec.title + ': expected a finite number.')
            elif not spec.low <= value <= spec.high or (spec.kind == 'int' and value != int(value)):
                errors.append(spec.title + ': value outside the supported range.')
        elif spec.kind == 'enum' and value not in devices:
            errors.append('GPU is no longer offered by this Nuke build.')
        elif spec.kind == 'bool' and not isinstance(value, bool):
            errors.append(spec.title + ': expected true/false.')
    if errors:
        return errors, warnings
    if merged.get('threads', 1) > hw.get('logical_cpus', 1):
        errors.append('Compute thread limit exceeds detected/entered logical CPUs.')
    if merged.get('workers', 1) > 1:
        warnings.append('Multiple Frame Server processes can multiply RAM and VRAM consumption. Test on a representative comp.')
    if merged.get('comp_pct', 0) + merged.get('timeline_pct', 0) > 80:
        warnings.append('Combined comp/timeline cache budgets leave little system headroom.')
    if merged.get('comp_pct', 0) >= 80:
        warnings.append('Comp cache is not a total RAM cap; plugins and nodes allocate additional memory.')
    free = hw.get('disk', {}).get('free_gb')
    if any(k in values for k in ('disk_gb', 'paint_disk_gb')):
        if free is None:
            errors.append('Cannot check free space for the selected cache directory.')
        elif merged.get('disk_gb', 0) + merged.get('paint_disk_gb', 0) > free * 0.8:
            warnings.append('Combined disk-cache limits exceed 80% of currently free space; existing cache occupancy is not measured.')
    vram = gpu_vram(merged.get('gpu', ''), hw)
    if any(k in values for k in ('texture_mb', 'blink_pct')):
        if vram:
            if merged.get('texture_mb', 0) / 1024 > vram * 0.8:
                errors.append('Texture cache alone exceeds 80% of dedicated VRAM.')
            if merged.get('texture_mb', 0) / 1024 + vram * merged.get('blink_pct', 0) / 100 > vram * 0.8:
                warnings.append('Combined GPU cache budgets leave little headroom for display and processing.')
        else:
            warnings.append('Dedicated VRAM is unknown for this device. GPU budgets require manual verification.')
    return errors, warnings
