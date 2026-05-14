#!/usr/bin/env python3
"""Print or manually launch a GParted Live VM plan."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from partitionlab_common import print_json


SCHEMA_VM_LAUNCH = "partition-lab.vm-launch.v1"


def load_vm_plan(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("schema") != "partition-lab.vm-plan.v1":
        raise ValueError("expected partition-lab.vm-plan.v1")
    return plan


def build_launch_result(plan_path: Path, launch: bool, acknowledged: bool) -> dict:
    plan = load_vm_plan(plan_path)
    command = list(plan.get("qemu_command") or [])
    blockers = list(plan.get("blockers") or [])
    if plan.get("status") != "ready":
        blockers.append({"id": "vm-plan-not-ready", "message": "VM plan is not ready"})
    if not command:
        blockers.append({"id": "qemu-command-missing", "message": "VM plan has no QEMU command"})
    if launch and not acknowledged:
        blockers.append({"id": "launch-acknowledgement-missing", "message": "launch requires explicit acknowledgement"})

    launched = False
    if launch and acknowledged and not blockers:
        subprocess.Popen(command)
        launched = True

    return {
        "schema": SCHEMA_VM_LAUNCH,
        "status": "launched" if launched else "printed" if not blockers else "blocked",
        "plan_path": str(plan_path),
        "plan_id": plan.get("plan_id"),
        "blockers": blockers,
        "qemu_command": command,
        "execution": {
            "launched": launched,
            "requires_acknowledgement": True,
            "automates_gparted": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print or launch a GParted Live VM plan.")
    parser.add_argument("--plan", required=True, help="partition-lab.vm-plan.v1 JSON file.")
    parser.add_argument("--launch", action="store_true", help="Actually launch QEMU.")
    parser.add_argument(
        "--i-understand-this-launches-qemu",
        action="store_true",
        help="Required with --launch. This still does not automate GParted.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = build_launch_result(Path(args.plan), args.launch, args.i_understand_this_launches_qemu)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.json:
        print_json(result)
    else:
        print(f"Status: {result['status']}")
        print("Command:")
        print(" ".join(result["qemu_command"]))
        if result["blockers"]:
            print(f"Blockers: {', '.join(item['id'] for item in result['blockers'])}")
    return 0 if result["status"] in {"printed", "launched"} else 2


if __name__ == "__main__":
    sys.exit(main())
