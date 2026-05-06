#!/usr/bin/env python3
"""Plan the target C/E operation against a mock or inspected layout JSON."""

from __future__ import annotations

import argparse
import sys

from partitionlab_common import (
    DEFAULT_MIN_SOURCE_FREE_AFTER_BYTES,
    LayoutError,
    human_bytes,
    load_json,
    parse_size,
    plan_operation,
    print_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Model the operation queue for expanding C by taking space from E. This script does not write changes."
    )
    parser.add_argument("--layout", required=True, help="Path to a tenra Partition Lab layout JSON fixture.")
    parser.add_argument("--increase-c", default="40G", help="Amount to add to C. Binary units are used; default: 40G.")
    parser.add_argument("--target", default="C", help="Target partition label. Default: C.")
    parser.add_argument("--source", default="E", help="Source partition label. Default: E.")
    parser.add_argument(
        "--min-source-free-after",
        default=str(DEFAULT_MIN_SOURCE_FREE_AFTER_BYTES),
        help="Minimum free bytes that must remain on the source partition. Default: 1GiB.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        layout = load_json(args.layout)
        increase = parse_size(args.increase_c)
        min_free = parse_size(args.min_source_free_after)
        plan = plan_operation(layout, increase, args.target, args.source, min_free)
    except (OSError, ValueError, LayoutError) as exc:
        parser.error(str(exc))

    if args.json:
        print_json(plan)
    else:
        print(f"Scenario: {plan.get('scenario')}")
        print(f"Plan status: {plan['plan_status']}")
        print(f"Increase {args.target}: {human_bytes(plan['input']['increase_bytes'])}")
        if plan["warnings"]:
            print("Warnings:")
            for warning in plan["warnings"]:
                print(f"  - {warning}")
        if plan["blockers"]:
            print("Blockers:")
            for blocker in plan["blockers"]:
                print(f"  - {blocker['id']}: {blocker['message']}")
        print("Operation queue:")
        for operation in plan["operations"]:
            write_marker = "writes" if operation["writes"] else "read-only"
            print(f"  {operation['step']}. {operation['action']} [{operation['status']}, {write_marker}]")

    return 0 if plan["plan_status"] == "ready" else 2


if __name__ == "__main__":
    sys.exit(main())
