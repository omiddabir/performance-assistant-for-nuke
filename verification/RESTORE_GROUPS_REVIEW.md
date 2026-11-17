# Restore and independent-proposal corrections

This patch is against the local code present at the start of this task, including
its preceding coupled-RAM safety patch. Nothing was pushed to GitHub.

## Changes

- `backend.py`: coupled RAM check messages become warnings during Restore. Normal
  Apply still receives the same blocking errors. An unconfirmed Restore raises
  `Review warnings before applying`; a confirmed Restore can exceed the RAM limit.
  Numeric/type checks, persistence protections and unrelated validation remain.
- `policy.py`: CPU, RAM, GPU, disk and sub-cache share proposals are checked in
  separate groups. An unsafe or unknown-capacity group is omitted and explained in
  `blocked_groups`. Omitted fields keep their exact current values. The existing
  2 GiB case remains wholly blocked because base system reserves alone exceed RAM.
- `presets.py` needs no edit: built-in defaults already call `recommendations()`.
  Both entry points are compared in every capacity case. Saved user-edited profiles
  remain saved values and retain existing Apply validation.
- `ui.py`: only the existing Auto status-text assignment changed, appending partial
  group messages. Restore confirmation requires no UI edit. Offscreen Qt tests cover
  declining and accepting an over-limit Restore through the existing flow.
- `hardware.py` and startup: both use `usable_cpus()` for the minimum of CPU count
  and process affinity. Startup tests patch this helper instead of host CPU count.
- No new plugin dependencies; Python 3.7-compatible syntax.

`limits.py`, `presets.py`, and `policy.validate()` are unchanged byte-for-byte.

## Existing tests changed

No original test method was removed or newly skipped. All 111 remain; 10 were added.

- `test_backend_blocks_before_write_even_warnings_accepted_or_restore`: retains the
  normal Apply rejection and no-write assertions. Restore now checks the requested
  distinction: numeric warnings, rejection without confirmation, successful confirmed
  restoration of the exact requested values.
- `test_tiny_ram_and_disk_fail_closed`: each failing group must now be omitted, have
  an explanatory message, and retain every current field. Healthy CPU proposals must
  remain. The original 1 CPU / 2 GiB whole-machine assertion in `test_core.py` is intact.
- `test_full_capacity_sweep_presets_and_auto` and its independent arithmetic helper:
  check every accepted group against its constraint; check every dropped group for
  exact preservation and a reason. Normal validation must accept the returned subset.
  Counts now refer to unique hardware/preset cases, not duplicate entry-point calls.
- `test_observed_scalar_controls_roundtrip_and_metadata_untouched`: removes the 50%
  fixture workaround, uses the original 90% comp cache with 128 GiB RAM, verifies the
  147.20 / 128.00 GiB warning, rejects an unconfirmed Restore, and restores all original
  values exactly after confirmation. Existing metadata preservation assertions remain.
- `StartupTests.run_startup` helper: patches `usable_cpus`, making the existing startup
  tests independent of the host affinity. New tests cover a non-default initial thread
  count, a one-CPU limit, helper arithmetic, and hardware detection using the helper.

Existing Qt tests are unchanged. Two new Qt tests cover partial-block status and the
existing over-limit Restore confirmation flow.

## Sweep accounting

Seed 20261115 covers every integer RAM size 8..1024 GiB, unknown VRAM and each integer
VRAM size 4..48 GiB. CPU counts are sampled deterministically across 2..128; disk free
space includes 5 and 4000 decimal GB endpoints and deterministic intermediate samples.

46,782 unique hardware scenarios x 2 presets = **93,564 hardware/preset cases**.
Each case checks both worker-estimate states, for **187,128 estimate-state variants**.
Calling recommendations and preset loading does not double either count.

Blocked hardware/preset cases, when at least one estimate state drops that group:

| Reason | Cases |
| --- | ---: |
| RAM | 1,531 |
| GPU | 2,034 |
| Disk | 31,342 |
| All groups | 0 |

Reason counts overlap and must not be summed. The dedicated 2 GiB regression covers
whole-machine rejection outside this 8..1024 GiB sweep.

Seed 51217 adds **512 random current/previous Restore pairs**. All confirmed Restores
succeed. Exactly 207 restored states exceed RAM and have the numeric combined-RAM
warning; 305 are within RAM and have no combined-RAM warning. Other advisory warnings,
such as multiple-worker warnings, can still be present. All warnings require explicit
acceptance. Failed unconfirmed calls preserve current values.

Seed 71517 adds **4,096 unknown-capacity input cases** (varying current settings, not
4,096 distinct detected hardware configurations). No affected value increases.

Additional tests check group-specific GPU rejection and successful CPU/RAM/GPU Apply
with low disk space and oversized existing disk fields left unchanged.

## Reproduce

```
PYTHONPATH=/tmp/npa-qt python -m unittest discover -s tests -v
```

The production code, core tests and sweeps use the standard library. PySide6 is only
needed for the existing offscreen Qt tests. The recorded Qt run uses PySide6 6.8.3.
PySide2 / Nuke 15 UI execution was not tested. Nuke APIs are simulated; this is not a
native Nuke runtime test. The Nuke 15 round-trip uses its observed knob schema.

## Final test result

121 tests passed in 87.798 seconds, no failures, errors or skips.
Full output: `restore-groups-tests-full.txt`.
