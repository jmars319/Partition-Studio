# Mac Pre-Windows Validation

This lane is the strongest validation available on the current macOS host before
moving to Windows. It validates disposable raw-image geometry, independent GPT
inspection, QEMU image metadata, batch scenario outcomes, and a manual GParted
Live VM plan. It does not validate real NTFS shrink, grow, or move behavior.

## Tooling

Install optional tools:

```bash
brew install qemu gptfdisk
```

Confirm capability detection:

```bash
scripts/discover_capabilities.py --json
```

Expected macOS result on this host:

- `raw_geometry`: available
- `gparted_live_vm`: available when QEMU and the local GParted Live ISO are present
- `real_ntfs`: blocked until native NTFS tooling exists
- `windows_vhdx`: blocked until running on Windows

## Disposable Matrix

Run the batch matrix:

```bash
scripts/run_scenario_batch.py --json
```

The report schema is `partition-lab.batch-report.v1`. The expected local shape
is pass for normal GPT geometry scenarios, blocked for unsupported or unsafe
scenarios, and zero failed scenarios.

## Independent Checks

Cross-check GPT geometry against `sgdisk`:

```bash
scripts/gpt_cross_check.py --image test-images/normal-c-e-layout.raw.img --json
```

Validate image metadata and optional qcow2 conversion with `qemu-img`:

```bash
scripts/qemu_image_check.py --image test-images/normal-c-e-layout.raw.img --json
scripts/qemu_image_check.py --image test-images/normal-c-e-layout.raw.img --convert-qcow2 --json
```

Generated qcow2 files are allowed only under `runs/`.

## GParted Live VM Plan

Generate a manual comparison plan:

```bash
scripts/vm_plan.py --image test-images/normal-c-e-layout.raw.img --json
```

The VM plan schema is `partition-lab.vm-plan.v1`. The script clones the source
image under `runs/`, emits the QEMU command against the clone, and records manual
comparison steps. It does not boot QEMU, click GParted, or mutate the source
image.

On Apple Silicon, the amd64 GParted Live ISO runs through x86_64 emulation. Treat
that as useful comparison evidence, not a production execution dependency.

## Carry To Windows

Before moving to Windows, preserve or import:

- the latest `partition-lab.capabilities.v1`
- the latest `partition-lab.batch-report.v1`
- representative `partition-lab.geometry-run.v1` and `partition-lab.verify.v1`
- optional `partition-lab.sgdisk-check.v1`, `partition-lab.qemu-image-check.v1`, and `partition-lab.vm-plan.v1`

The Windows phase still owns real VHDX attach/detach, `diskpart`, NTFS
shrink/grow behavior, admin/elevation handling, and any future physical-disk
decision.
