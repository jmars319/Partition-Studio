#!/usr/bin/env python3
"""Create a Windows-phase handoff bundle from Mac lab validation artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from partitionlab_common import PROJECT_ROOT, print_json
from qemu_image_check import image_fingerprint
from run_mac_gate import build_mac_gate


SCHEMA_WINDOWS_HANDOFF = "partition-lab.windows-handoff.v1"
RUNS_DIR = PROJECT_ROOT / "runs"
IMAGE_SUFFIXES = (".img", ".raw", ".qcow2", ".vhd", ".vhdx")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def is_large_image(path: Path) -> bool:
    text = path.name.lower()
    return text.endswith(IMAGE_SUFFIXES) or ".raw." in text


def copy_json_artifact(source: Path, destination_dir: Path, label: str) -> dict[str, Any]:
    destination = destination_dir / f"{label}.json"
    shutil.copy2(source, destination)
    return {"label": label, "source": str(source), "bundle_path": str(destination)}


def fingerprint_or_none(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return image_fingerprint(path)
    except OSError:
        return None


def collect_batch_artifacts(batch_report: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    json_artifacts: list[dict[str, Any]] = []
    excluded_images: list[dict[str, Any]] = []
    for scenario in batch_report.get("scenarios", []):
        name = scenario.get("name", "scenario")
        artifacts = scenario.get("artifacts", {})
        if not isinstance(artifacts, dict):
            continue
        for kind, raw_path in artifacts.items():
            if not raw_path:
                continue
            path = Path(str(raw_path))
            if is_large_image(path):
                excluded_images.append(
                    {
                        "scenario": name,
                        "kind": kind,
                        "path": str(path),
                        "fingerprint": fingerprint_or_none(path),
                    }
                )
            elif path.suffix.lower() == ".json":
                json_artifacts.append({"scenario": name, "kind": kind, "path": str(path)})
    return json_artifacts, excluded_images


def windows_checklist() -> list[dict[str, str]]:
    return [
        {"id": "confirm-admin", "status": "pending", "description": "Open PowerShell as Administrator."},
        {"id": "confirm-disposable-vhdx", "status": "pending", "description": "Use only disposable VHDX images under lab/test-images."},
        {"id": "create-vhdx", "status": "pending", "description": "Create or reset a normal C/E VHDX scenario."},
        {"id": "inspect-vhdx", "status": "pending", "description": "Inspect the VHDX read-only and capture JSON."},
        {"id": "plan-ntfs", "status": "pending", "description": "Generate the Windows NTFS dry-run plan."},
        {"id": "bitlocker-refusal", "status": "pending", "description": "Confirm encrypted volumes stay refused."},
        {"id": "dirty-refusal", "status": "pending", "description": "Confirm dirty filesystems stay refused."},
        {"id": "physical-disk-refusal", "status": "pending", "description": "Confirm physical disks stay refused."},
    ]


def windows_commands() -> list[dict[str, Any]]:
    return [
        {
            "id": "discover-capabilities",
            "description": "Capture Windows host capabilities.",
            "command": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "lab/scripts/smoke-test.ps1"],
        },
        {
            "id": "create-test-vhdx",
            "description": "Create a disposable NTFS-formatted VHDX.",
            "command": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "lab/scripts/create-test-image.ps1", "-Scenario", "normal-c-e-layout", "-Force"],
        },
        {
            "id": "inspect-vhdx",
            "description": "Inspect the disposable VHDX read-only.",
            "command": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "lab/scripts/inspect-image.ps1", "-Image", "lab/test-images/normal-c-e-layout.vhdx"],
        },
        {
            "id": "plan-windows-ntfs",
            "description": "Generate the dry-run Windows NTFS operation plan.",
            "command": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "lab/scripts/plan-windows-ntfs-operation.ps1", "-Image", "lab/test-images/normal-c-e-layout.vhdx", "-IncreaseC", "40G"],
        },
    ]


def build_windows_handoff(include_vm: bool = True) -> dict[str, Any]:
    handoff_id = f"windows-handoff-{utc_stamp()}-{uuid.uuid4().hex[:8]}"
    handoff_dir = RUNS_DIR / handoff_id
    evidence_dir = handoff_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=False)

    mac_gate = build_mac_gate(run_optional_checks=True, build_vm=include_vm)
    mac_gate_path = Path(mac_gate["run_dir"]) / "mac-gate.json"
    batch_path = Path(mac_gate["batch_report"]["path"])
    batch_report = load_json(batch_path)
    copied = [
        copy_json_artifact(mac_gate_path, evidence_dir, "mac-gate"),
        copy_json_artifact(batch_path, evidence_dir, "batch-report"),
    ]

    vm_plan = mac_gate.get("vm_plan")
    if isinstance(vm_plan, dict) and vm_plan.get("path"):
        copied.append(copy_json_artifact(Path(vm_plan["path"]), evidence_dir, "vm-plan"))

    json_artifacts, excluded_images = collect_batch_artifacts(batch_report)
    representative_geometry = next(
        (item for item in json_artifacts if item["kind"] == "geometry_run"),
        None,
    )
    if representative_geometry:
        copied.append(copy_json_artifact(Path(representative_geometry["path"]), evidence_dir, "representative-geometry-run"))

    handoff = {
        "schema": SCHEMA_WINDOWS_HANDOFF,
        "handoff_id": handoff_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "ready-for-windows" if mac_gate["status"] == "ready-for-windows" else "blocked",
        "run_dir": str(handoff_dir),
        "mac_gate": {
            "gate_id": mac_gate["gate_id"],
            "status": mac_gate["status"],
            "source_path": str(mac_gate_path),
            "bundle_path": str(evidence_dir / "mac-gate.json"),
        },
        "batch_report": {
            "batch_id": batch_report["batch_id"],
            "summary": batch_report["summary"],
            "source_path": str(batch_path),
            "bundle_path": str(evidence_dir / "batch-report.json"),
        },
        "representative_geometry_run": representative_geometry,
        "vm_plan": mac_gate.get("vm_plan"),
        "copied_artifacts": copied,
        "excluded_large_artifacts": excluded_images,
        "windows_checklist": windows_checklist(),
        "next_windows_commands": windows_commands(),
        "boundaries": [
            "Real NTFS mutation is not implemented.",
            "Physical disks remain refused.",
            "Windows testing must use disposable VHDX images first.",
        ],
    }
    write_json(handoff_dir / "windows-handoff.json", handoff)
    write_json(handoff_dir / "WINDOWS_NEXT_STEPS.json", {"commands": windows_commands(), "checklist": windows_checklist()})
    return handoff


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a Windows handoff bundle from Mac validation artifacts.")
    parser.add_argument("--skip-vm-plan", action="store_true", help="Do not include a VM plan in the handoff.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        handoff = build_windows_handoff(include_vm=not args.skip_vm_plan)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.json:
        print_json(handoff)
    else:
        print(f"Handoff: {handoff['handoff_id']}")
        print(f"Status: {handoff['status']}")
        print(f"Bundle: {handoff['run_dir']}/windows-handoff.json")
    return 0 if handoff["status"] == "ready-for-windows" else 2


if __name__ == "__main__":
    raise SystemExit(main())
