# Image Workflow

## Windows VHDX Path

Run PowerShell as Administrator for VHDX creation because Windows requires elevation to create, attach, format, and detach virtual disks with `diskpart`.

Create a disposable VHDX image:

```powershell
.\scripts\create-test-image.ps1 -Scenario normal-c-e-layout
```

Create a larger NTFS-formatted VHDX:

```powershell
.\scripts\create-test-image.ps1 `
  -Scenario normal-c-e-layout `
  -DiskSize 320GiB `
  -CSize 80GiB `
  -ESize 220GiB `
  -CFill 78GiB `
  -EData 80GiB `
  -Force
```

Create a partitioned VHDX without formatting:

```powershell
.\scripts\create-test-image.ps1 -Scenario normal-c-e-layout -NoFormat
```

Inspect the image read-only:

```powershell
.\scripts\inspect-image.ps1 -Image .\test-images\normal-c-e-layout.vhdx
```

Reset the image from scratch:

```powershell
.\scripts\reset-test-image.ps1 -Scenario normal-c-e-layout
```

The script logs every `diskpart` command to `logs/`. It labels the NTFS volumes as `C` and `E`, but it assigns temporary drive letters such as `P:` and `Q:` only while populating synthetic data.

## Portable Raw Path

Create a sparse raw image with a GPT or MBR partition table:

```powershell
.\scripts\create-raw-image.ps1 --scenario normal-c-e-layout
```

or:

```bash
scripts/create_image.py --scenario normal-c-e-layout
```

Raw fallback images are partitioned but not NTFS-formatted. They are useful for parser tests, planner inputs, and future QEMU workflows.

Inspect a raw image:

```bash
scripts/inspect_image.py --image test-images/normal-c-e-layout.raw.img
```

Normalize a raw image for the planner:

```bash
scripts/inspect_image.py \
  --image test-images/normal-c-e-layout.raw.img \
  --layout-json
```

Generate a dry-run command plan:

```bash
scripts/command_plan.py \
  --layout test-images/normal-c-e-layout.layout.json \
  --increase-c 1GiB \
  --json
```

Run geometry-only mutation on a work copy:

```bash
scripts/run_geometry_operation.py \
  --image test-images/normal-c-e-layout.raw.img \
  --increase-c 1GiB \
  --i-understand-this-is-geometry-only \
  --json
```

Geometry-only mode rewrites GPT boundaries and moves raw bytes in the work copy
only. It does not perform real NTFS shrink or grow operations.

Cross-check GPT geometry with `sgdisk` when available:

```bash
scripts/gpt_cross_check.py \
  --image test-images/normal-c-e-layout.raw.img \
  --json
```

Validate raw image metadata with `qemu-img`:

```bash
scripts/qemu_image_check.py \
  --image test-images/normal-c-e-layout.raw.img \
  --json
```

Optionally create a qcow2 copy under `runs/`:

```bash
scripts/qemu_image_check.py \
  --image test-images/normal-c-e-layout.raw.img \
  --convert-qcow2 \
  --json
```

Run the full disposable raw-image matrix:

```bash
scripts/run_scenario_batch.py --json
```

Generate a GParted Live VM comparison plan:

```bash
scripts/vm_plan.py \
  --image test-images/normal-c-e-layout.raw.img \
  --json
```

The VM plan clones the source image under `runs/` and emits the QEMU command for
manual GParted comparison. It does not boot the VM or automate the GParted UI.

Import generated capability, command-plan, geometry-run, verification, batch, or
VM-plan JSON through the desktop app's Lab artifact import to review results
without running scripts from the UI.

## Linux Bash Path

The Bash script remains available for Linux hosts with `parted`, `losetup`, `mkfs.ntfs`, and mount support:

```bash
scripts/create_test_image.sh --scenario normal-c-e-layout
```

Create partitions only:

```bash
scripts/create_test_image.sh --scenario normal-c-e-layout --no-format
```

Reset with:

```bash
scripts/reset_test_image.sh --scenario normal-c-e-layout
```

The Linux path is secondary. Windows VHDX compatibility takes priority.
