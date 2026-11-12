"""Small, explicit preference catalogue; no fuzzy knob-name guessing."""
import re
from dataclasses import dataclass


def normalized(value):
    return re.sub(r'[^a-z0-9%]+', '', str(value).lower())


@dataclass(frozen=True)
class Spec:
    key: str
    title: str
    group: str
    kind: str
    labels: tuple
    low: float = 0
    high: float = 100
    restart: bool = False
    help: str = ''


SPECS = (
    Spec('threads', 'Nuke compute threads', 'CPU', 'int', (), 1, 65536,
         help='Main-process CPU render thread limit, not core affinity. More threads are not always faster; Frame Server workers are separate.'),
    Spec('workers', 'Worker processes', 'Frame Server', 'int',
         ('frame server processes to run',), 1, 256, True,
         'Parallel render processes; each needs its own RAM and GPU memory.'),
    Spec('frame_server', 'Use Frame Server', 'Frame Server', 'bool',
         ('render using frame server (Nuke)', 'render using frame server'),
         restart=True, help='Render image sequences in background worker processes.'),
    Spec('frame_timeout', 'Render timeout (minutes)', 'Frame Server', 'float',
         ('frame server render timeout',), 1, 120, False,
         'Time allowed without a response before a render is stopped.'),
    Spec('gpu', 'Default Blink device', 'GPU', 'enum', ('default blink device',), restart=True,
         help='Device used by GPU-capable Blink nodes.'),
    Spec('texture_mb', 'GPU texture cache (MB)', 'GPU', 'int',
         ('GPU texture cache size', 'GPU texture cache size (MB)'), 1, 1048576, True,
         'GPU memory reserved for cached Viewer textures.'),
    Spec('blink_pct', 'Blink cache (%)', 'GPU', 'float',
         ('blink cache size %', 'blink cache size', 'blink cache size (%)'), 1, 100, True,
         'GPU memory available for Blink caching; larger is not always faster.'),
    Spec('blink_disabled', 'Disable Blink cache', 'GPU', 'bool', ('disable blink cache',),
         restart=True, help='Disable reuse of cached Blink GPU data.'),
    Spec('comp_pct', 'Comp cache (% of system RAM)', 'Cache', 'float',
         ('comp cache size (%)', 'comp cache size (% of system memory)', 'comp cache size'), 1, 90,
         help='RAM cache limit; processing can use additional memory.'),
    Spec('timeline_pct', 'Playback cache size (% of RAM)', 'Cache', 'float',
         ('playback cache size', 'playback cache size (% of system RAM)'), 1, 80,
         help='Timeline Viewer RAM cache, independent of comp playback cache. Unmapped builds require Nuke Preferences.'),
    Spec('playback_pct', 'Comp playback (% of comp cache)', 'Cache', 'float',
         ('comp playback cache size (% of comp cache)',), 1, 100,
         help='Share of comp cache available for Viewer playback.'),
    Spec('paint_pct', 'Comp paint (% of comp cache)', 'Cache', 'float',
         ('comp paint cache size (% of comp cache)',), 1, 100,
         help='Share of comp cache available for painting.'),
    Spec('disk_gb', 'Comp disk cache (GB)', 'Cache', 'float',
         ('comp disk cache size', 'comp disk cache size (GB)'), 1, 1048576,
         help='Disk space allowed for cached comp frames.'),
    Spec('paint_disk_gb', 'RotoPaint disk cache (GB)', 'Cache', 'float',
         ('rotopaint cache size', 'rotopaint cache size (GB)'), 1, 1048576,
         help='Disk space allowed for cached RotoPaint tiles.'),
    Spec('cache_path', 'Temporary / cache directory', 'Cache', 'path', ('temp directory',),
         restart=True, help='Existing writable cache folder; choose a fast local drive.'),
)
BY_KEY = {s.key: s for s in SPECS}
NUMERIC_CLASSES = {'Int_Knob', 'Unsigned_Knob', 'Double_Knob', 'Scale_Knob', 'Array_Knob'}


# Exact internal identifiers observed in a native Nuke 15.1v2 dump.
# Labels in Preferences may be rewritten by its UI and are not authoritative.
NATIVE_NAMES = {
    'frame_timeout': ('FrameServerRenderTimeout',),
    'frame_server': ('RenderWithFrameServer',),
    'gpu': ('selectedGPUDeviceIndex',),
    'texture_mb': ('viewer_texture_vram',),
    'blink_pct': ('BlinkCacheMemoryPercentage',),
    'blink_disabled': ('DisableBlinkCache',),
    'comp_pct': ('CacheLimit',),
    'playback_pct': ('PlaybackLimit',),
    'paint_pct': ('PaintCacheLimit',),
    'disk_gb': ('diskCacheGB',),
    'paint_disk_gb': ('PaintCacheGB',),
    'cache_path': ('DiskCachePath',),
}


def compatible(spec, knob):
    cls = knob.Class()
    if spec.kind in ('int', 'float'):
        if cls not in NUMERIC_CLASSES:
            return False
        try:
            return knob.arraySize() == 1
        except AttributeError:
            return cls != 'Array_Knob'  # Never guess the size of a generic array.
    return ((spec.kind == 'bool' and cls == 'Boolean_Knob')
            or (spec.kind == 'enum' and cls == 'Enumeration_Knob')
            or (spec.kind == 'path' and cls in ('File_Knob', 'String_Knob')))


def discover(preferences):
    """Exact internal ID first, exact label fallback, always type/shape checked."""
    found, unavailable = {}, {}
    knobs = preferences.knobs()
    for spec in SPECS:
        if spec.key == 'threads':
            continue
        named = [(name, knobs[name]) for name in NATIVE_NAMES.get(spec.key, ()) if name in knobs]
        if named:
            matches = [(name, knob) for name, knob in named if compatible(spec, knob)]
            if len(named) != 1 or len(matches) != 1:
                unavailable[spec.key] = 'Known identifier has an unexpected type/shape; left unchanged.'
                continue
        else:
            labels = {normalized(v) for v in spec.labels}
            matches = [(name, knob) for name, knob in knobs.items()
                       if normalized((knob.label() or '').replace('*', '')) in labels
                       and compatible(spec, knob)]
        if len(matches) == 1:
            found[spec.key] = matches[0]
        else:
            unavailable[spec.key] = ('Ambiguous preference; left unchanged.' if matches else
                                     'Not mapped in this build; left unchanged.')
    return found, unavailable
