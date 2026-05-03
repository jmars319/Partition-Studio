# Windows Development

Windows is the primary target for tenra Partition Studio. macOS development is supported, but new code should be checked against Windows assumptions before it lands.

## Required Tooling

- Windows 10 or Windows 11
- Microsoft Edge WebView2 Runtime
- Visual Studio 2022 Build Tools with the C++ desktop workload
- Rust installed through `rustup` using the MSVC toolchain
- Node.js 20 or newer
- npm 10 or newer

## Recommended Commands

Run these from PowerShell or Command Prompt:

```powershell
npm install
npm run check
npm run dev
npm run tauri dev
```

`npm run check` runs:

- TypeScript typecheck
- Vitest planner and simulator tests
- Rust formatting check
- Rust tests for the Tauri backend
- Vite production build

## Compatibility Policy

- Windows is the compatibility baseline.
- Do not add Bash-only scripts or Unix-only command assumptions.
- Do not hard-code absolute paths from macOS or Linux.
- Do not call real disk commands from the app.
- Future disk scanning should start with imported tenra Partition Lab JSON, then a Windows PowerShell Storage module adapter.
- Future destructive execution must remain outside this UI until tenra Partition Lab proves operations against disposable disk images.
