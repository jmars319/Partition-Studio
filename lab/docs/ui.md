# Local UI

tenra Partition Lab includes a small local browser dashboard. It is not the future partition manager GUI. It is an operator surface for the lab harness.

Start it on Windows:

```powershell
.\scripts\start-ui.ps1 -Open
```

Start it on macOS or Linux:

```bash
scripts/start_ui.sh --open
```

Default URL:

```text
http://127.0.0.1:8765/
```

The dashboard can:

- List mock layout fixtures.
- Accept operation inputs such as “increase C by 40G using E.”
- Show a visual disk map and partition table.
- Run the mock planner.
- Show blockers, warnings, and operation queue status.
- Run mock verification.
- Animate the planned process steps.
- Display the exact JSON returned by the local API.

The dashboard cannot:

- Modify partitions.
- Attach VHDX images.
- Format filesystems.
- Run destructive operations.

The local API is served by `scripts/lab_ui.py`. It binds to `127.0.0.1` by default and exposes only mock planning, mock verification, fixture inspection, and safety-mode metadata.
