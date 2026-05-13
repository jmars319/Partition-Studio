#!/usr/bin/env python3
"""Discover disposable-image lab capabilities without requiring native tools."""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from partitionlab_common import print_json


SCHEMA_CAPABILITIES = "partition-lab.capabilities.v1"

TOOL_COMMANDS = {
    "parted": ["parted", "--version"],
    "sgdisk": ["sgdisk", "--version"],
    "gdisk": ["gdisk", "-v"],
    "ntfsresize": ["ntfsresize", "--version"],
    "ntfsclone": ["ntfsclone", "--version"],
    "ntfs-3g": ["ntfs-3g", "--version"],
    "qemu-img": ["qemu-img", "--version"],
    "qemu-system-x86_64": ["qemu-system-x86_64", "--version"],
    "b3sum": ["b3sum", "--version"],
    "sha256sum": ["sha256sum", "--version"],
    "shasum": ["shasum", "--version"],
    "powershell": ["powershell", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"],
    "pwsh": ["pwsh", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"],
    "diskpart": ["diskpart"],
}

REAL_NTFS_TOOLS = ("parted", "sgdisk", "ntfsresize", "ntfsclone", "ntfs-3g")
VM_TOOLS = ("qemu-img", "qemu-system-x86_64")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWN_GPARTED_ISO_NAMES = ("gparted-live*.iso", "GParted-live*.iso")


def command_version(command: list[str], timeout_seconds: float = 3.0) -> str | None:
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    if not output:
        return None
    lines = output.splitlines()
    version_line = next((line for line in lines if "version" in line.lower()), lines[0])
    return version_line[:240]


def discover_tool(name: str, command: list[str]) -> dict[str, Any]:
    executable = shutil.which(command[0])
    available = executable is not None
    return {
        "name": name,
        "available": available,
        "path": executable,
        "version": command_version(command) if available and name != "diskpart" else None,
    }


def discover_gparted_iso() -> dict[str, Any]:
    candidates: list[Path] = []
    search_roots = [
        PROJECT_ROOT,
        PROJECT_ROOT.parent,
        PROJECT_ROOT.parent.parent,
    ]
    for root in search_roots:
        for pattern in KNOWN_GPARTED_ISO_NAMES:
            candidates.extend(root.glob(pattern))

    resolved_candidates = sorted({path.resolve(strict=False) for path in candidates})
    selected = resolved_candidates[0] if resolved_candidates else None
    return {
        "available": selected is not None,
        "path": str(selected) if selected else None,
        "candidates": [str(path) for path in resolved_candidates],
    }


def discover_qemu_architecture(tools: dict[str, Any]) -> dict[str, Any]:
    qemu = tools.get("qemu-system-x86_64", {})
    if not qemu.get("available"):
        return {
            "available": False,
            "emulator": "qemu-system-x86_64",
            "host_machine": platform.machine(),
            "guest_machine": "x86_64",
            "notes": ["qemu-system-x86_64 is not installed."],
        }
    host_machine = platform.machine()
    notes = []
    if host_machine.lower() in {"arm64", "aarch64"}:
        notes.append("Host is ARM64; the amd64 GParted Live ISO will run through emulation.")
    else:
        notes.append("Host architecture is compatible with x86_64 VM comparison.")
    return {
        "available": True,
        "emulator": qemu.get("path"),
        "host_machine": host_machine,
        "guest_machine": "x86_64",
        "notes": notes,
    }


def discover_capabilities() -> dict[str, Any]:
    tools = {name: discover_tool(name, command) for name, command in TOOL_COMMANDS.items()}
    platform_name = platform.system().lower()
    powershell_available = tools["powershell"]["available"] or tools["pwsh"]["available"]
    checksum_available = tools["b3sum"]["available"] or tools["sha256sum"]["available"] or tools["shasum"]["available"]
    real_ntfs_missing = [name for name in REAL_NTFS_TOOLS if not tools[name]["available"]]
    vm_missing = [name for name in VM_TOOLS if not tools[name]["available"]]
    gparted_iso = discover_gparted_iso()
    qemu_architecture = discover_qemu_architecture(tools)
    vm_blockers = list(vm_missing)
    if not gparted_iso["available"]:
        vm_blockers.append("gparted-live-iso")

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if real_ntfs_missing:
        blockers.append(
            {
                "id": "real-ntfs-tools-missing",
                "message": f"Real NTFS mutation is unavailable; missing: {', '.join(real_ntfs_missing)}.",
            }
        )
    if vm_blockers:
        warnings.append(
            {
                "id": "vm-tools-missing",
                "message": f"GParted Live VM comparison is unavailable; missing: {', '.join(vm_blockers)}.",
            }
        )
    elif platform.machine().lower() in {"arm64", "aarch64"}:
        warnings.append(
            {
                "id": "vm-emulation-host",
                "message": "GParted Live VM comparison is available but will run the amd64 ISO through emulation.",
            }
        )
    if not checksum_available:
        warnings.append(
            {
                "id": "external-checksum-tools-missing",
                "message": "No external checksum tool was found; Python hashlib remains available for lab manifests.",
            }
        )
    if platform_name == "windows" and not tools["diskpart"]["available"]:
        warnings.append(
            {
                "id": "diskpart-missing",
                "message": "Windows VHDX creation and inspection expect diskpart.",
            }
        )
    if platform_name == "windows" and not powershell_available:
        warnings.append(
            {
                "id": "powershell-missing",
                "message": "Windows wrapper scripts expect Windows PowerShell or PowerShell 7.",
            }
        )

    return {
        "schema": SCHEMA_CAPABILITIES,
        "host": {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "machine": platform.machine(),
            "python": {
                "executable": sys.executable,
                "version": platform.python_version(),
            },
        },
        "modes": {
            "raw_geometry": {
                "available": True,
                "blockers": [],
                "notes": ["Uses Python-only GPT/raw-image logic against disposable work copies."],
            },
            "real_ntfs": {
                "available": not real_ntfs_missing,
                "blockers": real_ntfs_missing,
                "notes": ["Requires native partition and NTFS tools; remains dry-run unless explicitly implemented."],
            },
            "gparted_live_vm": {
                "available": not vm_blockers,
                "blockers": vm_blockers,
                "notes": ["Requires QEMU image tooling and a local GParted Live ISO."],
            },
            "windows_vhdx": {
                "available": platform_name == "windows" and tools["diskpart"]["available"] and powershell_available,
                "blockers": [
                    name
                    for name, missing in (
                        ("windows-host", platform_name != "windows"),
                        ("diskpart", not tools["diskpart"]["available"]),
                        ("powershell", not powershell_available),
                    )
                    if missing
                ],
                "notes": ["Requires Administrator PowerShell for attach, format, and detach operations."],
            },
        },
        "tools": tools,
        "optional_validation": {
            "gpt_cross_check": {
                "available": tools["sgdisk"]["available"],
                "blockers": [] if tools["sgdisk"]["available"] else ["sgdisk"],
            },
            "qemu_image": {
                "available": tools["qemu-img"]["available"],
                "blockers": [] if tools["qemu-img"]["available"] else ["qemu-img"],
            },
            "gparted_live_iso": gparted_iso,
            "qemu_architecture": qemu_architecture,
        },
        "blockers": blockers,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover tenra Partition Lab host capabilities.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    capabilities = discover_capabilities()

    if args.json:
        print_json(capabilities)
    else:
        print(f"Schema: {capabilities['schema']}")
        print(f"Host: {capabilities['host']['platform']} {capabilities['host']['machine']}")
        print("Modes:")
        for name, mode in capabilities["modes"].items():
            status = "available" if mode["available"] else "blocked"
            print(f"  {name}: {status}")
            if mode["blockers"]:
                print(f"    blockers: {', '.join(mode['blockers'])}")
        if capabilities["warnings"]:
            print("Warnings:")
            for warning in capabilities["warnings"]:
                print(f"  - {warning['id']}: {warning['message']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
