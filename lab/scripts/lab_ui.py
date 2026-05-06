#!/usr/bin/env python3
"""Local browser UI for tenra Partition Lab.

This server is intentionally local-only by default. It exposes mock planning and
verification APIs, but it does not run destructive operations.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from partitionlab_common import (
    DEFAULT_MIN_SOURCE_FREE_AFTER_BYTES,
    PROJECT_ROOT,
    LayoutError,
    load_json,
    parse_size,
    plan_operation,
    print_json,
    safety_assessment,
    simulated_after_layout,
)
from verify_layout import compare_layouts


UI_ROOT = PROJECT_ROOT / "ui"
FIXTURES_ROOT = PROJECT_ROOT / "fixtures"


def fixture_path(name: str) -> Path:
    candidate = (FIXTURES_ROOT / name).resolve(strict=False)
    fixtures_root = FIXTURES_ROOT.resolve()
    try:
        candidate.relative_to(fixtures_root)
    except ValueError as exc:
        raise LayoutError("fixture must be under fixtures/") from exc
    if candidate.suffix.lower() != ".json":
        raise LayoutError("fixture must be a JSON file")
    if not candidate.exists():
        raise LayoutError(f"fixture not found: {name}")
    return candidate


def list_fixtures() -> list[dict[str, Any]]:
    result = []
    for path in sorted(FIXTURES_ROOT.glob("*.json")):
        try:
            data = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        result.append(
            {
                "file": path.name,
                "scenario": data.get("scenario", path.stem),
                "description": data.get("description", ""),
                "disk_label": data.get("disk", {}).get("label"),
                "mode": data.get("mode", "mock"),
            }
        )
    return result


def build_plan(payload: dict[str, Any]) -> dict[str, Any]:
    layout = load_json(fixture_path(str(payload.get("fixture", ""))))
    increase = parse_size(str(payload.get("increase_c", "40G")))
    min_free = parse_size(str(payload.get("min_source_free_after", DEFAULT_MIN_SOURCE_FREE_AFTER_BYTES)))
    return plan_operation(
        layout,
        increase,
        str(payload.get("target", "C")),
        str(payload.get("source", "E")),
        min_free,
    )


def build_verification(payload: dict[str, Any]) -> dict[str, Any]:
    layout = load_json(fixture_path(str(payload.get("fixture", ""))))
    increase = parse_size(str(payload.get("increase_c", "40G")))
    target = str(payload.get("target", "C"))
    source = str(payload.get("source", "E"))
    min_free = parse_size(str(payload.get("min_source_free_after", DEFAULT_MIN_SOURCE_FREE_AFTER_BYTES)))
    plan = plan_operation(layout, increase, target, source, min_free)
    if plan["plan_status"] != "ready":
        return {
            "schema": "partition-lab.verify.v1",
            "scenario": layout.get("scenario"),
            "verification_status": "fail",
            "mode": "mock",
            "input": {
                "target_label": target,
                "source_label": source,
                "increase_bytes": increase,
            },
            "checks": [
                {
                    "name": "planner is ready",
                    "status": "fail",
                    "details": {"blockers": plan["blockers"]},
                }
            ],
        }
    after = simulated_after_layout(layout, increase, target, source)
    return compare_layouts(layout, after, increase, target, source, min_free)


class LabUiHandler(BaseHTTPRequestHandler):
    server_version = "PartitionLabUI/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def send_json(self, data: dict[str, Any] | list[dict[str, Any]], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self.send_json({"error": message}, status)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/fixtures":
                self.send_json({"fixtures": list_fixtures()})
                return
            if parsed.path == "/api/layout":
                query = parse_qs(parsed.query)
                name = query.get("fixture", [""])[0]
                self.send_json(load_json(fixture_path(name)))
                return
            if parsed.path == "/api/safety":
                self.send_json(
                    {
                        "modes": [
                            {"id": "mock", "label": "Mock mode", "status": "active", "writes": False},
                            {"id": "image", "label": "Image mode", "status": "available", "writes": False},
                            {"id": "loop", "label": "Loop-device mode", "status": "guarded", "writes": True},
                            {"id": "vm", "label": "Future VM mode", "status": "not implemented", "writes": False},
                        ],
                        "example_assessment": safety_assessment(PROJECT_ROOT / "test-images" / "example.vhdx"),
                    }
                )
                return
            self.serve_static(parsed.path)
        except (OSError, ValueError, LayoutError, json.JSONDecodeError) as exc:
            self.send_error_json(str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json_body()
            if parsed.path == "/api/plan":
                self.send_json(build_plan(payload))
                return
            if parsed.path == "/api/verify":
                self.send_json(build_verification(payload))
                return
            if parsed.path == "/api/process-demo":
                plan = build_plan(payload)
                self.send_json(
                    {
                        "scenario": plan.get("scenario"),
                        "plan_status": plan["plan_status"],
                        "events": [
                            {
                                "sequence": item["step"],
                                "label": item["action"],
                                "status": item["status"],
                                "writes": item["writes"],
                                "details": item["details"],
                            }
                            for item in plan["operations"]
                        ],
                    }
                )
                return
            self.send_error_json("unknown endpoint", HTTPStatus.NOT_FOUND)
        except (OSError, ValueError, LayoutError, json.JSONDecodeError) as exc:
            self.send_error_json(str(exc))

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        path = (UI_ROOT / relative).resolve(strict=False)
        try:
            path.relative_to(UI_ROOT.resolve())
        except ValueError:
            self.send_error_json("invalid path", HTTPStatus.FORBIDDEN)
            return
        if not path.exists() or not path.is_file():
            self.send_error_json("not found", HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local tenra Partition Lab UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8765, help="Bind port. Default: 8765.")
    parser.add_argument("--open", action="store_true", help="Open the UI in a browser.")
    parser.add_argument("--json", action="store_true", help="Print startup details as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), LabUiHandler)
    url = f"http://{args.host}:{server.server_port}/"
    if args.json:
        print_json({"url": url, "host": args.host, "port": server.server_port})
    else:
        print(f"tenra Partition Lab UI running at {url}")
        print("Press Ctrl+C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping tenra Partition Lab UI.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
