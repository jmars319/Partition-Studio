#!/usr/bin/env python3
"""Regression tests for the tenra Partition disposable-image lab pipeline."""

from __future__ import annotations

import sys
import json
import shutil
import subprocess
import unittest
import uuid
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
        image = TEST_IMAGES_DIR / f"{name}-{uuid.uuid4().hex}.raw.img"
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
        path = TEST_IMAGES_DIR / f"{name}-{uuid.uuid4().hex}.layout.json"
        self.created.append(path)
        path.write_text(json.dumps(layout, indent=2), encoding="utf-8")
        return path

    def command_plan_for_image(self, name: str, image: Path, increase: str = "1GiB") -> dict[str, object]:
        layout_path = self.write_layout_file(name, self.layout_for_image(image))
        result = self.run_script("command_plan.py", "--layout", str(layout_path), "--increase-c", increase, "--json")
        self.assertIn(result.returncode, {0, 2}, result.stderr)
        return json.loads(result.stdout)

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
        self.assertEqual(corrupted_layout["manifest_validation"]["status"], "blocked")
        self.assertIn(
            "payload-marker-hash-mismatch",
            {issue["id"] for issue in corrupted_layout["manifest_validation"]["issues"]},
        )

        malformed = self.create_preset_image("malformed-manifest")
        result = self.run_script("inspect_image.py", "--image", str(malformed), "--layout-json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected manifest schema", result.stderr)

    def test_manifest_validation_reports_unsafe_preset_states(self) -> None:
        for scenario, issue_id in (
            ("dirty-filesystem-placeholder", "manifest-filesystem-state"),
            ("encrypted-filesystem-placeholder", "manifest-encrypted"),
            ("interrupted-operation-placeholder", "manifest-operation-state"),
            ("backup-gpt-header-corrupt", "gpt-backup-header-invalid"),
            ("gpt-entry-crc-mismatch", "gpt-entry-crc-mismatch"),
        ):
            with self.subTest(scenario=scenario):
                layout = self.layout_for_image(self.create_preset_image(scenario))
                self.assertEqual(layout["manifest_validation"]["status"], "blocked")
                self.assertIn(issue_id, {issue["id"] for issue in layout["manifest_validation"]["issues"]})

    def test_corrupt_gpt_and_manifest_mismatch_scenarios_refuse_or_block(self) -> None:
        refusal_cases = {
            "primary-gpt-header-corrupt": "no raw GPT/MBR partition table was parsed",
            "truncated-image": "manifest disk size does not match parsed image",
            "manifest-sector-size-mismatch": "manifest sector size does not match parsed image",
            "manifest-disk-size-mismatch": "manifest disk size does not match parsed image",
            "manifest-partition-bounds-mismatch": "partition 2 start_sector does not match parsed image",
        }

        for scenario, message in refusal_cases.items():
            with self.subTest(scenario=scenario):
                image = self.create_preset_image(scenario)
                result = self.run_script("inspect_image.py", "--image", str(image), "--layout-json")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

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
        self.assertIn("gparted_live_vm", command_plan["modes"])

    def test_sgdisk_cross_check_passes_for_valid_gpt_and_blocks_mbr(self) -> None:
        gpt_image = self.create_image("unittest-sgdisk-gpt")
        gpt_result = self.run_script("gpt_cross_check.py", "--image", str(gpt_image), "--json")

        self.assertEqual(gpt_result.returncode, 0, gpt_result.stderr)
        gpt_check = json.loads(gpt_result.stdout)
        self.assertEqual(gpt_check["schema"], "partition-lab.sgdisk-check.v1")
        self.assertEqual(gpt_check["status"], "pass")
        self.assertEqual(
            [(part["number"], part["start_sector"], part["end_sector"]) for part in gpt_check["sgdisk"]["partitions"]],
            [(part["number"], part["start_sector"], part["end_sector"]) for part in gpt_check["python"]["partitions"]],
        )

        mbr_image = self.create_image("unittest-sgdisk-mbr", partition_table="mbr")
        mbr_result = self.run_script("gpt_cross_check.py", "--image", str(mbr_image), "--json")

        self.assertEqual(mbr_result.returncode, 2, mbr_result.stderr)
        mbr_check = json.loads(mbr_result.stdout)
        self.assertEqual(mbr_check["status"], "blocked")
        self.assertIn("sgdisk-invalid-gpt", {item["id"] for item in mbr_check["blockers"]})

    def test_qemu_img_validation_and_qcow2_conversion_are_safe(self) -> None:
        image = self.create_image("unittest-qemu-img")
        run_dir = LAB_ROOT / "runs" / f"unittest-qemu-{uuid.uuid4().hex}"
        self.created_dirs.append(run_dir)
        output = run_dir / "converted.qcow2"

        result = self.run_script(
            "qemu_image_check.py",
            "--image",
            str(image),
            "--convert-qcow2",
            "--qcow2-output",
            str(output),
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        check = json.loads(result.stdout)
        self.assertEqual(check["schema"], "partition-lab.qemu-image-check.v1")
        self.assertEqual(check["status"], "pass")
        self.assertEqual(check["info"]["format"], "raw")
        self.assertEqual(check["conversion"]["status"], "pass")
        self.assertEqual(check["conversion"]["info"]["format"], "qcow2")
        self.assertTrue(check["source_fingerprint"]["unchanged"])

        refused = self.run_script(
            "qemu_image_check.py",
            "--image",
            str(image),
            "--convert-qcow2",
            "--qcow2-output",
            str(TEST_IMAGES_DIR / "refused.qcow2"),
            "--json",
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("qcow2 output must be under", refused.stderr)

    def test_scenario_batch_report_handles_pass_and_blocked_scenarios(self) -> None:
        result = self.run_script("run_scenario_batch.py", "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.created_dirs.append(Path(report["run_dir"]))
        for scenario in report["scenarios"]:
            image = Path(scenario["artifacts"]["image"])
            manifest = Path(scenario["artifacts"]["manifest"])
            self.created.append(image)
            self.created.append(manifest)

        self.assertEqual(report["schema"], "partition-lab.batch-report.v1")
        self.assertEqual(report["summary"]["fail"], 0)
        self.assertGreaterEqual(report["summary"]["pass"], 1)
        self.assertGreaterEqual(report["summary"]["blocked"], 1)
        self.assertTrue((Path(report["run_dir"]) / "batch-report.json").exists())
        statuses = {scenario["name"]: scenario["status"] for scenario in report["scenarios"]}
        self.assertEqual(statuses["normal-c-e-layout"], "pass")
        self.assertEqual(statuses["missing-manifest"], "blocked")
        self.assertEqual(statuses["too-large-requested-expansion"], "blocked")
        self.assertTrue(
            all(
                scenario.get("source_fingerprint", {}).get("unchanged", True)
                for scenario in report["scenarios"]
            )
        )

    def test_vm_plan_clones_only_disposable_images_when_available(self) -> None:
        image = self.create_image("unittest-vm-plan")
        result = self.run_script("vm_plan.py", "--image", str(image), "--json")

        self.assertIn(result.returncode, {0, 2}, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["schema"], "partition-lab.vm-plan.v1")
        if plan["status"] == "ready":
            self.created_dirs.append(Path(plan["run_dir"]))
            self.assertTrue(Path(plan["work_image"]["path"]).exists())
            self.assertNotEqual(Path(plan["work_image"]["path"]), image)
            self.assertIn("qemu-system-x86_64", plan["qemu_command"][0])
            self.assertIn(str(Path(plan["work_image"]["path"])), " ".join(plan["qemu_command"]))
        else:
            self.assertTrue(plan["blockers"])

    def test_mac_gate_reports_ready_for_windows(self) -> None:
        result = self.run_script("run_mac_gate.py", "--skip-vm-plan", "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        gate = json.loads(result.stdout)
        self.created_dirs.append(Path(gate["run_dir"]))
        batch_report = json.loads(Path(gate["batch_report"]["path"]).read_text(encoding="utf-8"))
        self.created_dirs.append(Path(batch_report["run_dir"]))
        for scenario in batch_report["scenarios"]:
            image = Path(scenario["artifacts"]["image"])
            manifest = Path(scenario["artifacts"]["manifest"])
            self.created.append(image)
            self.created.append(manifest)

        self.assertEqual(gate["schema"], "partition-lab.mac-gate.v1")
        self.assertEqual(gate["status"], "ready-for-windows")
        self.assertTrue(gate["checks"]["batch_has_no_failures"])
        self.assertTrue(gate["checks"]["generated_artifacts_ignored"])
        self.assertTrue(all(item["ignored"] for item in gate["ignored_artifacts"]))

    def test_windows_handoff_bundle_excludes_large_images(self) -> None:
        result = self.run_script("create_windows_handoff.py", "--skip-vm-plan", "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        handoff = json.loads(result.stdout)
        self.created_dirs.append(Path(handoff["run_dir"]))
        mac_gate = json.loads(Path(handoff["mac_gate"]["source_path"]).read_text(encoding="utf-8"))
        batch_report = json.loads(Path(handoff["batch_report"]["source_path"]).read_text(encoding="utf-8"))
        self.created_dirs.append(Path(mac_gate["run_dir"]))
        self.created_dirs.append(Path(batch_report["run_dir"]))
        for scenario in batch_report["scenarios"]:
            image = Path(scenario["artifacts"]["image"])
            manifest = Path(scenario["artifacts"]["manifest"])
            self.created.append(image)
            self.created.append(manifest)

        self.assertEqual(handoff["schema"], "partition-lab.windows-handoff.v1")
        self.assertEqual(handoff["status"], "ready-for-windows")
        self.assertTrue(Path(handoff["run_dir"], "windows-handoff.json").exists())
        self.assertTrue(handoff["excluded_large_artifacts"])
        self.assertTrue(
            all(Path(item["bundle_path"]).suffix == ".json" for item in handoff["copied_artifacts"])
        )
        self.assertIn("plan-windows-ntfs", {item["id"] for item in handoff["next_windows_commands"]})

    def test_windows_ntfs_plan_is_dry_run_only_and_refuses_physical_disks(self) -> None:
        image = TEST_IMAGES_DIR / f"future-windows-{uuid.uuid4().hex}.vhdx"
        result = self.run_script(
            "plan_windows_ntfs_operation.py",
            "--image",
            str(image),
            "--increase-c",
            "40G",
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["schema"], "partition-lab.windows-ntfs-plan.v1")
        self.assertEqual(plan["status"], "dry-run-only")
        self.assertFalse(plan["execution"]["enabled"])
        self.assertIn("real-ntfs-mutation-not-implemented", {item["id"] for item in plan["blockers"]})

        refused = self.run_script(
            "plan_windows_ntfs_operation.py",
            "--image",
            r"\\.\PhysicalDrive0",
            "--json",
        )
        self.assertEqual(refused.returncode, 2, refused.stderr)
        refused_plan = json.loads(refused.stdout)
        self.assertEqual(refused_plan["status"], "refused")
        self.assertIn("physical-disk-refused", {item["id"] for item in refused_plan["blockers"]})

    def test_vm_launcher_prints_by_default_and_requires_acknowledgement_to_launch(self) -> None:
        plan_path = TEST_IMAGES_DIR / f"unittest-vm-plan-{uuid.uuid4().hex}.json"
        self.created.append(plan_path)
        plan_path.write_text(
            json.dumps(
                {
                    "schema": "partition-lab.vm-plan.v1",
                    "plan_id": "unittest-vm-plan",
                    "status": "ready",
                    "blockers": [],
                    "qemu_command": ["qemu-system-x86_64", "-version"],
                }
            ),
            encoding="utf-8",
        )

        printed = self.run_script("launch_vm_plan.py", "--plan", str(plan_path), "--json")
        self.assertEqual(printed.returncode, 0, printed.stderr)
        printed_result = json.loads(printed.stdout)
        self.assertEqual(printed_result["schema"], "partition-lab.vm-launch.v1")
        self.assertEqual(printed_result["status"], "printed")
        self.assertFalse(printed_result["execution"]["launched"])

        blocked = self.run_script("launch_vm_plan.py", "--plan", str(plan_path), "--launch", "--json")
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        blocked_result = json.loads(blocked.stdout)
        self.assertEqual(blocked_result["status"], "blocked")
        self.assertIn("launch-acknowledgement-missing", {item["id"] for item in blocked_result["blockers"]})

    def test_command_plan_reports_stable_blockers_for_unsafe_scenarios(self) -> None:
        cases = {
            "mbr-layout": "partition-table-not-gpt",
            "e-has-insufficient-free-space": "source-free-insufficient",
            "non-adjacent-free-space": "partition-adjacency",
            "unaligned-layout": "layout-invalid",
            "overlapping-partitions": "layout-invalid",
            "dirty-filesystem-placeholder": "source-filesystem-state",
            "encrypted-filesystem-placeholder": "source-encrypted",
            "interrupted-operation-placeholder": "operation-state",
            "corrupted-payload-marker": "payload-marker-hash-mismatch",
            "backup-gpt-header-corrupt": "gpt-backup-header-invalid",
            "gpt-entry-crc-mismatch": "gpt-entry-crc-mismatch",
        }

        for scenario, blocker in cases.items():
            with self.subTest(scenario=scenario):
                command_plan = self.command_plan_for_image(f"unittest-plan-{scenario}", self.create_preset_image(scenario))
                raw_mode = command_plan["modes"]["raw_geometry"]
                self.assertEqual(raw_mode["status"], "blocked")
                self.assertIn(blocker, set(raw_mode["blockers"]))

    def test_command_plan_reports_tool_blockers_for_real_ntfs_and_vm_modes(self) -> None:
        command_plan = self.command_plan_for_image("unittest-tool-blockers", self.create_preset_image("normal-c-e-layout"))

        self.assertIn("tool-missing-ntfsresize", set(command_plan["modes"]["real_ntfs"]["blockers"]))
        vm_mode = command_plan["modes"]["gparted_live_vm"]
        if vm_mode["status"] == "blocked":
            self.assertTrue(
                set(vm_mode["blockers"]).issubset(
                    {"tool-missing-qemu-img", "tool-missing-qemu-system-x86_64", "tool-missing-gparted-live-iso"}
                )
            )
        else:
            self.assertEqual(vm_mode["status"], "ready")

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

    def test_geometry_run_simulated_interruptions_preserve_artifacts(self) -> None:
        expected_failure = {
            "snapshot": "preflight-refusal",
            "byte-move": "geometry-failed",
            "gpt-rewrite": "geometry-failed",
            "manifest-update": "geometry-failed",
            "verification": "verification-failed",
        }

        for stage, failure_class in expected_failure.items():
            with self.subTest(stage=stage):
                image = self.create_image(f"unittest-interrupt-{stage}")
                result = self.run_script(
                    "run_geometry_operation.py",
                    "--image",
                    str(image),
                    "--increase-c",
                    "8MiB",
                    "--i-understand-this-is-geometry-only",
                    "--simulate-interruption",
                    stage,
                    "--json",
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                run = json.loads(result.stdout)
                self.created_dirs.append(Path(run["run_dir"]))

                self.assertEqual(run["status"], "fail")
                self.assertEqual(run["failure_class"], failure_class)
                self.assertEqual(run["input"]["simulated_interruption"], stage)
                self.assertTrue(Path(run["run_dir"]).exists())
                self.assertTrue(run["preserved_artifacts"])
                if run["work_image"]:
                    manifest = json.loads(Path(run["work_image"]).with_suffix(".img.manifest.json").read_text(encoding="utf-8"))
                    if stage != "verification":
                        self.assertEqual(manifest["unsafe_state"]["stage"], stage)


if __name__ == "__main__":
    unittest.main()
