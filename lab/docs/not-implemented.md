# Not Implemented Yet

The project intentionally does not implement these items yet:

- Real destructive partition mutation.
- Real NTFS shrink, move, or grow operations.
- Windows VHDX mutation beyond create, inspect, reset, and guarded refusal.
- Physical disk mutation of any kind.
- Crash recovery after an interrupted real move.
- BitLocker or encrypted-volume handling.
- Dirty NTFS repair.
- Automated VM boot/control or GParted GUI operation.
- UI-triggered local script execution.
- Production safety guarantees.

The current lab can normalize disposable raw image layouts and run geometry-only
mutation against work copies. The next implementation step is real NTFS
shrink/grow validation in a disposable VM or Windows-admin VHDX path. The macOS
lab can now generate `sgdisk`, `qemu-img`, batch, and GParted Live VM-plan
artifacts, but those artifacts still do not make write-mode NTFS execution
available by themselves. Only after real filesystem validation should real
mutation be considered.
