# Native compatibility / release acceptance

Target: Nuke 13 through the latest official release checked, **17.1v2**. Target is distinct from verified support.

| Nuke family | Native execution | Persistence after restart | GPU / rendering | Status |
|---|---|---|---|---|
| 13.0 before v10 | Pending | Pending | Compute-thread control disabled for bug 483961 | Partial by design |
| 13.0v10+ / 13.x | Pending | Pending | Pending | Target |
| 14.x | Pending | Pending | Pending | Target |
| 15.1v2 Windows | 0.2.0 Apply verified in field test | 0.2.0 persisted after full restart | Pending | Partial field test |
| Other 15.x | Pending | Pending | Pending | Target |
| 16.x | Pending | Pending | Pending | Target |
| 17.0 / 17.1v2 | Pending | Pending | Pending | Target |

No native Nuke build was installed in the development environment. Windows testing confirmed 0.1.2 opens, reads current values and generates proposals on Windows. A standalone panel reproduced executing() = True inside the button callback, False before/after. Version 0.2.0 defers Apply/Restore with bundled QtCore; native verification remains pending. A 15.1v2 Script Editor dump establishes specific knob identifiers, types and labels, but not raw unit conversions or apply/restart behaviour. The implementation discovers allowed controls at runtime and fails closed on missing or ambiguous controls.

Run the following on each claimed Nuke build and OS. Record the exact version, OS, CPU, RAM, GPU, driver and test comp.

1. Keep existing Preferences backed up; use a disposable user configuration for the first test.
2. Install without overwriting existing startup files. Check menu registration and all tabs at normal and high DPI.
3. Export diagnostics. Compare every detected mapping, type, current value and unit against native Preferences, including hidden/disabled controls. Confirm raw GPU cache units are MB and RAM controls use percentages rather than bytes.
4. Verify logical CPU count, RAM and selected-device VRAM against OS utilities. Exercise unavailable `nvidia-smi`, multiple GPUs, CPU-only mode and unified memory.
5. Run Auto Configure. Confirm native Preferences remain unchanged until Apply & Save. Edit one value, run Auto Configure again and confirm its manual lock.
6. Apply a small, valid set. Verify immediate knob readback and changes in native Preferences. Confirm unrelated preference values survive. Confirm the real compute-thread limit while rendering, not just the Python dictionary value.
7. Close Nuke fully; relaunch normally. Verify compute threads, cache budgets, GPU selection, worker process count and locks. Check diagnostics for loaded-versus-saved differences. Confirm device/worker restart actually takes effect.
8. Launch with `-m 2`; confirm the explicit flag wins over saved thread configuration. Check a headless render receives no tool startup override.
9. Restore previous settings; restart and verify again. Change an unrelated preference between Apply and Restore and confirm it survives.
10. Verify unwritable path, nearly-full cache drive, interrupted save, externally edited preferences, duplicate panel actions and stale lock handling.
11. For performance claims, use identical comp, frame range, resolution, node settings and disk path. Measure cold and warm cache separately, peak RAM/VRAM, render time, Viewer response and stability. Repeat enough to distinguish noise. Never use changed image quality as a speedup.
12. Uninstall and verify other plugins still load and saved native preferences remain intact unless restored explicitly.

Do not mark a row verified until the corresponding native checks have passed. Report test results with the supplied diagnostic JSON, with personal paths removed if needed.


## 0.3.0 acceptance additions

Field tests confirmed 0.2.0 Apply and persistence after full restart on Nuke 15.1v2 Windows. This does not certify the new Qt dialog, presets or Frame Server timeout. Verify all three independently editable profiles after closing/reopening the dialog and Nuke; Save preset must not change native Preferences. Auto must not overwrite the saved profile until Save preset. Confirm short tooltips and the shared footer on every tab. Worker count remains unavailable until its mapping is established.

## 0.4.0 acceptance additions (supersedes the worker status above)

Worker count can now map to the confirmed ApplicationSettings key when matching
installed source evidence is present. Test its native persistence and restart
behavior. Test a custom Unicode preset, RAM estimate persistence, rename/delete,
and a preset whose old number exceeds a newly reduced hardware ceiling.
Confirm cancel/new/save-preset do not write native preferences. Confirm Apply
rejects excessive changed groups and Restore returns the recorded previous values.
Focus/export limits remain unmapped. Nuke 13–17 is a target, not a tested matrix.

On Windows with Nuke 17.1v1 the panel opened and generated recommendations. Full native coverage remains pending.
