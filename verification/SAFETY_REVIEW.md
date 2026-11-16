# Coupled resource safety patch

This local patch targets the published 0.5.2 preview. It has not been pushed or released.

## Behavior

`ram_budget()` is the shared GiB ledger used by `ceilings()` and `check_limits()`:

```
max(4 GiB, 10% RAM) OS reserve
+ max(4 GiB, 10% RAM) processing reserve
+ RAM * comp_pct / 100
+ RAM * timeline_pct / 100
+ workers * worker_ram_gb
<= physical usable RAM
```

An unmapped timeline retains the existing 5% allowance. All configured workers count,
even with Frame Server off. The estimate is planning data, not an enforced process
memory cap. Actual shot memory can exceed an observed peak.

Comp cache, timeline, workers and Frame Server enablement form one validation group.
Changing a group member validates its peers. Overcommit is a blocking error, including
Restore and calls that accept warnings. Unrelated edits do not silently rewrite legacy
preferences.

The 8 GiB default is unconfirmed. Old preset files that saved only the number are also
unconfirmed. Both recommendations and allowed worker counts are capped at one until
explicit editing. A persisted boolean records confirmation, survives preset rename,
and is removed with preset deletion. Loading or scanning never confirms a value.
The UI labels the worker ceiling `unconfirmed estimate` and explains how to measure
a representative worker peak. A confirmed estimate remains an estimate.

Auto stages only a complete, checked proposal. If supported minimum settings cannot
fit (for example 8 GiB RAM with the unconfirmed 8 GiB worker estimate, or insufficient
disk space after reserve), it returns no changes and an explicit blocked reason.
Unknown capacities do not authorize increases in the corresponding controls.

## Deterministic sweep

- Capacity seed 20261115.
- Every integer RAM capacity from 8 through 1024 GiB.
- VRAM unknown and every integer capacity from 4 through 48 GiB.
- Both unconfirmed defaults and confirmed worker peaks of 0.5, 2, 8, 16 or 32 GiB.
- CPUs sampled deterministically from 2 through 128.
- Free disk includes 5 and 4000 GB endpoints and deterministic intermediate samples.
- Both Shared and Comp focused, through direct Auto and built-in preset loading.
- 374,256 entry-point cases. Assertions independently calculate RAM, GPU memory,
  disk reserves and unit conversions, and also invoke the blocking validator.
- Unknown-capacity seed 71517, 4,096 additional cases.
- Total 378,352 sweep cases.

Disk probes use GiB; the disk-cache fields and sweep inputs use decimal GB. Tests
convert these explicitly before checking the combined disk allowance.

## Existing tests

All 99 original test methods remain. Twelve regression/UI tests were added.
No test methods were removed or newly skipped. Existing transaction fixtures now use
safe starting RAM budgets and an explicit confirmed peak. Assertions that previously
expected an untouched unknown worker count, an independent worker ceiling, or a
partial proposal on impossible hardware were updated to the new safety contract.
Unsafe historical combinations are explicitly tested as blocking errors, including
Restore. Rollback, persistence, metadata preservation, version compatibility and
Python 3.7 syntax checks remain in the suite.

## Reproduce

From the project directory:

```
python -m unittest discover -s tests -v
```

The sweep and core tests use the standard library only. To include the existing real
Qt widget tests, make PySide6 importable. The recorded run used Python 3.12.14 and PySide6 6.12.0; see the environment file for the actual interpreter.
Nuke itself was simulated. Native Nuke execution was not tested here.

## Final result

111 tests passed, no skips, in 45.194 seconds. Capacity sweep accepted 246,120
cases and blocked 128,136. All 4,096 unknown-capacity cases passed.
