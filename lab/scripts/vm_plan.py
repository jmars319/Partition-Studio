#!/usr/bin/env python3
"""Create a safe GParted Live VM comparison plan for a cloned lab image."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discover_capabilities import discover_capabilities
from inspect_image import manifest_path_for_image, parse_raw_partition_table
from partitionlab_common import PROJECT_ROOT, path_is_under, print_json, safety_assessment
from qemu_image_check import image_fingerprint
from run_geometry_operation import copy_sparse_file


SCHEMA_VM_PLAN = "partition-lab.vm-plan.v1"
RUNS_DIR = PROJECT_ROOT / "runs"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def blocker(blocker_id: str, message: str) -> dict[str, str]:
    return {"id": blocker_id, "message": message}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def vm_work_image_path(source_image: Path, plan_dir: Path) -> Path:
    return plan_dir / f"{source_image.stem}.vm-work{source_image.suffix}"


def build_qemu_command(qemu_system: str, iso_path: str, work_image: str, memory: str) -> list[str]:
    return [
        qemu_system,
        "-m",
        memory,
        "-accel",
        "tcg",
        "-boot",
        "d",
        "-cdrom",
        iso_path,
        "-drive",
        f"file={work_image},format=raw,if=virtio",
    ]


def build_vm_plan(image: Path, memory: str = "2048") -> dict[str, Any]:
    image = image.resolve(strict=False)
    capabilities = discover_capabilities()
    qemu_img = capabilities["tools"]["qemu-img"]
    qemu_system = capabilities["tools"]["qemu-system-x86_64"]
    iso = capabilities["optional_validation"]["gparted_live_iso"]
    safety = safety_assessment(image)
    blockers: list[dict[str, str]] = []

    if not safety["under_test_images"]:
        blockers.append(blocker("image-outside-test-images", "source image must be under lab/test-images"))
    if safety["block_device"] or safety["windows_physical_drive"] or safety["denylisted_system_device"]:
        blockers.append(blocker("image-is-device", "refusing block or system device for VM planning"))
    if not image.exists():
        blockers.append(blocker("image-not-found", f"image not found: {image}"))
    if not qemu_img["available"]:
        blockers.append(blocker("qemu-img-missing", "qemu-img is not installed"))
    if not qemu_system["available"]:
        blockers.append(blocker("qemu-system-x86_64-missing", "qemu-system-x86_64 is not installed"))
    if not iso["available"] or not iso.get("path"):
        blockers.append(blocker("gparted-live-iso-missing", "no local GParted Live ISO was found"))

    raw = parse_raw_partition_table(image) if image.exists() else None
    if image.exists() and (not raw or raw.get("partition_table") != "gpt"):
        blockers.append(blocker("source-not-gpt", "GParted VM comparison expects a GPT raw image"))

    plan_id = f"vm-plan-{utc_stamp()}-{uuid.uuid4().hex[:8]}"
    plan_dir = RUNS_DIR / plan_id
    work_image: Path | None = None
    source_fingerprint = image_fingerprint(image) if image.exists() else None
    command: list[str] = []

    if not blockers:
        plan_dir.mkdir(parents=True, exist_ok=False)
        work_image = vm_work_image_path(image, plan_dir)
        if not path_is_under(RUNS_DIR, work_image):
            blockers.append(blocker("work-image-path-refused", "VM work image must stay under lab/runs"))
        else:
            copy_sparse_file(image, work_image)
            source_manifest = manifest_path_for_image(image)
            if source_manifest.exists():
                shutil.copy2(source_manifest, manifest_path_for_image(work_image))
            command = build_qemu_command(str(qemu_system["path"]), str(iso["path"]), str(work_image), memory)

    status = "ready" if not blockers else "blocked"
    result = {
        "schema": SCHEMA_VM_PLAN,
        "plan_id": plan_id,
        "status": status,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "blockers": blockers,
        "source_image": {
            "path": str(image),
            "fingerprint": source_fingerprint,
        },
        "work_image": {
            "path": str(work_image) if work_image else None,
            "manifest": str(manifest_path_for_image(work_image)) if work_image else None,
        },
        "iso": {
            "path": iso.get("path"),
            "candidates": iso.get("candidates", []),
        },
        "host": capabilities["host"],
        "qemu": {
            "qemu_img": qemu_img,
            "qemu_system_x86_64": qemu_system,
            "architecture": capabilities["optional_validation"]["qemu_architecture"],
        },
        "qemu_command": command,
        "steps": [
            {"id": "clone-image", "title": "Use only the cloned VM work image, never the source image."},
            {"id": "boot-gparted-live", "title": "Boot GParted Live with the cloned raw image attached."},
            {"id": "perform-manual-comparison", "title": "Apply or inspect the C/E geometry change manually in GParted."},
            {"id": "inspect-after", "title": "Inspect the cloned image after shutdown and compare it with Tenra lab output."},
        ],
    }
    if plan_dir.exists():
        write_json(plan_dir / "vm-plan.json", result)
        result["run_dir"] = str(plan_dir)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a GParted Live VM comparison plan for a disposable image clone.")
    parser.add_argument("--image", required=True, help="Source raw image under lab/test-images.")
    parser.add_argument("--memory", default="2048", help="QEMU memory in MiB. Default: 2048.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = build_vm_plan(Path(args.image), args.memory)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.json:
        print_json(result)
    else:
        print(f"Plan: {result['plan_id']}")
        print(f"Status: {result['status']}")
        if result["blockers"]:
            print(f"Blockers: {', '.join(item['id'] for item in result['blockers'])}")
        elif result["qemu_command"]:
            print("Command:")
            print(" ".join(result["qemu_command"]))
    return 0 if result["status"] == "ready" else 2


if __name__ == "__main__":
    sys.exit(main())
