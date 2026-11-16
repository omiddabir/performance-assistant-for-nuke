"""On-demand, offline hardware inventory. Standard library only; no shell=True."""
import csv
import ctypes
import io
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

GIB = 1024 ** 3


def usable_cpus():
    """Logical CPUs available to this process, including OS affinity restrictions."""
    count = os.cpu_count() or 1
    if hasattr(os, 'sched_getaffinity'):
        count = min(count, len(os.sched_getaffinity(0)))
    return max(1, count)


def command(args):
    try:
        opts = {'creationflags': 0x08000000} if os.name == 'nt' else {}
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=6, universal_newlines=True, **opts)
        return p.stdout.strip() if p.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return ''


def disk_info(path):
    p = Path(os.path.expandvars(os.path.expanduser(str(path))))
    if not p.is_absolute() or not p.is_dir():
        return {'path': str(p), 'free_gb': None, 'total_gb': None}
    try:
        d = shutil.disk_usage(str(p))
        return {'path': str(p), 'free_gb': d.free / GIB, 'total_gb': d.total / GIB}
    except OSError:
        return {'path': str(p), 'free_gb': None, 'total_gb': None}


def parse_nvidia(text):
    devices = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) == 3:
            try:
                devices.append({'name': row[0].strip(), 'vram_gb': float(row[1]) / 1024,
                                'uuid': row[2].strip(), 'source': 'nvidia-smi'})
            except ValueError:
                pass
    return devices


def detect(cache_path):
    out = {'os': platform.system(), 'cpu': platform.processor() or 'Unknown',
           'logical_cpus': usable_cpus(), 'physical_cores': None,
           'ram_gb': None, 'available_gb': None, 'gpus': [], 'warnings': []}
    try:
        if out['os'] == 'Windows':
            class MemoryStatus(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong) for name in
                    ('total', 'avail', 'page_total', 'page_avail', 'virtual_total', 'virtual_avail', 'extended')]
            m = MemoryStatus()
            m.length = ctypes.sizeof(m)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                out.update(ram_gb=m.total / GIB, available_gb=m.avail / GIB)
            raw = command(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                           'Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores | ConvertTo-Json -Compress'])
            if raw:
                cpus = json.loads(raw)
                cpus = cpus if isinstance(cpus, list) else [cpus]
                out['cpu'] = ' / '.join(c['Name'].strip() for c in cpus)
                out['physical_cores'] = sum(int(c['NumberOfCores']) for c in cpus)
        elif out['os'] == 'Linux':
            mem = {}
            for line in Path('/proc/meminfo').read_text().splitlines():
                k, v = line.split(':', 1)
                mem[k] = int(v.strip().split()[0]) * 1024
            out.update(ram_gb=mem['MemTotal'] / GIB, available_gb=mem.get('MemAvailable', 0) / GIB)
            cpu = Path('/proc/cpuinfo').read_text()
            pairs = set()
            for block in cpu.split('\n\n'):
                fields = dict(line.split(':', 1) for line in block.splitlines() if ':' in line)
                fields = {k.strip(): v.strip() for k, v in fields.items()}
                if 'model name' in fields:
                    out['cpu'] = fields['model name']
                if 'physical id' in fields and 'core id' in fields:
                    pairs.add((fields['physical id'], fields['core id']))
            out['physical_cores'] = len(pairs) or None
            # Container limits affect usable resources; do not advertise host RAM as usable.
            for file in ('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes'):
                try:
                    limit = int(Path(file).read_text().strip()) / GIB
                    if 0 < limit < out['ram_gb']:
                        out['ram_gb'] = limit
                        out['available_gb'] = None
                        out['warnings'].append('RAM is constrained by a container limit.')
                except (OSError, ValueError):
                    pass
        elif out['os'] == 'Darwin':
            def sysctl(key):
                return command(['sysctl', '-n', key])
            out['ram_gb'] = int(sysctl('hw.memsize')) / GIB
            out['physical_cores'] = int(sysctl('hw.physicalcpu'))
            out['cpu'] = sysctl('machdep.cpu.brand_string') or platform.machine()
            out['warnings'].append('macOS GPU memory may be unified; no dedicated VRAM is assumed.')
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        out['warnings'].append('Some hardware details could not be detected. Unknown values are not estimated.')
    smi = shutil.which('nvidia-smi')
    if not smi and os.name == 'nt':
        candidate = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/nvidia-smi.exe'
        smi = str(candidate) if candidate.is_file() else None
    if smi:
        out['gpus'] = parse_nvidia(command([smi, '--query-gpu=name,memory.total,uuid', '--format=csv,noheader,nounits']))
    if not out['ram_gb']:
        out['warnings'].append('System RAM unknown: automatic RAM recommendations are disabled.')
    out['disk'] = disk_info(cache_path)
    return out
