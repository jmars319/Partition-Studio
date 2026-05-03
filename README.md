# tenra Partition Studio

tenra Partition Studio is a future desktop partition management app focused on safe planning, visualization, simulation, and later controlled execution through a separate tested backend.

The initial app is intentionally read-only. It does not run disk commands and it does not implement destructive writes.

## Windows First

tenra Partition Studio is Windows-compatible from day one, even when developed from macOS.

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
- tenra Partition Lab-compatible layout import
- Operation planner for giving space from `E:` to `C:`
- In-memory simulation engine
- Safety validator and refusal cases
- JSON and human-readable export paths

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
fixtures/     tenra Partition Lab-style JSON fixtures
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
```

For Windows setup details, see [docs/windows.md](docs/windows.md).

## Safety Boundary

tenra Partition Studio does not currently execute partition operations. The Execute control is disabled and the Rust backend exposes only a disabled execution status. Real execution must wait until tenra Partition Lab can validate operations against disposable disk images.
