# Resource policy 0.4.0

These are explicit capacity-allocation rules, not a measured optimum. They do not
alter image quality, node settings, OS priority, GPU clocks or drivers. All values
can be edited and saved in any of the three presets.

## CPU

Let C be logical CPUs available to the process (detector honors affinity where
supported). Shared sets max(1, C - ceil(0.25 C)); Comp focused sets C. The latter
removes the assistant's thread reserve. Utilization still depends on node
parallelism and I/O. This does not reserve physical cores for the UI.

## RAM

R is usable system RAM in GiB. Shared reserves max(4, 0.30 R) for OS/other work
and max(4, 0.15 R) for processing outside the comp cache. Comp focused reserves
max(4, 0.10 R) for each. These minimums/fractions are project policy assumptions.

If a timeline RAM control is exposed, propose 5% Shared or 3% Comp focused.
Otherwise account for an unknown 5% timeline allowance, without writing it.
Comp cache percentage is floor(100 * remaining RAM / R), capped at 80%.
If less than 1% remains, preserve the current control and report the limitation.
Unknown RAM preserves memory-cache values. This is a cache cap, not a total
process-memory cap or automatic eviction policy for other applications.

Comp playback and paint are overlapping sub-limits of comp cache, not additional
RAM allocations. Shared sets each to 50%; Comp focused sets each to 90%, allowing
either activity to use most of the parent cache. They do not allocate 180% RAM.

## GPU

Only an explicit device exposed by Nuke may be selected. Keep a valid current GPU;
if exactly one GPU exists and CPU/auto is selected, select that GPU. Multiple GPUs
are not ranked by name. Dedicated VRAM must match the selected device.

Texture budget = min(2048, VRAM_MiB * 0.0625) for Shared or
min(4096, VRAM_MiB * 0.125) for Comp focused, rounded down to 128-unit blocks in the
native MB control. No tiny-GPU minimum is forced. Budgeting uses conservative
binary-memory units consistently with the NVIDIA probe.

Blink = 25% Shared or 40% Comp focused. Foundry's Preferences documentation states
40% is preferred in most instances and larger caches may reduce performance.
Unknown dedicated memory preserves GPU cache budgets. Blink disablement is a
manual workflow choice. These settings do not cap GPU compute utilization.

## Disk

F = currently free GiB, D = filesystem capacity GiB. Retain max(20, 0.10 D) free.
Joint comp + paint allowance = max(0, F - reserve) * 0.50 Shared or 0.80 Comp focused.
Round down to whole native GB units, split 75% comp / 25% paint. Computing the budget
in GiB while the native control uses GB is conservative if the control uses decimal
GB. No arbitrary fixed 100 GB ceiling. Unknown/too-low space preserves current
limits. Files already cached are not measured as reclaimable; files are never deleted.
The proposed path is checked again at Apply. No drive-speed claim from free space.

## Frame Server and dynamic ceilings

Worker RAM estimate defaults to 8 GiB and is explicitly editable, not inferred
from CPU/GPU model. Budget = min(total RAM, available RAM at scan) minus
max(4 GiB, 20% total RAM). Estimated worker ceiling is min(logical CPUs,
floor(budget / RAM-per-worker)). A zero ceiling means the estimate cannot fit;
the native minimum of one remains visible and a changed worker setting is blocked.
Auto with a known RAM estimate uses min(ceiling, allotted CPU threads // 4), at
least one if feasible. For a selected GPU, auto instead starts with one because
per-worker VRAM is unknown. No per-worker thread limit is being configured.
Enabling Frame Server and changing timeout remain deliberate choices.

Numeric ceilings are implemented in limits.py and checked again in the backend.
RAM ceiling uses max(4 GiB, 10% RAM) for OS and the same for non-cache processing;
timeline and comp are coupled. GPU texture and Blink budgets share 80% VRAM and
Blink is capped at 50%. This is our planning policy, not a universal safe maximum.
Disk ceiling uses free minus max(20 GiB, 10% volume), converts GiB to GB, then
subtracts the other disk cache allowance. Auto recommendations remain below this.
Percentage sub-limits can overlap. Unknown hardware is never treated as zero
capacity. Unsupported controls remain unchanged. A restore uses the recorded
previous snapshot and may exceed planning ceilings; native range validation stays.
