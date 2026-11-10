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

    def check_mutated_quality_workflow(self, original: str, replacement: str) -> None:
        reviewed = (ROOT / contract.QUALITY_WORKFLOW).read_text(encoding="utf-8")
        self.assertIn(original, reviewed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quality.yml"
            path.write_text(reviewed.replace(original, replacement), encoding="utf-8")
            contract.check_ci_boundary(path)

    def test_reviewed_quality_workflow_satisfies_the_contract(self) -> None:
        contract.check_ci_boundary()

    def test_self_hosted_runner_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssertionError, "GitHub-hosted"):
            self.check_mutated_quality_workflow(
                "    runs-on: ubuntu-24.04\n    timeout-minutes: 45",
                "    runs-on: [self-hosted, Linux]\n    timeout-minutes: 45",
            )

    def test_action_pinned_to_a_tag_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssertionError, "not pinned to a full commit"):
            self.check_mutated_quality_workflow(
                "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
                "actions/setup-python@v5",
            )

    def test_secret_reference_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssertionError, "unsafe quality workflow content"):
            self.check_mutated_quality_workflow(
                "        run: scripts/check.sh\n",
                "        env:\n          TOKEN: ${{ secrets.TOKEN }}\n"
                "        run: scripts/check.sh\n",
            )

    def test_privileged_pull_request_trigger_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssertionError, "exactly pull_request and push"):
            self.check_mutated_quality_workflow(
                "  pull_request:\n", "  pull_request_target:\n"
            )

    def test_widened_token_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssertionError, "exactly contents: read"):
            self.check_mutated_quality_workflow(
                "permissions:\n  contents: read\n",
                "permissions:\n  contents: write\n",
            )

    def test_removed_repository_gate_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssertionError, "lint quality gate missing"):
            self.check_mutated_quality_workflow(
                "        run: scripts/check.sh\n", "        run: echo skipped\n"
            )


if __name__ == "__main__":
    unittest.main()
