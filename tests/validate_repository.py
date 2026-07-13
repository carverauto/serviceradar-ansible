#!/usr/bin/env python3
"""Dependency-free repository contract checks used before Ansible tooling."""

from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {".git", ".venv", ".ansible", ".cache", ".collections", ".molecule", "__pycache__"}

INTEGRATED_WRAPPERS = {
    "remote-access-integrated-preflight.yml": ("preflight", "present", "enroll"),
    "remote-access-integrated-stage.yml": ("stage", "present", "enroll"),
    "remote-access-integrated-overlap-stage.yml": ("stage", "present", "overlap"),
    "remote-access-integrated-retire-stage.yml": ("stage", "present", "retire"),
    "remote-access-integrated-absent-stage.yml": ("stage", "absent", "remove"),
    "remote-access-integrated-enroll-verify.yml": ("verify", "present", "enroll"),
    "remote-access-integrated-enroll-commit.yml": ("commit", "present", "enroll"),
    "remote-access-integrated-overlap-verify.yml": ("verify", "present", "overlap"),
    "remote-access-integrated-overlap-commit.yml": ("commit", "present", "overlap"),
    "remote-access-integrated-retire-verify.yml": ("verify", "present", "retire"),
    "remote-access-integrated-retire-commit.yml": ("commit", "present", "retire"),
    "remote-access-integrated-absent-verify.yml": ("verify", "absent", "remove"),
    "remote-access-integrated-absent-commit.yml": ("commit", "absent", "remove"),
}

WINDOWS_QGA_REQUIRED_FILES = {
    "install-qemu-guest-agent-windows.yml",
    "qemu-guest-agent-windows-preflight.yml",
    "docs/windows-qemu-guest-agent.md",
    "examples/windows-qemu-guest-agent-inventory.yml",
    "roles/windows_qemu_guest_agent/README.md",
    "roles/windows_qemu_guest_agent/defaults/main.yml",
    "roles/windows_qemu_guest_agent/meta/argument_specs.yml",
    "roles/windows_qemu_guest_agent/meta/main.yml",
    "roles/windows_qemu_guest_agent/tasks/main.yml",
    "molecule/windows_qga_static/molecule.yml",
    "molecule/windows_qga_static/converge.yml",
    "requirements.yml",
}


def repository_files(pattern: str = "*"):
    for path in ROOT.rglob(pattern):
        if path.is_file() and not any(part in IGNORED_DIRS for part in path.parts):
            yield path


def check_json() -> None:
    for path in repository_files("*.json"):
        with path.open(encoding="utf-8") as source:
            json.load(source)


def check_callback_response_schema() -> None:
    path = ROOT / "catalog/ssh-ca-bundle-response.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))

    if schema.get("$schema") != "http://json-schema.org/draft-07/schema#":
        raise AssertionError("callback response schema must use the supported draft-07 contract")
    if "$defs" in schema or "definitions" not in schema:
        raise AssertionError("callback response schema definitions are not draft-07 compatible")
    if "job_id" not in schema.get("required", []):
        raise AssertionError("callback response schema must require the AWX runtime job ID")
    if schema.get("properties", {}).get("job_id") != {"type": "integer", "minimum": 1}:
        raise AssertionError("callback response schema has an invalid AWX runtime job ID")
    if schema.get("properties", {}).get("targets", {}).get("items") != {
        "$ref": "#/definitions/target"
    }:
        raise AssertionError("callback response schema target reference is not canonical")


def check_wrappers() -> None:
    missing = sorted(name for name in INTEGRATED_WRAPPERS if not (ROOT / name).is_file())
    if missing:
        raise AssertionError(f"missing integrated wrappers: {missing}")
    for name, (phase, state, operation) in INTEGRATED_WRAPPERS.items():
        content = (ROOT / name).read_text(encoding="utf-8")
        if "ansible.builtin.import_playbook: playbooks/integrated.yml" not in content:
            raise AssertionError(f"integrated wrapper bypasses fixed entrypoint: {name}")
        literals = {
            f"SERVICERADAR_CALLBACK_PHASE') == '{phase}'",
            f"SERVICERADAR_CALLBACK_STATE') == '{state}'",
            f"SERVICERADAR_CALLBACK_OPERATION') == '{operation}'",
        }
        missing_literals = sorted(value for value in literals if value not in content)
        if missing_literals:
            raise AssertionError(f"wrapper intent is not literal in {name}: {missing_literals}")

    integrated = (ROOT / "playbooks/integrated.yml").read_text(encoding="utf-8")
    required_boundaries = {
        "Snapshot the exact AWX-limited host set without contacting targets",
        "Materialize every exact AWX host binding before callback",
        "connection: local",
        "Resolve and validate the callback exactly once on the AWX controller",
        "hosts: serviceradar_callback_targets",
    }
    missing = sorted(value for value in required_boundaries if value not in integrated)
    if missing:
        raise AssertionError(f"integrated controller/managed boundary missing: {missing}")
    if "serial:" in integrated:
        raise AssertionError("integrated callback must not repeat across serial batches")
    materialization = integrated.split(
        "- name: Materialize every exact AWX host binding before callback", 1
    )[1].split(
        "- name: Resolve and validate the callback exactly once on the AWX controller", 1
    )[0]
    if "delegate_to: localhost" not in materialization or "run_once:" in materialization:
        raise AssertionError(
            "AWX scope materialization must run locally once for every limited host"
        )

    callback = (ROOT / "roles/serviceradar_callback/tasks/main.yml").read_text(
        encoding="utf-8"
    )
    if callback.count("ansible.builtin.uri:") != 1:
        raise AssertionError("callback consumer must have exactly one HTTP invocation")
    for value in ("SERVICERADAR_CALLBACK_IDEMPOTENCY_KEY", "Idempotency-Key"):
        if value not in callback:
            raise AssertionError(f"callback idempotency boundary missing: {value}")
    for value in (
        "lookup('ansible.builtin.env', 'JOB_ID') is match('^[1-9][0-9]{0,18}$')",
        "job_id: \"{{ lookup('ansible.builtin.env', 'JOB_ID') | int }}\"",
        "sr_callback_response.json.get('job_id', 0)",
    ):
        if value not in callback:
            raise AssertionError(f"exact AWX runtime job binding missing: {value}")

    catalog = (ROOT / "catalog/remote-access-ssh-ca.yml").read_text(encoding="utf-8")
    if "awx_runtime_environment:\n      - JOB_ID" not in catalog:
        raise AssertionError("catalog must identify JOB_ID as AWX runtime state")
    custom_environment = catalog.split("custom_credential_environment:", 1)[1].split(
        "awx_runtime_environment:", 1
    )[0]
    if "JOB_ID" in custom_environment:
        raise AssertionError("JOB_ID must not be injected by the custom credential")
    for value in (
        "status_code: [200, 409]",
        "until: sr_callback_response.status | default(0) == 200",
        "timeout: 5",
        "retries: 30",
    ):
        if value not in callback:
            raise AssertionError(f"bounded callback retry contract missing: {value}")
    if "^(sr_ra_|sr_callback_|_sr_)" not in integrated:
        raise AssertionError("integrated host set lacks exhaustive reserved-prefix rejection")

    activation = (
        ROOT / "roles/remote_access_ssh_ca/files/serviceradar-ssh-ca-activate"
    ).read_text(encoding="utf-8")
    for primitive in ("fcntl.LOCK_EX", "renameat2", "ensure_before_deadline"):
        if primitive not in activation:
            raise AssertionError(f"atomic activation primitive missing: {primitive}")

    transition = (
        ROOT / "roles/remote_access_ssh_ca/tasks/validate_transition.yml"
    ).read_text(encoding="utf-8")
    for operation in ("enroll", "overlap", "retire"):
        if f"sr_ra_operation == '{operation}'" not in transition:
            raise AssertionError(f"CA delta gate missing for {operation}")


def check_no_private_material() -> None:
    forbidden = re.compile(
        r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|ENCRYPTED) PRIVATE KEY-----|"
        r"ssh-ca export|serviceradar-cli.+ca",
        re.IGNORECASE,
    )
    findings: list[str] = []
    for path in repository_files():
        if path == Path(__file__):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if forbidden.search(content):
            findings.append(str(path.relative_to(ROOT)))
    if findings:
        raise AssertionError(f"private material/export pattern found: {findings}")


def check_windows_qga() -> None:
    missing = sorted(
        name for name in WINDOWS_QGA_REQUIRED_FILES if not (ROOT / name).is_file()
    )
    if missing:
        raise AssertionError(f"missing Windows QGA content: {missing}")

    wrapper = (ROOT / "install-qemu-guest-agent-windows.yml").read_text(
        encoding="utf-8"
    )
    for value in (
        "hosts: \"{{ target_hosts | default('all') }}\"",
        "role: windows_qemu_guest_agent",
        "gather_facts: true",
    ):
        if value not in wrapper:
            raise AssertionError(f"Windows QGA wrapper contract missing: {value}")

    preflight = (ROOT / "qemu-guest-agent-windows-preflight.yml").read_text(
        encoding="utf-8"
    )
    for value in (
        "gather_facts: false",
        "Win32_LogicalDisk",
        "DriveType=5",
        "Get-AuthenticodeSignature",
        "Get-FileHash",
        "authenticode_status",
        "sha256",
        "path",
    ):
        if value not in preflight:
            raise AssertionError(f"Windows QGA read-only preflight missing: {value}")
    for value in (
        "ansible.windows.win_package:",
        "ansible.windows.win_service:",
        "ansible.windows.win_reboot:",
        "ansible.windows.win_file:",
        "ansible.windows.win_get_url:",
    ):
        if value in preflight:
            raise AssertionError(f"Windows QGA preflight contains mutation: {value}")

    tasks = (ROOT / "roles/windows_qemu_guest_agent/tasks/main.yml").read_text(
        encoding="utf-8"
    )
    required_task_boundaries = {
        "windows_qemu_guest_agent_source != 'https'",
        "windows_qemu_guest_agent_source != 'mounted_iso'",
        "match('^https://[^/@?#]+",
        "match('^[A-Fa-f0-9]{64}$')",
        "ansible.windows.win_get_url:",
        "validate_certs: true",
        "checksum_algorithm: sha256",
        "ansible.windows.win_package:",
        "verify_signature: true",
        "Win32_LogicalDisk",
        "drive_type | int == 5",
        "ansible.windows.win_reboot:",
        "ansible.windows.win_service:",
        "ansible.windows.win_service_info:",
        "windows_qemu_guest_agent_service_name == 'QEMU-GA'",
        "windows_qemu_guest_agent_binary.output[0].file_version",
        "qm agent <vmid> ping",
    }
    missing_boundaries = sorted(
        value for value in required_task_boundaries if value not in tasks
    )
    if missing_boundaries:
        raise AssertionError(
            f"Windows QGA security/readiness boundary missing: {missing_boundaries}"
        )

    forbidden_task_patterns = {
        "validate_certs: false",
        "verify_signature: false",
        "ansible.windows.win_shell:",
        "ansible.windows.win_command:",
        "ansible.builtin.raw:",
        "ignore_errors: true",
        "url_username:",
        "url_password:",
        "/latest/",
    }
    present = sorted(value for value in forbidden_task_patterns if value in tasks)
    if present:
        raise AssertionError(f"unsafe Windows QGA task pattern present: {present}")

    galaxy = (ROOT / "galaxy.yml").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.yml").read_text(encoding="utf-8")
    if 'ansible.windows: \">=3.4.0,<4.0.0\"' not in galaxy:
        raise AssertionError("collection must declare the supported ansible.windows range")
    for value in ("name: ansible.windows", "version: 3.6.1"):
        if value not in requirements:
            raise AssertionError(f"exact Windows collection lock missing: {value}")

    scenario = (ROOT / "molecule/windows_qga_static/converge.yml").read_text(
        encoding="utf-8"
    )
    for value in (
        "windows_qemu_guest_agent_source: https",
        "windows_qemu_guest_agent_source: mounted_iso",
        "qemu-ga-x86_64.msi",
    ):
        if value not in scenario:
            raise AssertionError(f"Windows QGA static scenario missing: {value}")

    guide = (ROOT / "docs/windows-qemu-guest-agent.md").read_text(encoding="utf-8")
    for value in (
        "QGA cannot bootstrap WinRM or OpenSSH",
        "qm set <vmid> --agent enabled=1",
        "vioserial",
        "ansible_connection: winrm",
        "ansible_connection: ssh",
        "Proxmox graphical console",
        "machine credential",
    ):
        if value not in guide:
            raise AssertionError(f"Windows QGA operator guidance missing: {value}")

    public_lab_leaks = []
    for path in WINDOWS_QGA_REQUIRED_FILES:
        content = (ROOT / path).read_text(encoding="utf-8")
        if "192.168.2.126" in content:
            public_lab_leaks.append(path)
    if public_lab_leaks:
        raise AssertionError(f"private lab target leaked into public content: {public_lab_leaks}")


def check_integrated_catalog_only() -> None:
    catalog = (ROOT / "catalog/remote-access-ssh-ca.yml").read_text(encoding="utf-8")
    if "direct_wrappers_catalog_eligible: false" not in catalog:
        raise AssertionError("direct wrappers must remain catalog-ineligible")
    if "production_import_ready: false" not in catalog:
        raise AssertionError("untested integrated content must remain production-gated")
    if "remote-access-direct-" in catalog:
        raise AssertionError("catalog must not bind a direct wrapper")


def check_ci_boundary() -> None:
    workflow = (ROOT / ".forgejo/workflows/quality.yml").read_text(encoding="utf-8")
    molecule = workflow.split("  molecule-systemd-sshd:\n", maxsplit=1)[-1]

    required = {
        "runs-on: [serviceradar-public-ephemeral-ubuntu-24.04-20260701]",
        "persist-credentials: false",
        "test ! -S /run/forgejo-docker/docker.sock",
        "test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token",
        "DOCKER_HOST: unix:///var/run/docker.sock",
    }
    missing = sorted(value for value in required if value not in molecule)
    if missing:
        raise AssertionError(f"isolated Molecule runner contract missing: {missing}")

    forbidden = {
        "runs-on: [ubuntu24]",
        "serviceradar-signing",
        "pull_request_target",
        "--privileged",
        "volumes:",
    }
    present = sorted(value for value in forbidden if value in molecule)
    if present:
        raise AssertionError(f"unsafe Molecule runner contract present: {present}")


def main() -> None:
    check_json()
    check_callback_response_schema()
    check_wrappers()
    check_no_private_material()
    check_windows_qga()
    check_integrated_catalog_only()
    check_ci_boundary()
    print("repository contract checks passed")


if __name__ == "__main__":
    main()
