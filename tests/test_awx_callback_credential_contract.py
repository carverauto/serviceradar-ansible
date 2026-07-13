#!/usr/bin/env python3
"""Conformance tests for the public AWX callback credential artifacts."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import awx_callback_credential_contract as contract  # noqa: E402


ARTIFACT_ROOT = (
    ROOT / "awx/credential-types/serviceradar-ephemeral-callback/v1"
)
SCRIPT = SCRIPTS / "awx_callback_credential_contract.py"


class CallbackCredentialContractTest(unittest.TestCase):
    def test_go_id_91_conformance_vector(self) -> None:
        canonical = contract.canonical_contract(91)
        expected = (
            ARTIFACT_ROOT / "conformance-id-91.canonical.json"
        ).read_bytes().removesuffix(b"\n")
        expected_digest = (
            ARTIFACT_ROOT / "conformance-id-91.sha256"
        ).read_text(encoding="ascii").strip()

        self.assertEqual(canonical, expected)
        self.assertEqual(
            contract.contract_sha256(canonical),
            "cd42bea50b45fcb010c1cc1e89243b8d9d0230bc2fe0b6bb9d49839d17f5a263",
        )
        self.assertEqual(contract.contract_sha256(canonical), expected_digest)

    def test_cli_emits_exact_canonical_json_then_lowercase_digest(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "91"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        canonical = contract.canonical_contract(91)
        digest = contract.contract_sha256(canonical).encode("ascii")
        self.assertEqual(result.stdout, canonical + b"\n" + digest + b"\n")
        self.assertEqual(result.stderr, b"")

    def test_cli_rejects_non_positive_and_out_of_range_ids(self) -> None:
        for value in ("0", "-1", "+1", "2147483648", "not-an-id"):
            with self.subTest(value=value):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), value],
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertIn(b"credential type ID", result.stderr)

    def test_only_grant_and_idempotency_key_are_secret(self) -> None:
        inputs = json.loads(contract.DEFAULT_INPUTS.read_text(encoding="utf-8"))
        injectors = json.loads(
            contract.DEFAULT_INJECTORS.read_text(encoding="utf-8")
        )
        secrets = {field["id"] for field in inputs["fields"] if field["secret"]}
        self.assertEqual(
            secrets,
            {"callback_grant", "callback_idempotency_key"},
        )
        self.assertEqual(len(inputs["fields"]), 10)
        self.assertEqual(len(inputs["required"]), 10)
        self.assertEqual(len(injectors["env"]), 10)
        self.assertNotIn("JOB_ID", inputs["required"])
        self.assertNotIn("JOB_ID", injectors["env"])

    def test_rejects_job_id_and_any_extra_environment_mapping(self) -> None:
        injectors = json.loads(
            contract.DEFAULT_INJECTORS.read_text(encoding="utf-8")
        )
        injectors["env"]["JOB_ID"] = "{{ job_id }}"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "injectors.json"
            path.write_text(json.dumps(injectors), encoding="utf-8")
            with self.assertRaisesRegex(contract.ContractError, "10 reviewed mappings"):
                contract.canonical_contract(91, injectors_path=path)

    def test_rejects_changed_secret_classification(self) -> None:
        inputs = json.loads(contract.DEFAULT_INPUTS.read_text(encoding="utf-8"))
        next(
            field for field in inputs["fields"] if field["id"] == "callback_url"
        )["secret"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inputs.json"
            path.write_text(json.dumps(inputs), encoding="utf-8")
            with self.assertRaisesRegex(contract.ContractError, "callback_url"):
                contract.canonical_contract(91, inputs_path=path)

    def test_canonical_and_digest_output_modes_are_pipeable(self) -> None:
        canonical = contract.canonical_contract(17)
        for output, expected in (
            ("canonical", canonical + b"\n"),
            (
                "sha256",
                contract.contract_sha256(canonical).encode("ascii") + b"\n",
            ),
        ):
            with self.subTest(output=output):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "17", "--output", output],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                )
                self.assertEqual(result.stdout, expected)
                self.assertEqual(result.stderr, b"")


if __name__ == "__main__":
    unittest.main()
