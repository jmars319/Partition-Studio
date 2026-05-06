# Windows Compatibility

Windows is the primary compatibility target.

Use these scripts on Windows:

- `scripts\start-ui.ps1`
- `scripts\inspect-layout.ps1`
- `scripts\plan-operation.ps1`
- `scripts\verify-layout.ps1`
- `scripts\smoke-test.ps1`
- `scripts\create-test-image.ps1`
- `scripts\reset-test-image.ps1`
- `scripts\inspect-image.ps1`
- `scripts\run-destructive-image-operation.ps1`

The shared planner and verifier are Python scripts. The PowerShell wrappers exist so day-to-day commands work naturally from Windows PowerShell or PowerShell 7.

The easiest way to explore the lab is the local browser dashboard:

```powershell
.\scripts\start-ui.ps1 -Open
```

It runs at `http://127.0.0.1:8765/` and does not perform destructive actions.

The Windows real-image path uses VHDX:

- Images are created only under `test-images\`.
- `diskpart` creates and attaches the virtual disk.
- Partitions are formatted as NTFS when `-NoFormat` is not supplied.
- Volumes are labeled `C` and `E`.
- Temporary drive letters are used only while synthetic data is written.
- The VHDX is detached at the end.

Administrator PowerShell is required for VHDX creation, formatting, and read-only VHDX inspection because those operations use Windows disk APIs.

The scripts refuse Windows physical disk paths such as `\\.\PhysicalDrive0`. Real destructive mutation is not implemented.

macOS development remains supported for mock planning, verification, and portable raw-image creation:

```powershell
.\scripts\create-raw-image.ps1 --scenario normal-c-e-layout
```

or:

```bash
scripts/create_image.py --scenario normal-c-e-layout
```
