#!/usr/bin/env python3
"""Regression tests for the tenra Partition disposable-image lab pipeline."""

from __future__ import annotations

import sys
import json
import shutil
import subprocess
import unittest
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = LAB_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from discover_capabilities import discover_capabilities  # noqa: E402
from partitionlab_common import TEST_IMAGES_DIR  # noqa: E402


class CapabilityDiscoveryTests(unittest.TestCase):
    def test_capability_discovery_returns_stable_schema(self) -> None:
        capabilities = discover_capabilities()

        self.assertEqual(capabilities["schema"], "partition-lab.capabilities.v1")
        self.assertIn("host", capabilities)
        self.assertIn("tools", capabilities)
        self.assertIn("modes", capabilities)
        self.assertTrue(capabilities["modes"]["raw_geometry"]["available"])

    def test_missing_tools_are_reported_as_data(self) -> None:
        capabilities = discover_capabilities()

        self.assertIn("blockers", capabilities)
        self.assertIn("warnings", capabilities)
        for name in ("parted", "sgdisk", "ntfsresize", "ntfsclone", "ntfs-3g"):
            self.assertIn(name, capabilities["tools"])
            self.assertIn("available", capabilities["tools"][name])


class RawImageNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        self.created: list[Path] = []
        self.created_dirs: list[Path] = []

    def tearDown(self) -> None:
        for path in self.created:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        for path in self.created_dirs:
            shutil.rmtree(path, ignore_errors=True)

    def image_path(self, name: str) -> Path:
        image = TEST_IMAGES_DIR / f"{name}.raw.img"
        self.created.append(image)
        self.created.append(image.with_suffix(image.suffix + ".manifest.json"))
        return image

    def run_script(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / script), *args],
            check=False,
            text=True,
            capture_output=True,
        )

    def create_image(self, name: str, partition_table: str = "gpt") -> Path:
        image = self.image_path(name)
        result = self.run_script(
            "create_image.py",
            "--scenario",
            name,
            "--output",
            str(image),
            "--disk-size",
            "128MiB",
            "--c-size",
            "32MiB",
            "--e-size",
            "64MiB",
            "--c-used",
            "16MiB",
            "--e-used",
            "8MiB",
            "--min-source-free-after",
            "4MiB",
            "--partition-table",
            partition_table,
            "--force",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return image

    def create_preset_image(self, scenario: str) -> Path:
        image = self.image_path(f"unittest-{scenario}")
        result = self.run_script(
            "create_image.py",
            "--scenario",
            scenario,
            "--output",
            str(image),
            "--force",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return image

    def layout_for_image(self, image: Path) -> dict[str, object]:
        result = self.run_script("inspect_image.py", "--image", str(image), "--layout-json")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def write_layout_file(self, name: str, layout: dict[str, object]) -> Path:
        path = TEST_IMAGES_DIR / f"{name}.layout.json"
        self.created.append(path)
        path.write_text(json.dumps(layout, indent=2), encoding="utf-8")
        return path

    def test_raw_gpt_image_manifest_and_layout_are_planner_compatible(self) -> None:
        image = self.create_image("unittest-normalize-gpt")
        manifest = json.loads(image.with_suffix(image.suffix + ".manifest.json").read_text(encoding="utf-8"))
        layout = self.layout_for_image(image)

        self.assertEqual(manifest["schema"], "partition-lab.image-manifest.v1")
        self.assertEqual(manifest["manifest_version"], 2)
        self.assertEqual(layout["schema"], "partition-lab.layout.v1")
        self.assertEqual(layout["mode"], "raw-geometry")
        self.assertEqual(layout["disk"]["label"], "gpt")
        self.assertEqual([part["label"] for part in layout["disk"]["partitions"]], ["C", "E"])
        self.assertTrue(layout["disk"]["partitions"][1]["payload_marker"]["hash_ok"])

    def test_raw_mbr_image_normalizes_as_blockable_layout(self) -> None:
        image = self.create_image("unittest-normalize-mbr", partition_table="mbr")
        layout = self.layout_for_image(image)

        self.assertEqual(layout["schema"], "partition-lab.layout.v1")
        self.assertEqual(layout["disk"]["label"], "mbr")

    def test_layout_json_refuses_missing_manifest(self) -> None:
        image = self.create_image("unittest-missing-manifest")
        image.with_suffix(image.suffix + ".manifest.json").unlink()

        result = self.run_script("inspect_image.py", "--image", str(image), "--layout-json")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing image manifest", result.stderr)

    def test_scenario_presets_write_expected_manifest_state(self) -> None:
        cases = {
            "e-has-insufficient-free-space": ("E", "free_bytes"),
            "dirty-filesystem-placeholder": ("E", "filesystem_state"),
            "encrypted-filesystem-placeholder": ("E", "encrypted"),
            "interrupted-operation-placeholder": ("disk", "operation_state"),
            "non-adjacent-free-space": ("disk", "non_adjacent"),
            "unaligned-layout": ("disk", "unaligned"),
        }

        for scenario, expectation in cases.items():
            with self.subTest(scenario=scenario):
                image = self.create_preset_image(scenario)
                manifest = json.loads(image.with_suffix(image.suffix + ".manifest.json").read_text(encoding="utf-8"))
                c_part, e_part = manifest["disk"]["partitions"]

                if expectation == ("E", "free_bytes"):
                    self.assertLess(e_part["free_bytes"], manifest["workflow"]["minimum_source_free_after_bytes"])
                elif expectation == ("E", "filesystem_state"):
                    self.assertEqual(e_part["filesystem_state"], "dirty")
                elif expectation == ("E", "encrypted"):
                    self.assertTrue(e_part["encrypted"])
                elif expectation == ("disk", "operation_state"):
                    self.assertEqual(manifest["disk"]["operation_state"], "interrupted-move")
                elif expectation == ("disk", "non_adjacent"):
                    self.assertGreater(e_part["start_sector"], c_part["end_sector"] + 1)
                elif expectation == ("disk", "unaligned"):
                    self.assertNotEqual(c_part["start_sector"] % manifest["disk"]["alignment_sectors"], 0)

    def test_corrupted_payload_and_malformed_manifest_presets_are_available(self) -> None:
        corrupted = self.create_preset_image("corrupted-payload-marker")
        corrupted_layout = self.layout_for_image(corrupted)
        self.assertFalse(corrupted_layout["disk"]["partitions"][1]["payload_marker"]["hash_ok"])

        malformed = self.create_preset_image("malformed-manifest")
        result = self.run_script("inspect_image.py", "--image", str(malformed), "--layout-json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected manifest schema", result.stderr)

    def test_command_plan_has_geometry_steps_and_real_ntfs_dry_run_steps(self) -> None:
        image = self.create_image("unittest-command-plan")
        layout_path = self.write_layout_file("unittest-command-plan", self.layout_for_image(image))

        result = self.run_script(
            "command_plan.py",
            "--layout",
            str(layout_path),
            "--increase-c",
            "8MiB",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        command_plan = json.loads(result.stdout)

        self.assertEqual(command_plan["schema"], "partition-lab.command-plan.v1")
        self.assertEqual(command_plan["modes"]["raw_geometry"]["status"], "ready")
        self.assertGreater(len(command_plan["modes"]["raw_geometry"]["steps"]), 0)
        self.assertTrue(command_plan["modes"]["real_ntfs"]["dry_run_only"])
        self.assertGreater(len(command_plan["modes"]["real_ntfs"]["steps"]), 0)
        self.assertIn("ntfsresize", " ".join(command_plan["modes"]["real_ntfs"]["steps"][1]["command"]))

    def test_geometry_run_mutates_work_copy_and_verifies_result(self) -> None:
        image = self.create_image("unittest-geometry-run")

        result = self.run_script(
            "run_geometry_operation.py",
            "--image",
            str(image),
            "--increase-c",
            "8MiB",
            "--i-understand-this-is-geometry-only",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        run = json.loads(result.stdout)
        self.created_dirs.append(Path(run["run_dir"]))

        self.assertEqual(run["schema"], "partition-lab.geometry-run.v1")
        self.assertEqual(run["status"], "pass")
        self.assertTrue(Path(run["work_image"]).exists())
        self.assertTrue((Path(run["run_dir"]) / "geometry-run.json").exists())
        self.assertTrue(all(check["status"] == "pass" for check in run["checks"]))

    def test_geometry_run_refuses_without_acknowledgement(self) -> None:
        image = self.create_image("unittest-geometry-no-ack")

        result = self.run_script("run_geometry_operation.py", "--image", str(image), "--increase-c", "8MiB", "--json")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("geometry write mode requires", result.stderr)


if __name__ == "__main__":
    unittest.main()
