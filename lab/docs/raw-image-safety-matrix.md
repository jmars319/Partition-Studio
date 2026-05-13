# Raw Image Safety Matrix

The pure-Python lab path is safe-to-test only for disposable raw images under
`test-images/` and per-run work copies under `runs/`.

## Scenario Presets

`scripts/create_image.py --scenario <name>` supports these local presets:

| Scenario | Expected result |
| --- | --- |
| `normal-c-e-layout` | Raw geometry command plan is ready. |
| `gpt-layout` | Same geometry shape as the normal C/E GPT scenario. |
| `e-has-insufficient-free-space` | Planner blocks with `source-free-insufficient`. |
| `mbr-layout` | Command plan blocks with `partition-table-not-gpt`. |
| `non-adjacent-free-space` | Planner blocks with `partition-adjacency`. |
| `unaligned-layout` | Layout validation blocks with `layout-invalid`. |
| `dirty-filesystem-placeholder` | Planner blocks with `source-filesystem-state`. |
| `encrypted-filesystem-placeholder` | Planner blocks with `source-encrypted`. |
| `interrupted-operation-placeholder` | Planner blocks with `operation-state`. |
| `corrupted-payload-marker` | Manifest validation blocks with `payload-marker-hash-mismatch`. |
| `malformed-manifest` | Inspection refuses before layout normalization. |
| `missing-manifest` | Inspection refuses before layout normalization. |
| `too-large-requested-expansion` | Planner blocks with `source-free-insufficient`. |

Missing manifests are tested by deleting the generated
`.raw.img.manifest.json` sidecar before inspection.

Run the matrix with:

```bash
scripts/run_scenario_batch.py --json
```

The batch runner emits `partition-lab.batch-report.v1` under `runs/`, including
scenario statuses, blocker IDs, artifact paths, optional `sgdisk`/`qemu-img`
checks, geometry-run outputs, and source fingerprint preservation.

## Optional Mac Validation

When installed, `sgdisk` and `qemu-img` add independent checks:

```bash
scripts/gpt_cross_check.py --image test-images/normal-c-e-layout.raw.img --json
scripts/qemu_image_check.py --image test-images/normal-c-e-layout.raw.img --json
```

`scripts/vm_plan.py --image ... --json` creates a cloned VM work image and a
`partition-lab.vm-plan.v1` command plan for manual GParted Live comparison. It
does not boot QEMU or automate GParted.

## Interruption Simulation

`scripts/run_geometry_operation.py` accepts:

```bash
--simulate-interruption snapshot
--simulate-interruption byte-move
--simulate-interruption gpt-rewrite
--simulate-interruption manifest-update
--simulate-interruption verification
```

Interrupted runs return `partition-lab.geometry-run.v1` with `status: fail`,
`failure_class`, `preflight`, `postflight`, and preserved artifact paths. Work
manifests are marked unsafe when a work image exists.

## Artifact Imports

The desktop app can import these read-only lab artifacts:

- `partition-lab.capabilities.v1`
- `partition-lab.command-plan.v1`
- `partition-lab.geometry-run.v1`
- `partition-lab.verify.v1`
- `partition-lab.batch-report.v1`
- `partition-lab.vm-plan.v1`

The app displays them for review only. It does not execute lab scripts.
