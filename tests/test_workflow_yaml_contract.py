#!/usr/bin/env python3
"""Tests for strict workflow parsing used by repository contract checks."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import validate_repository as contract  # noqa: E402


class WorkflowYamlContractTest(unittest.TestCase):
    def load_fixture(self, content: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.yml"
            path.write_text(content, encoding="utf-8")
            return contract.load_unique_yaml(path)

    def test_duplicate_top_level_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssertionError, "duplicate YAML key"):
            self.load_fixture('"on": {}\n"on": {}\n')

    def test_duplicate_nested_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssertionError, "duplicate YAML key"):
            self.load_fixture(
                "jobs:\n  diagnostic:\n    runs-on: one\n    runs-on: two\n"
            )

    def test_reviewed_workflow_has_only_manual_trigger_and_exact_jobs(self) -> None:
        workflow = contract.load_unique_yaml(
            ROOT / ".forgejo/workflows/public-runner-diagnostic.yml"
        )
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(set(workflow["jobs"]), {"diagnostic", "verify-next-guest"})


if __name__ == "__main__":
    unittest.main()
