# tenra Partition

tenra Partition is a desktop partition-management app focused on safe planning,
visualization, simulation, and later controlled execution.

The app is intentionally read-only today. It does not run disk commands and it
does not implement destructive writes. The former Lab harness now lives inside
this repo under `lab/` so planning, simulation, disposable-image tests, and the
desktop program move as one product.

## Windows First

tenra Partition is Windows-compatible from day one, even when developed from macOS.

- Windows is the primary desktop target.
- All npm scripts are shell-portable and work from PowerShell or Command Prompt.
- The Rust backend avoids Unix-only APIs and does not run platform disk commands.
- Future native disk scanning should prioritize Windows PowerShell Storage module output before Linux or macOS adapters.
- CI includes a `windows-latest` gate for TypeScript, planner tests, frontend build, Rust formatting, and Rust tests.

## Current Scope

- Tauri 2 desktop shell
- Rust backend with execution explicitly disabled
- React and TypeScript frontend
- Mock JSON disk scanner abstraction
- Integrated lab-compatible layout import
- Visual lab validation bridge for fixture source, simulation state, and locked execution status
- Operation planner for giving space from `E:` to `C:`
- In-memory simulation engine
- Safety validator and refusal cases
- JSON and human-readable export paths
- Integrated lab harness for fixtures, Windows VHDX creation, raw image creation, inspection, smoke tests, and guarded destructive-mode refusal

## Core Workflow

The first supported workflow handles:

```text
Before:
[C: NTFS, nearly full][E: NTFS, large, mostly unused]

Goal:
Give space from E to C.
```

The planner models the correct operation sequence:

1. Shrink `E:` filesystem
2. Shrink `E:` partition
3. Move `E:` to the right
4. Create adjacent free space immediately after `C:`
5. Expand `C:` partition
6. Expand `C:` filesystem

This is not treated as a simple shrink/extend workflow. Shrinking `E:` creates unallocated space to the right of `E:`, so `C:` cannot use it until `E:` is moved.

## Project Layout

```text
src/          React UI, domain model, planner, simulator, import/export helpers
src-tauri/    Tauri Rust shell and non-execution backend status
fixtures/     App-level mock/import fixtures
lab/          Integrated validation harness formerly kept as the separate Lab repo
docs/         Architecture and safety notes
tests/        Vitest planner, simulator, and refusal tests
```

## Development

These commands are valid on macOS, Windows PowerShell, Windows Command Prompt, and Git Bash:

```sh
npm install
npm run dev
npm run test
npm run check
npm run build
npm run tauri dev
npm run lab:smoke:posix
```

For Windows setup details, see [docs/windows.md](docs/windows.md).

## Lab Harness

The integrated `lab/` directory contains the fixture-driven and disposable-image
test harness. Its scripts still default to mock fixtures, refuse known system
disks, and keep destructive execution locked. It is part of tenra Partition now,
not a separate app.

Useful lab commands:

```sh
npm run lab:smoke:posix
cd lab && scripts/plan_operation.py --layout fixtures/normal-c-e-layout.json --increase-c 40G
cd lab && scripts/start_ui.sh --open
```

On Windows, use the PowerShell scripts in `lab/scripts/`.

## Safety Boundary

tenra Partition does not currently execute partition operations. The Execute
control is disabled and the Rust backend exposes only a disabled execution
status. Real execution must wait until the integrated lab harness can validate
operations against disposable disk images.
