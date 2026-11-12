# Implementation research

Reviewed 2026-11-05. Primary Foundry sources are listed below. No third-party plugin code was copied.

- [Nuke downloads](https://downloads.foundry.com/nuke) and [17.1v2 release notes](https://learn.foundry.com/hiero/17.1v2/content/release_notes/17.1/nuke_17.1v2_releasenotes.html): establish the latest official version checked for this preview. Future release support requires another review.
- [Python version transition](https://support.foundry.com/hc/en-us/articles/360020635559-Q100610-Nuke-13-and-later-fail-to-launch-with-Python-3-syntax-errors): Nuke 13 starts the Python 3 era; the code targets Python 3.7 syntax and standard-library APIs.
- [PySide transition in Nuke 16+](https://support.foundry.com/hc/en-us/articles/25604028087570-Q100715-How-to-address-Python-PySide-issues-in-Nuke-16): motivates using Nuke's native PythonPanel controls instead of direct Qt imports.
- [Python environment and panel basics](https://learn.foundry.com/nuke/developers/latest/pythondevguide/basics.html): documents mutable `nuke.env['threads']`, environment inspection, native controls and PythonPanel dialogs.
- [Thread-limit guidance](https://support.foundry.com/hc/en-us/articles/208462129-Q100117-Limiting-threads-in-Nuke-with-the-m-flag): explains launch-time thread limits and why maximum thread counts are not always best. The startup hook respects explicit launch arguments.
- [13.0v10 release notes](https://thefoundry.s3.amazonaws.com/products/nuke/releases/13.0v10/Nuke13.0v10_ReleaseNotes.pdf): issue 483961 records a fix for unreliable thread limits. Earlier 13.0 maintenance releases therefore have that control disabled.
- [Preferences reference](https://learn.foundry.com/nuke/content/misc/available_preferences_studio.html): distinguishes compute-related settings, independent Frame Server processes, GPU caches, RAM/disk caches, and restart-sensitive controls. Comp caching does not bound all memory used by a process. Comp playback/paint are subordinate limits rather than additional full RAM pools. Numeric policies in this project are our heuristics, not values prescribed by this page.
- [Saving preferences](https://modosdk.foundry.com/nuke/content/getting_started/using_interface/nuke_studio_environments.html): describes the versioned preference file under the user `.nuke` directory.
- [Node Python API](https://learn.foundry.com/nuke/developers/17.1/pythondevguide/_autosummary/nuke.Node.html): provides preference-node knob access and serialization. The preview serializes the live preference node using Nuke's own API; native reload testing is still required.
- [Startup scripts](https://support.foundry.com/hc/en-us/articles/360003811839-Q100490-What-are-the-init-py-and-menu-py-startup-script-files): supports separation of early initialization from GUI menu registration.

Unresolved empirical questions: exact knob labels/types/units across maintenance builds; preference reload ordering with studio startup scripts; actual worker pool initialization; rendering performance; Windows/macOS hardware probes. These are explicitly represented in the acceptance checklist rather than inferred from unit tests.


## 0.2.0 event-loop correction (2026-11-06)

User-native experiment on 15.1v2: executing() is False outside the panel and True inside its PyScript callback. It is not a sufficient render-only test in that context. Apply/Restore now leave that callback via a single-shot Qt timer, then use the existing guard. Qt documents zero-delay timers on the event loop: https://doc.qt.io/qt-6/qtimer.html . Foundry documents the PySide2-to-PySide6 change at Nuke 16: https://support.foundry.com/hc/en-us/articles/360002448139-Q100465-How-to-load-plugins-for-different-versions-of-Nuke . Native confirmation of the deferred fix is pending.


## 0.3.0 research

Foundry 15.1 Preferences explicitly describes comp cache as a cache limit and comp playback/paint as overlapping sub-limits. The same document states Blink 40% is preferred in most cases and larger values may slow processing. Therefore Comp focused exposes all compute threads without maximizing every cache. Frame Server processes have independent memory costs and require a restart after count changes. Enablement and timeout have observed native knob IDs. No source proving the 15.1v2 worker-count key was found; the release leaves it unavailable and exports read-only candidates for review.

Sources: https://learn.foundry.com/nuke/15.1/content/misc/available_preferences_studio.html ; https://learn.foundry.com/nuke/current/content/comp_environment/rendering/frame_server_renders.html ; https://learn.foundry.com/nuke/developers/13.1/HieroPythonDevGuide/api/api_core.html

## 0.4.0 evidence

Installed Nuke 15.1v2 FnNsFrameServer source confirms the following mapping:
workerCount creates hiero.core.ApplicationSettings and reads
`int(settings.value("frameserver/workercount"))`. The adapter requires this same
source evidence at runtime. The official 15.1 core source documents setValue as
saving application settings, stringifying numeric values:
https://learn.foundry.com/nuke/developers/15.1/HieroPythonDevGuide/_modules/hiero/core.html

Worker restarts and distinctions from export limits:
https://learn.foundry.com/nuke/15.2v1/content/comp_environment/rendering/frame_server_renders.html

Focus/export key names have not been confirmed. They remain untouched rather
than interpreting UI labels as ApplicationSettings keys. Dynamic ceilings and
per-worker estimates are plugin planning policies, not Foundry-certified maxima.


## 0.5.0 CPU and playback distinction

The Foundry developer guide explicitly documents threads as writable and as the
number of threads spawned when rendering:
https://learn.foundry.com/nuke/developers/105/pythondevguide/basics.html
The Nuke 13.0v10 release notes record the fix for setting thread count using -m or
nuke.env['threads'] (ID 483961); the early-13.0 guard is retained.
https://thefoundry.s3.amazonaws.com/products/nuke/releases/13.0v10/Nuke13.0v10_ReleaseNotes.pdf
Playback cache size is the independent timeline Viewer cache, unlike comp playback:
https://learn.foundry.com/nuke/17.0v2/content/misc/available_preferences_studio.html
No authoritative read/write mapping for that timeline setting was found. This
release extends read-only diagnostics and does not invent one.
