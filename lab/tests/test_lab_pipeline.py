#!/usr/bin/env python3
"""Regression tests for the tenra Partition disposable-image lab pipeline."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = LAB_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from discover_capabilities import discover_capabilities  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
