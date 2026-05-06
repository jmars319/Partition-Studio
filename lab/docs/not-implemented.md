# Not Implemented Yet

The project intentionally does not implement these items yet:

- Real destructive partition mutation.
- Real NTFS shrink, move, or grow operations.
- Windows VHDX mutation beyond create, inspect, reset, and guarded refusal.
- Crash recovery after an interrupted real move.
- BitLocker or encrypted-volume handling.
- Dirty NTFS repair.
- VM orchestration.
- GUI or app frontend.
- Production safety guarantees.

The next implementation step should be to extend inspection so real image layouts can be normalized into the same JSON shape as the mock fixtures. Only after that should real image mutation be considered.
