# 0.6.0-preview

- Shared memory checks account for comp cache, timeline, system reserves and Frame Server workers together. Extra workers require a user-confirmed memory estimate.
- Restore warns and asks for confirmation before returning to over-limit settings. Auto keeps useful CPU, RAM and GPU suggestions when another resource group cannot fit. Startup and hardware detection use the same available CPU count.
- Shared support diagnostics redact identities and folder paths, remove GPU UUIDs and omit the full Preferences list by default.

Author testing covers UI launch and Preferences saving on Windows Nuke 15.1 and 17.1. Other versions are untested. No performance improvement is claimed.
