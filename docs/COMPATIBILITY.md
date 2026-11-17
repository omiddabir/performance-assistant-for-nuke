# 0.6.0-preview compatibility

| Nuke version | Author testing |
| --- | --- |
| 15.1 (Windows) | UI launches; settings save into Preferences |
| 17.1 (Windows) | UI launches; settings save into Preferences |
| All other versions | Untested |

No Nuke 13 support is claimed. No performance improvement is claimed.
The implementation retains existing version guards; those guards do not certify support.
Automated tests simulate Nuke APIs. Offscreen widget tests use PySide6 only; PySide2 was not tested.
Hardware detection, GPU memory information and exposed controls vary by system.
Independent timeline playback cache and some Frame Server controls have no verified mapping.
Suggestions are estimates; measure worker memory on representative shots.
Stop renders before Apply. GPU and worker changes may require restarting Nuke.
Confirmed Restore can return settings exceeding the current computer's RAM capacity after warning.
Diagnostics are redacted by default but retain hardware models, OS, Nuke version and values.
