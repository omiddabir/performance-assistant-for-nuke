# 0.5.0 preview — verification

99 automated tests passed with Python 3.12 and PySide6-Essentials. Qt widgets run
in offscreen mode against a simulated Nuke API; no licensed Nuke is installed in
the build environment. Python sources also parse with Python 3.7 grammar.

Coverage includes:
- Exact Nuke 15.1v2 native names/types and vector rejection.
- Non-iterable GlobalsEnvironment, startup restoration and version isolation.
- Native/state paired save, failed writes, conflicts, backup and recovery.
- ApplicationSettings Worker adapter requiring installed source evidence.
- Worker apply/restore, rejected writes, coordinated journal recovery, active
  writer refusal, committed cleanup and refusing unrelated external changes.
- Coupled CPU/RAM/GPU/disk planning ceilings and unknown capacity handling.
- Worker RAM estimates, CPU-only scaling and conservative GPU recommendations.
- 35 Unicode custom presets saved/reloaded, rename/delete, built-in protection,
  stale file conflict, and preserving built-in automatic defaults after deletion.
- Real Qt preset creation/rename/delete, saved RAM estimate, stale out-of-budget
  profile displayed without clamping and rejected on Apply.
- Deferred Apply/Restore, render guard, confirmation cancel, double-click guard,
  diagnostics Save mode and no write on cancel.

Home, Cache and Frame Server layout screenshots inspected. Screenshots are local
QA artifacts, not bundled with the plugin. No external Qt packages are required
by users: Nuke supplies PySide2 or PySide6.

Native validation still required:
- New Worker count persists in Preferences after full Nuke restart.
- Source-evidence adapter on each target version, especially Nuke 17.
- PySide2 widget execution in Nuke 13–15.
- Native disk/cache units and limits across supported maintenance versions.
- Representative shot timings and peak RAM/VRAM; no speedup claim is made.

Save/restart persistence was observed on Nuke 15. This evidence
applies to the previous release, not to every new 0.4.0 path.
Focus background renders and Export render limits are deliberately not mapped;
use native Preferences for them. Diagnostic schema/key candidates remain read-only.

0.5.0 added checks for read-only/full-precision hardware, Auto without any prompt,
Undo auto without native writes, no-op OK without save/confirmation, unknown GPU
memory isolation, and read-only playback diagnostics excluding nonnumeric values.
Home and Cache screenshots inspected with the real Qt Fusion dark palette.
The independent playback-cache setting still needs a verified native mapping.
