#!/usr/bin/env python3
"""Validate and fingerprint the ServiceRadar AWX callback credential type."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (
    ROOT / "awx/credential-types/serviceradar-ephemeral-callback/v1"
)
DEFAULT_INPUTS = ARTIFACT_ROOT / "inputs.json"
DEFAULT_INJECTORS = ARTIFACT_ROOT / "injectors.json"

CONTRACT_SCHEMA = "serviceradar.awx_callback_credential_type"
CONTRACT_VERSION = 1
AWX_KIND = "cloud"
MAX_AWX_ID = 2_147_483_647

FIELD_IDS = (
    "callback_url",
    "callback_grant",
    "callback_idempotency_key",
    "callback_allowed_origin",
    "callback_manifest_sha256",
    "scm_revision",
    "content_sha256",
    "callback_phase",
    "callback_operation",
    "callback_state",
)
FIELD_LABELS = {
    "callback_url": "Callback URL",
    "callback_grant": "Callback grant",
    "callback_idempotency_key": "Callback idempotency key",
    "callback_allowed_origin": "Callback allowed origin",
    "callback_manifest_sha256": "Callback manifest SHA-256",
    "scm_revision": "SCM revision",
    "content_sha256": "Content SHA-256",
    "callback_phase": "Callback phase",
    "callback_operation": "Callback operation",
    "callback_state": "Callback state",
}
SECRET_FIELD_IDS = {"callback_grant", "callback_idempotency_key"}
ENVIRONMENT = {
    "SERVICERADAR_CALLBACK_URL": "{{ callback_url }}",
    "SERVICERADAR_CALLBACK_GRANT": "{{ callback_grant }}",
    "SERVICERADAR_CALLBACK_IDEMPOTENCY_KEY": "{{ callback_idempotency_key }}",
    "SERVICERADAR_CALLBACK_ALLOWED_ORIGIN": "{{ callback_allowed_origin }}",
    "SERVICERADAR_CALLBACK_MANIFEST_SHA256": "{{ callback_manifest_sha256 }}",
    "SERVICERADAR_SCM_REVISION": "{{ scm_revision }}",
    "SERVICERADAR_CONTENT_SHA256": "{{ content_sha256 }}",
    "SERVICERADAR_CALLBACK_PHASE": "{{ callback_phase }}",
    "SERVICERADAR_CALLBACK_OPERATION": "{{ callback_operation }}",
    "SERVICERADAR_CALLBACK_STATE": "{{ callback_state }}",
}


class ContractError(ValueError):
    """The local AWX credential artifacts do not match the reviewed contract."""


def positive_awx_id(value: str) -> int:
    """Parse the same positive signed-32-bit AWX ID accepted by ServiceRadar."""

    if re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise argparse.ArgumentTypeError("credential type ID must be a positive decimal integer")
    parsed = int(value, 10)
    if parsed > MAX_AWX_ID:
        raise argparse.ArgumentTypeError(
            f"credential type ID must be at most {MAX_AWX_ID}"
        )
    return parsed


def load_json_object(path: Path, artifact_name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ContractError(f"cannot read {artifact_name} artifact {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ContractError(f"invalid JSON in {artifact_name} artifact {path}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError(f"{artifact_name} artifact must be a JSON object")
    return value


def validate_inputs(document: dict[str, Any]) -> list[dict[str, Any]]:
    if set(document) != {"fields", "required"}:
        raise ContractError("inputs artifact must contain only fields and required")

    fields = document.get("fields")
    required = document.get("required")
    if not isinstance(fields, list) or len(fields) != len(FIELD_IDS):
        raise ContractError("inputs artifact must define exactly the 10 reviewed fields")
    if not isinstance(required, list) or len(required) != len(FIELD_IDS):
        raise ContractError("inputs artifact must require exactly the 10 reviewed fields")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            raise ContractError("every input field must be an object")
        if set(field) != {"id", "label", "type", "secret"}:
            raise ContractError(
                "input fields may contain only id, label, type, and secret"
            )
        field_id = field.get("id")
        if not isinstance(field_id, str) or field_id not in FIELD_IDS:
            raise ContractError(f"unreviewed input field ID: {field_id!r}")
        if field_id in seen:
            raise ContractError(f"duplicate input field ID: {field_id}")
        seen.add(field_id)
        if field.get("label") != FIELD_LABELS[field_id]:
            raise ContractError(f"unreviewed label for input field {field_id}")
        if field.get("type") != "string":
            raise ContractError(f"input field {field_id} must have type string")
        expected_secret = field_id in SECRET_FIELD_IDS
        if field.get("secret") is not expected_secret:
            raise ContractError(
                f"input field {field_id} must set secret to {str(expected_secret).lower()}"
            )
        normalized.append(
            {"id": field_id, "secret": expected_secret, "type": "string"}
        )

    if seen != set(FIELD_IDS):
        raise ContractError("inputs artifact is missing a reviewed field")
    if any(not isinstance(field_id, str) for field_id in required):
        raise ContractError("every required field ID must be a string")
    if len(set(required)) != len(required) or set(required) != set(FIELD_IDS):
        raise ContractError("required must contain each reviewed field exactly once")
    if "JOB_ID" in seen or "JOB_ID" in required:
        raise ContractError("JOB_ID is AWX runtime state and must not be a credential input")

    return sorted(normalized, key=lambda field: field["id"])


def validate_injectors(document: dict[str, Any]) -> dict[str, str]:
    if set(document) != {"env"}:
        raise ContractError("injectors artifact must contain only env")
    environment = document.get("env")
    if not isinstance(environment, dict):
        raise ContractError("injectors env must be an object")
    if environment != ENVIRONMENT:
        raise ContractError("injectors env does not match the 10 reviewed mappings")
    if "JOB_ID" in environment:
        raise ContractError("JOB_ID is supplied by AWX and must not be injected")
    return dict(environment)


def canonical_contract(
    credential_type_id: int,
    inputs_path: Path = DEFAULT_INPUTS,
    injectors_path: Path = DEFAULT_INJECTORS,
) -> bytes:
    if (
        isinstance(credential_type_id, bool)
        or not isinstance(credential_type_id, int)
        or credential_type_id < 1
        or credential_type_id > MAX_AWX_ID
    ):
        raise ContractError(
            f"credential type ID must be an integer between 1 and {MAX_AWX_ID}"
        )

    fields = validate_inputs(load_json_object(inputs_path, "inputs"))
    environment = validate_injectors(load_json_object(injectors_path, "injectors"))
    document = {
        "schema": CONTRACT_SCHEMA,
        "version": CONTRACT_VERSION,
        "credential_type_id": credential_type_id,
        "kind": AWX_KIND,
        "fields": fields,
        "required": sorted(FIELD_IDS),
        "environment": environment,
    }
    return json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def contract_sha256(canonical: bytes) -> str:
    return hashlib.sha256(canonical).hexdigest()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Validate the reviewed v1 AWX callback credential artifacts and "
            "emit the canonical ServiceRadar contract and SHA-256."
        )
    )
    result.add_argument(
        "credential_type_id",
        type=positive_awx_id,
        help="positive credential type ID assigned by AWX (maximum 2147483647)",
    )
    result.add_argument(
        "--inputs",
        type=Path,
        default=DEFAULT_INPUTS,
        help=f"AWX input configuration JSON (default: {DEFAULT_INPUTS})",
    )
    result.add_argument(
        "--injectors",
        type=Path,
        default=DEFAULT_INJECTORS,
        help=f"AWX injector configuration JSON (default: {DEFAULT_INJECTORS})",
    )
    result.add_argument(
        "--output",
        choices=("both", "canonical", "sha256"),
        default="both",
        help=(
            "stdout format: newline-delimited canonical JSON plus digest "
            "(both), exact canonical bytes without a trailing newline "
            "(canonical), or a newline-terminated digest (sha256)"
        ),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    try:
        canonical = canonical_contract(
            args.credential_type_id,
            inputs_path=args.inputs,
            injectors_path=args.injectors,
        )
    except ContractError as error:
        argument_parser.exit(2, f"error: {error}\n")

    digest = contract_sha256(canonical)
    if args.output == "both":
        sys.stdout.buffer.write(canonical + b"\n")
    elif args.output == "canonical":
        sys.stdout.buffer.write(canonical)
    if args.output in {"both", "sha256"}:
        sys.stdout.buffer.write(digest.encode("ascii") + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
