# Diagnostics privacy patch

The final merged export is passed once through `redact_diagnostics` immediately before
serialization. `ui.py` changes only inside `_export`: import the redactor and pass its
return value to `json_bytes`. No layout or safety behavior changed.

The redactor copies its input, scrubs collected user/home/computer identities including
separator and percent-encoding variants, reduces folder paths, removes GPU UUIDs and
replaces the Preferences schema with its count. Explicit developer calls can retain
the schema using `include_schema=True`; its strings are still scrubbed. Hardware model,
OS, Nuke version, numeric values and structural keys remain. Generic identity names
are deliberately excluded to preserve ordinary support terminology.

The Windows short-home API is guarded and uses GetShortPathNameW. Actual Windows API
execution was not tested on this Linux host. Synthetic short names are covered.
Code inspection found GPU UUID production only in hardware detection; device matching
uses names, and no code reads the exported UUID. Internal detection remains unchanged.

README and Persian guide changes replace only the diagnostics privacy sentence.
No existing diagnostic test assertion was changed. Six stdlib privacy tests and one
real offscreen export-flow test were added. The sample comes from that FakeNuke export
flow with synthetic names, a synthetic GPU, and synthetic hardware specifications.

Final verification: 128 tests passed in 45.989 seconds, no failures or skips.
Qt execution used PySide6 6.8.3 offscreen. PySide2 and a licensed Nuke session were not
tested. Every Python source passes Python 3.7 grammar parsing. No runtime dependency
was added. Full test output is in privacy-tests-final.txt.

This patch is against the local code at the start of the diagnostics privacy task.
Nothing was pushed to GitHub. The export is redacted, not a guarantee of anonymity.
