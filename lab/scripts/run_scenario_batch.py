#!/usr/bin/env python3
"""Run the disposable raw-image scenario matrix and emit one batch report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discover_capabilities import discover_capabilities
from partitionlab_common import PROJECT_ROOT, TEST_IMAGES_DIR, path_is_under, print_json
from qemu_image_check import image_fingerprint, qemu_image_check


SCHEMA_BATCH_REPORT = "partition-lab.batch-report.v1"
RUNS_DIR = PROJECT_ROOT / "runs"
SCRIPTS_DIR = Path(__file__).resolve().parent


BASE_CREATE_ARGS = {
    "--disk-size": "128MiB",
    "--c-size": "32MiB",
    "--e-size": "64MiB",
    "--c-used": "16MiB",
    "--e-used": "8MiB",
    "--min-source-free-after": "4MiB",
}

DEFAULT_INCREASE = "8MiB"

SCENARIOS: list[dict[str, Any]] = [
    {"name": "normal-c-e-layout"},
    {"name": "gpt-layout"},
    {"name": "e-has-insufficient-free-space", "create_args": {"--e-used": "54MiB"}},
    {"name": "mbr-layout", "create_args": {"--partition-table": "mbr"}},
    {"name": "non-adjacent-free-space", "create_args": {"--layout": "non-adjacent"}},
    {"name": "unaligned-layout", "create_args": {"--layout": "unaligned"}},
    {"name": "dirty-filesystem-placeholder", "create_args": {"--e-filesystem-state": "dirty"}},
    {"name": "encrypted-filesystem-placeholder", "create_args": {"--e-encrypted": None}},
    {"name": "interrupted-operation-placeholder", "create_args": {"--operation-state": "interrupted-move"}},
    {"name": "malformed-manifest", "create_args": {"--malformed-manifest": None}},
    {"name": "missing-manifest", "delete_manifest": True},
    {"name": "corrupted-payload-marker", "create_args": {"--corrupt-payload-marker": None}},
    {"name": "too-large-requested-expansion", "increase": "96MiB"},
    {"name": "primary-gpt-header-corrupt"},
    {"name": "backup-gpt-header-corrupt"},
    {"name": "gpt-entry-crc-mismatch"},
    {"name": "overlapping-partitions"},
    {"name": "truncated-image"},
    {"name": "manifest-sector-size-mismatch"},
    {"name": "manifest-disk-size-mismatch"},
    {"name": "manifest-partition-bounds-mismatch"},
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def blocker(blocker_id: str, message: str) -> dict[str, str]:
    return {"id": blocker_id, "message": message}


def run_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script), *args],
        check=False,
        text=True,
        capture_output=True,
    )


def create_args_for_scenario(scenario: dict[str, Any], image: Path) -> list[str]:
    merged = dict(BASE_CREATE_ARGS)
    merged.update(scenario.get("create_args", {}))
    args = ["--scenario", scenario["name"], "--output", str(image), "--force"]
    for key, value in merged.items():
        args.append(key)
        if value is not None:
            args.append(str(value))
    return args


def parse_json_output(result: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def phase(name: str, status: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "status": status, "details": details or {}}


def collect_blockers(plan: dict[str, Any] | None) -> list[dict[str, str]]:
    if not plan:
        return []
    raw_mode = plan.get("modes", {}).get("raw_geometry", {})
    return [blocker(str(item), str(item)) for item in raw_mode.get("blockers", [])]


def scenario_status(phases: list[dict[str, Any]], blockers: list[dict[str, str]], geometry_run: dict[str, Any] | None) -> str:
    if any(item["status"] == "fail" for item in phases):
        return "fail"
    if geometry_run:
        return "pass" if geometry_run.get("status") == "pass" else "fail"
    if blockers:
        return "blocked"
    return "fail"


def run_scenario(
    scenario: dict[str, Any],
    batch_dir: Path,
    batch_id: str,
    run_optional_checks: bool,
    convert_qcow2: bool,
) -> dict[str, Any]:
    name = scenario["name"]
    scenario_dir = batch_dir / name
    scenario_dir.mkdir(parents=True, exist_ok=True)
    image = TEST_IMAGES_DIR / f"{batch_id}-{name}.raw.img"
    manifest = image.with_suffix(image.suffix + ".manifest.json")
    increase = scenario.get("increase", DEFAULT_INCREASE)
    phases: list[dict[str, Any]] = []
    blockers: list[dict[str, str]] = []
    artifacts: dict[str, str] = {"image": str(image), "manifest": str(manifest)}
    layout: dict[str, Any] | None = None
    command_plan: dict[str, Any] | None = None
    geometry_run: dict[str, Any] | None = None
    source_fingerprint_before: dict[str, Any] | None = None
    source_fingerprint_after: dict[str, Any] | None = None

    create_result = run_script("create_image.py", *create_args_for_scenario(scenario, image))
    phases.append(phase("create", "pass" if create_result.returncode == 0 else "fail", {"stderr": create_result.stderr}))
    if create_result.returncode != 0:
        blockers.append(blocker("create-image-failed", create_result.stderr.strip()))
        return {
            "name": name,
            "status": "fail",
            "blockers": blockers,
            "phases": phases,
            "artifacts": artifacts,
        }

    if scenario.get("delete_manifest"):
        manifest.unlink(missing_ok=True)
        blockers.append(blocker("manifest-missing", "scenario intentionally removes the manifest"))

    source_fingerprint_before = image_fingerprint(image)

    inspect_result = run_script("inspect_image.py", "--image", str(image), "--layout-json")
    layout = parse_json_output(inspect_result)
    phases.append(phase("inspect", "pass" if inspect_result.returncode == 0 and layout else "blocked", {"stderr": inspect_result.stderr}))
    if layout:
        layout_path = scenario_dir / "layout.json"
        write_json(layout_path, layout)
        artifacts["layout"] = str(layout_path)
    else:
        blockers.append(blocker("inspect-refused", inspect_result.stderr.strip()))

    if layout:
        command_result = run_script(
            "command_plan.py",
            "--layout",
            artifacts["layout"],
            "--increase-c",
            increase,
            "--json",
        )
        command_plan = parse_json_output(command_result)
        command_status = "pass" if command_result.returncode == 0 else "blocked"
        phases.append(phase("command-plan", command_status, {"stderr": command_result.stderr}))
        if command_plan:
            command_plan_path = scenario_dir / "command-plan.json"
            write_json(command_plan_path, command_plan)
            artifacts["command_plan"] = str(command_plan_path)
            blockers.extend(collect_blockers(command_plan))
        else:
            blockers.append(blocker("command-plan-failed", command_result.stderr.strip()))

    if run_optional_checks and image.exists():
        sgdisk_result = run_script("gpt_cross_check.py", "--image", str(image), "--json")
        sgdisk_check = parse_json_output(sgdisk_result)
        if sgdisk_check:
            sgdisk_path = scenario_dir / "sgdisk-check.json"
            write_json(sgdisk_path, sgdisk_check)
            artifacts["sgdisk_check"] = str(sgdisk_path)
            phases.append(phase("sgdisk-check", "pass" if sgdisk_check["status"] == "pass" else "blocked"))
        qemu_check = qemu_image_check(image, convert_qcow2, None)
        qemu_path = scenario_dir / "qemu-image-check.json"
        write_json(qemu_path, qemu_check)
        artifacts["qemu_image_check"] = str(qemu_path)
        phases.append(phase("qemu-img-check", "pass" if qemu_check["status"] == "pass" else "blocked"))

    raw_mode = command_plan.get("modes", {}).get("raw_geometry", {}) if command_plan else {}
    if raw_mode.get("status") == "ready":
        geometry_result = run_script(
            "run_geometry_operation.py",
            "--image",
            str(image),
            "--increase-c",
            increase,
            "--i-understand-this-is-geometry-only",
            "--json",
        )
        geometry_run = parse_json_output(geometry_result)
        phases.append(phase("geometry-run", "pass" if geometry_result.returncode == 0 else "fail", {"stderr": geometry_result.stderr}))
        if geometry_run:
            geometry_path = scenario_dir / "geometry-run.json"
            write_json(geometry_path, geometry_run)
            artifacts["geometry_run"] = str(geometry_path)
            artifacts["geometry_run_dir"] = str(geometry_run.get("run_dir"))
        else:
            blockers.append(blocker("geometry-run-failed", geometry_result.stderr.strip()))

    source_fingerprint_after = image_fingerprint(image)
    if source_fingerprint_before["value"] != source_fingerprint_after["value"]:
        blockers.append(blocker("source-mutated", "source image fingerprint changed during batch scenario"))

    status = scenario_status(phases, blockers, geometry_run)
    return {
        "name": name,
        "status": status,
        "increase_c": increase,
        "blockers": blockers,
        "phases": phases,
        "artifacts": artifacts,
        "source_fingerprint": {
            "before": source_fingerprint_before,
            "after": source_fingerprint_after,
            "unchanged": source_fingerprint_before["value"] == source_fingerprint_after["value"],
        },
    }


def build_batch_report(run_optional_checks: bool = True, convert_qcow2: bool = False) -> dict[str, Any]:
    batch_id = f"batch-{utc_stamp()}-{uuid.uuid4().hex[:8]}"
    batch_dir = RUNS_DIR / batch_id
    batch_dir.mkdir(parents=True, exist_ok=False)
    capabilities = discover_capabilities()
    scenarios = [
        run_scenario(scenario, batch_dir, batch_id, run_optional_checks, convert_qcow2)
        for scenario in SCENARIOS
    ]
    summary = {
        "total": len(scenarios),
        "pass": sum(1 for scenario in scenarios if scenario["status"] == "pass"),
        "blocked": sum(1 for scenario in scenarios if scenario["status"] == "blocked"),
        "fail": sum(1 for scenario in scenarios if scenario["status"] == "fail"),
    }
    report = {
        "schema": SCHEMA_BATCH_REPORT,
        "batch_id": batch_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(batch_dir),
        "input": {
            "default_increase_c": DEFAULT_INCREASE,
            "optional_checks": run_optional_checks,
            "convert_qcow2": convert_qcow2,
        },
        "capabilities": capabilities,
        "summary": summary,
        "scenarios": scenarios,
    }
    write_json(batch_dir / "batch-report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the disposable raw-image scenario matrix.")
    parser.add_argument("--skip-optional-checks", action="store_true", help="Skip sgdisk and qemu-img checks.")
    parser.add_argument("--convert-qcow2", action="store_true", help="Convert raw images to qcow2 during qemu-img checks.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.convert_qcow2 and args.skip_optional_checks:
            raise ValueError("--convert-qcow2 requires optional checks")
        if not path_is_under(RUNS_DIR, RUNS_DIR):
            raise ValueError("lab run directory is invalid")
        report = build_batch_report(not args.skip_optional_checks, args.convert_qcow2)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.json:
        print_json(report)
    else:
        print(f"Batch: {report['batch_id']}")
        print(
            "Summary: "
            f"{report['summary']['pass']} pass, "
            f"{report['summary']['blocked']} blocked, "
            f"{report['summary']['fail']} fail"
        )
        print(f"Report: {report['run_dir']}/batch-report.json")
    return 0 if report["summary"]["fail"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
