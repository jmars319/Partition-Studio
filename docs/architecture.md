# Architecture

tenra Partition starts as a read-only planner, simulator, and integrated lab harness.

## Modules

- `src/domain`: shared disk, partition, filesystem, operation, safety, and validation types.
- `src/safety`: safety checks for filesystem support, mounted/encrypted/dirty flags, partition table support, alignment, adjacency, and shrink capacity.
- `src/planner`: workflow-specific planner for giving space from `E:` to `C:`.
- `src/simulation`: in-memory operation application and final layout validation.
- `src/io`: lab JSON import and tenra Partition export helpers.
- `src-tauri`: Rust Tauri shell. Execution is explicitly disabled.
- `lab`: integrated validation harness for fixtures, raw images, Windows VHDX scripts, inspection, smoke tests, and guarded destructive-mode refusal.

## Scanner Abstraction

The current scanner input is mock JSON with schema `partition-lab.disk-layout.v1`.
The schema name is kept for compatibility with existing fixtures even though the
harness now lives inside this repo.

Future adapters should be added in this priority order:

- Integrated lab JSON output
- Windows PowerShell Storage module
- Linux `lsblk`, `parted`, and `sgdisk`
- macOS `diskutil`

No adapter in this app runs real disk commands today.

## Execution Boundary

The UI can produce operation plans and reports, and the simulator can apply operations to an in-memory model. There is no command that writes to a disk. Execution is blocked until the integrated lab harness can test equivalent operations against disposable disk images.

## Windows Compatibility Rules

- Keep development commands portable across PowerShell, Command Prompt, Git Bash, and POSIX shells.
- Do not add shell scripts that depend on `/bin/sh`, Bash-only syntax, `rm`, `cp`, or Unix path separators.
- Keep file paths inside code as imported modules, URLs, or Tauri APIs rather than hard-coded absolute paths.
- Any future scanner or executor backend must isolate Windows-specific code behind an adapter boundary.
- Windows must remain the primary CI signal before any disk-operation feature is considered.
