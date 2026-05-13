# tenra Partition Lab Harness

The tenra Partition lab harness is the destructive-testing and fixture-testing
area inside the main tenra Partition app. It does not try to be production
software and it does not make the desktop app safe for real disk mutation.

Windows compatibility is a Day 1 requirement. The primary script surface is PowerShell plus Python, and the primary real-image format on Windows is disposable VHDX under `test-images/`. Bash/Linux tooling is optional secondary support.

See [docs/windows-compatibility.md](docs/windows-compatibility.md) for the Windows-specific command surface.
See [docs/gparted-live-reference.md](docs/gparted-live-reference.md) for how the
local GParted Live ISO informs the lab toolchain and staged execution plan.
See [docs/raw-image-safety-matrix.md](docs/raw-image-safety-matrix.md) for the
current pure-Python disposable raw-image scenario matrix.
See [docs/mac-pre-windows-validation.md](docs/mac-pre-windows-validation.md)
for the macOS validation lane before Windows NTFS testing.

The lab models and tests this workflow:

```text
Initial: [C: NTFS, nearly full][E: NTFS, lots of free space]
Goal:    [C: NTFS, larger][E: NTFS, smaller and moved right]
```

The required operation is:

1. Validate the disk.
2. Validate E has enough free space.
3. Shrink the E filesystem.
4. Shrink the E partition.
5. Move E to the right.
6. Expand the C partition.
7. Expand the C filesystem.
8. Verify the result.

## Current Status

Implemented:

- Repository structure for fixtures, scripts, docs, logs, and test images.
- Mock JSON fixtures for the required scenarios.
- A write-free planner for the C/E workflow.
- A mock verification model for expected post-operation geometry.
- Windows PowerShell entrypoints for planning, verification, image creation, inspection, reset, smoke tests, and guarded destructive mode.
- Windows VHDX image creation with `diskpart`, NTFS formatting, and synthetic data population.
- Cross-platform raw image creation under `test-images/` using pure Python.
- Read-only raw image inspection using a pure Python GPT/MBR parser, with optional `parted`, `sgdisk`, and `lsblk` enrichment when available.
- Host capability discovery for native partition, NTFS, VM, Windows VHDX, and checksum tools.
- Optional macOS validation using `sgdisk`, `qemu-img`, `qemu-system-x86_64`, and the local GParted Live ISO when available.
- Normalized `partition-lab.layout.v1` output from disposable raw image inspection.
- Dry-run command plans for real NTFS tooling and executable geometry-only raw image steps.
- Independent GPT cross-check reports with `partition-lab.sgdisk-check.v1`.
- QEMU image validation and optional raw-to-qcow2 conversion reports with `partition-lab.qemu-image-check.v1`.
- Full disposable scenario batch reports with `partition-lab.batch-report.v1`.
- GParted Live VM comparison plans with `partition-lab.vm-plan.v1`, scoped to cloned disposable images only.
- Guarded geometry-only raw image mutation against per-run work copies under `runs/`.
- Geometry verification for final C/E layout, payload marker hashes, and source image preservation.
- Simulated interruption tests for snapshot, byte move, GPT rewrite, manifest update, and verification stages.
- Desktop import and display for capability, command-plan, geometry-run, verification, batch-report, and VM-plan artifacts.
- A local browser dashboard for selecting fixtures, entering operation inputs, viewing disk layout, and watching the mock process queue.
- A guarded destructive-mode entrypoint that performs safety checks, delegates only explicit geometry-only lab mode, and refuses real NTFS mutation.

Not implemented yet:

- Real NTFS shrink, move, or grow execution.
- Physical disk mutation.
- Automated VM boot/control and GParted GUI operation.
- Any polished UI or GUI app.
- Any claim that this is safe for production disks.

## Safety Model

tenra Partition Lab defaults to mock JSON fixtures. The scripts must not operate on real physical disks by default.

Guardrails:

- Test images live under `test-images/`.
- Generated logs live under `logs/`.
- Generated geometry run directories live under `runs/`.
- Windows physical drive paths such as `\\.\PhysicalDrive0` are refused.
- Unix block devices are refused unless explicitly marked as lab devices.
- Known system disks such as `/dev/sda`, `/dev/nvme0n1`, `/dev/vda`, `/dev/xvda`, `/dev/disk0`, and `C:` are denied.
- Future destructive mode requires `-IUnderstandThisIsDestructive` on PowerShell or `--i-understand-this-is-destructive` on Bash.
- Geometry-only raw mode also requires `--geometry-only-lab` on the guarded Bash entrypoint or `-GeometryOnlyLab` on PowerShell.
- The current destructive runner still refuses real NTFS mutation after performing safety checks.

Modes are intentionally separate:

- Mock mode: JSON fixtures only. No disk images.
- Windows image mode: VHDX files under `test-images/`.
- Raw image mode: regular raw image files under `test-images/`.
- Raw geometry mode: lab-only GPT geometry mutation on a work copy, with no real NTFS shrink/grow.
- Loop-device mode: disposable loop devices attached to lab images only.
- VM comparison mode: command-plan scaffold only, against cloned disposable images.

Safe-to-test currently means safe to test the planner, normalization, dry-run command planning, and geometry-only raw image mutation against disposable image work copies. It does not mean safe for physical disks or real NTFS mutation.

## Quick Start

Local browser UI:

```powershell
.\scripts\start-ui.ps1 -Open
```

On macOS/Linux:

```bash
scripts/start_ui.sh --open
```

The UI runs locally at `http://127.0.0.1:8765/` by default. It accepts planner inputs, shows the selected mock disk layout, displays blockers and verification checks, and animates the intended operation queue. It does not run destructive operations.

Windows PowerShell:

```powershell
.\scripts\inspect-layout.ps1 .\fixtures\normal-c-e-layout.json
.\scripts\plan-operation.ps1 --layout .\fixtures\normal-c-e-layout.json --increase-c 40G
.\scripts\verify-layout.ps1 --before .\fixtures\normal-c-e-layout.json --increase-c 40G
.\scripts\smoke-test.ps1
```

The wrappers call the shared Python core, so the same planner and verifier run on Windows, macOS, and Linux.

macOS/Linux shell:

Inspect a fixture:

```bash
scripts/inspect_layout.py fixtures/normal-c-e-layout.json
```

Plan the target operation without writing changes:

```bash
scripts/plan_operation.py --layout fixtures/normal-c-e-layout.json --increase-c 40G
```

Emit the plan as JSON:

```bash
scripts/plan_operation.py --layout fixtures/normal-c-e-layout.json --increase-c 40G --json
```

Verify the mock expected result:

```bash
scripts/verify_layout.py --before fixtures/normal-c-e-layout.json --increase-c 40G
```

Run smoke tests:

```bash
scripts/smoke_test.sh
```

Discover host capabilities:

```bash
scripts/discover_capabilities.py --json
```

Run the full macOS disposable-image matrix:

```bash
scripts/run_scenario_batch.py --json
```

Cross-check a raw GPT image with `sgdisk`:

```bash
scripts/gpt_cross_check.py --image test-images/normal-c-e-layout.raw.img --json
```

Validate a raw image with `qemu-img`:

```bash
scripts/qemu_image_check.py --image test-images/normal-c-e-layout.raw.img --json
```

## Fixtures

The mock fixtures are in `fixtures/`:

- `normal-c-e-layout.json`
- `e-has-insufficient-free-space.json`
- `dirty-filesystem-placeholder.json`
- `encrypted-filesystem-placeholder.json`
- `gpt-layout.json`
- `mbr-layout.json`
- `non-adjacent-free-space.json`
- `interrupted-operation-placeholder.json`

Each fixture describes:

- Disk label, sector size, and alignment.
- Partitions and free regions.
- Start sector, end sector, size, filesystem, mount status, and mock used/free space.
- Mock file lists for validating that E data survives the modeled operation.

## Create A Disposable Image On Windows

The Windows path creates a disposable VHDX, partitions it, formats C and E as NTFS, adds synthetic files, and detaches it. Run PowerShell as Administrator because Windows requires elevation for `diskpart` VHD attach/format operations.

```powershell
.\scripts\create-test-image.ps1 -Scenario normal-c-e-layout
```

By default this creates:

- `test-images\normal-c-e-layout.vhdx`
- GPT partition table
- NTFS volume labeled `C`
- NTFS volume labeled `E`
- Synthetic fill data on C and E

Useful options:

```powershell
.\scripts\create-test-image.ps1 `
  -Scenario normal-c-e-layout `
  -DiskSize 64GiB `
  -CSize 20GiB `
  -ESize 40GiB `
  -CFill 18GiB `
  -EData 8GiB `
  -Force
```

Reset by deterministic rebuild:

```powershell
.\scripts\reset-test-image.ps1 -Scenario normal-c-e-layout
```

Inspect a VHDX read-only:

```powershell
.\scripts\inspect-image.ps1 -Image .\test-images\normal-c-e-layout.vhdx
```

## Create A Portable Raw Image

The raw-image path is cross-platform and does not require administrator privileges. It creates a sparse raw file with GPT or MBR partition entries, but it does not format NTFS.

```powershell
.\scripts\create-raw-image.ps1 --scenario normal-c-e-layout
```

or:

```bash
scripts/create_image.py --scenario normal-c-e-layout
```

Create a blocked scenario:

```bash
scripts/create_image.py --scenario dirty-filesystem-placeholder
```

By default this creates:

- `test-images/normal-c-e-layout.raw.img`
- GPT partition table
- C partition
- E partition
- deterministic payload markers inside C and E
- `test-images/normal-c-e-layout.raw.img.manifest.json`

The legacy Bash image script remains available for Linux hosts with `parted`, `losetup`, `mkfs.ntfs`, and mount support:

```bash
scripts/create_test_image.sh --scenario normal-c-e-layout
```

Inspect a raw image:

```bash
scripts/inspect_image.py --image test-images/normal-c-e-layout.raw.img
```

Normalize a raw image into the planner layout schema:

```bash
scripts/inspect_image.py \
  --image test-images/normal-c-e-layout.raw.img \
  --layout-json
```

Generate a disposable-image command plan:

```bash
scripts/command_plan.py \
  --layout test-images/normal-c-e-layout.layout.json \
  --increase-c 1GiB \
  --json
```

The command plan includes a ready raw-geometry mode when the layout passes
safety checks. Real NTFS mode remains dry-run-only and is blocked unless native
tools such as `parted`, `sgdisk`, `ntfsresize`, `ntfsclone`, and `ntfs-3g` are
available.

Run a geometry-only lab mutation against a work copy:

```bash
scripts/run_geometry_operation.py \
  --image test-images/normal-c-e-layout.raw.img \
  --increase-c 1GiB \
  --i-understand-this-is-geometry-only \
  --json
```

The source image is not modified. The runner writes a per-run directory under
`runs/` containing:

- `before-layout.json`
- `command-plan.json`
- `after-layout.json`
- `verification.json`
- `geometry-run.json`
- the mutated work image and work manifest

Run the full disposable scenario matrix:

```bash
scripts/run_scenario_batch.py --json
```

The batch report writes `partition-lab.batch-report.v1` under `runs/` and
records pass, blocked, and fail counts, blocker IDs, optional `sgdisk`/`qemu-img`
checks, geometry-run artifacts, and source fingerprint preservation.

Generate a GParted Live VM comparison plan:

```bash
scripts/vm_plan.py \
  --image test-images/normal-c-e-layout.raw.img \
  --json
```

This creates a cloned work image under `runs/`, emits a `partition-lab.vm-plan.v1`
artifact, and prints the QEMU command. It does not boot the VM or automate
GParted.

Simulate an interrupted run:

```bash
scripts/run_geometry_operation.py \
  --image test-images/normal-c-e-layout.raw.img \
  --increase-c 1GiB \
  --i-understand-this-is-geometry-only \
  --simulate-interruption gpt-rewrite \
  --json
```

## Guarded Destructive Entrypoint

The future destructive runner exists as a safety guard for real mutation and as
an explicit delegation point for geometry-only raw lab mode.

Windows:

```powershell
.\scripts\run-destructive-image-operation.ps1 `
  -Image .\test-images\normal-c-e-layout.vhdx `
  -IncreaseC 40G `
  -DryRun
```

Write mode would require:

```powershell
-IUnderstandThisIsDestructive
```

Geometry-only raw mode additionally requires:

```powershell
-GeometryOnlyLab
```

macOS/Linux:

```bash
scripts/run_destructive_image_operation.sh \
  --image test-images/normal-c-e-layout.raw.img \
  --increase-c 40G \
  --dry-run
```

Write mode would require:

```bash
--i-understand-this-is-destructive
```

Geometry-only raw mode additionally requires:

```bash
--geometry-only-lab
```

Even with these flags, real NTFS mutation is intentionally refused in this phase.

## Why Moving E Is Required

Windows Disk Management can expand a partition only into unallocated space that is immediately after that partition. If C is followed by E, and E has free space inside its filesystem, that free space is not unallocated disk space after C.

Shrinking E normally creates unallocated space after E, not before E. That still does not help C, because the free space is non-adjacent to C. E must be moved to the right so the unallocated space appears immediately after C. Then C can be expanded into that adjacent space.

## Snapshot Notes

Windows VHDX images are deterministic rebuild targets. Reset them with `reset-test-image.ps1`.

Raw images are useful for portable parsing tests and future QEMU work.

For VM experiments, a raw image can be converted to a qcow2 base and used with disposable overlays:

```bash
qemu-img convert -f raw -O qcow2 test-images/normal-c-e-layout.raw.img test-images/normal-c-e-layout.base.qcow2
qemu-img create -f qcow2 -F qcow2 -b test-images/normal-c-e-layout.base.qcow2 test-images/normal-c-e-layout.work.qcow2
```

Reset the qcow2 overlay by deleting and recreating the `.work.qcow2` file. Direct qcow2 mutation is not implemented yet.
