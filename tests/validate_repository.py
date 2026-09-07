#!/usr/bin/env python3
"""Repository checks using the standard library and exact-pinned PyYAML."""

from __future__ import annotations

import json
from pathlib import Path
import re

import yaml

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
    "roles/windows_qemu_guest_agent/vars/main.yml",
    "molecule/windows_qga_static/molecule.yml",
    "molecule/windows_qga_static/converge.yml",
    "tests/windows_qga_path_contract.yml",
    "requirements.yml",
}

LINUX_TRUSTED_CA_REQUIRED_FILES = {
    "install-linux-trusted-ca.yml",
    "roles/linux_trusted_ca/README.md",
    "roles/linux_trusted_ca/defaults/main.yml",
    "roles/linux_trusted_ca/handlers/main.yml",
    "roles/linux_trusted_ca/meta/argument_specs.yml",
    "roles/linux_trusted_ca/meta/main.yml",
    "roles/linux_trusted_ca/tasks/apply_item.yml",
    "roles/linux_trusted_ca/tasks/main.yml",
    "roles/linux_trusted_ca/tasks/validate_item.yml",
    "roles/linux_trusted_ca/tasks/validate_shape.yml",
}

PROXMOX_INVENTORY_REQUIRED_FILES = {
    "inventory/proxmox.proxmox.yml",
    "docs/proxmox-dynamic-inventory.md",
    "collections/requirements.yml",
    "awx/credential-types/proxmox-api-token-ca/v1/inputs.json",
    "awx/credential-types/proxmox-api-token-ca/v1/injectors.json",
    "awx/credential-types/proxmox-api-token-ca-connect-relay/v1/inputs.json",
    "awx/credential-types/proxmox-api-token-ca-connect-relay/v1/injectors.json",
}

FLEET_SSH_REQUIRED_FILES = {
    "install-fleet-ssh-ca.yml",
    "install-fleet-ssh-known-hosts.yml",
    "docs/fleet-ssh-ca-enrollment.md",
    "examples/fleet-ssh-ca-inventory.yml",
    "roles/fleet_ssh_enroll/README.md",
    "roles/fleet_ssh_enroll/defaults/main.yml",
    "roles/fleet_ssh_enroll/handlers/main.yml",
    "roles/fleet_ssh_enroll/meta/argument_specs.yml",
    "roles/fleet_ssh_enroll/meta/main.yml",
    "roles/fleet_ssh_enroll/tasks/main.yml",
    "roles/fleet_ssh_enroll/tasks/validate.yml",
    "roles/fleet_ssh_enroll/tasks/enroll.yml",
    "roles/fleet_ssh_enroll/tasks/verify.yml",
    "roles/fleet_ssh_enroll/templates/60-serviceradar-user-ca.conf.j2",
}

PUBLIC_RUNNER_DIAGNOSTIC_REQUIRED_FILES = {
    ".forgejo/workflows/public-runner-diagnostic.yml",
    "docs/public-runner-isolation-diagnostic.md",
    "scripts/public_runner_diagnostic.sh",
    "tests/test_workflow_yaml_contract.py",
}


def repository_files(pattern: str = "*"):
    for path in ROOT.rglob(pattern):
        if path.is_file() and not any(part in IGNORED_DIRS for part in path.parts):
            yield path


def load_unique_yaml(path: Path):
    """Load trusted repository YAML while rejecting duplicate mapping keys."""

    class UniqueKeyLoader(yaml.SafeLoader):
        pass

    def construct_unique_mapping(loader, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise AssertionError(f"unhashable YAML key in {path}") from exc
            if duplicate:
                raise AssertionError(f"duplicate YAML key in {path}: {key!r}")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_unique_mapping,
    )
    with path.open(encoding="utf-8") as source:
        return yaml.load(source, Loader=UniqueKeyLoader)


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
        "allow_unsigned_pinned_iso",
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
        "Get-AuthenticodeSignature",
        "windows_qemu_guest_agent_signature.output[0].status == 'Valid'",
        "['Valid', 'NotSigned']",
        "windows_qemu_guest_agent_signature_policy != 'require_valid'",
        "allow_unsigned_pinned_iso",
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
        "verify_signature:",
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
    execution_environment = (ROOT / "execution-environment.yml").read_text(
        encoding="utf-8"
    )
    if 'ansible.windows: \">=2.4.0,<3.0.0\"' not in galaxy:
        raise AssertionError("collection must declare the supported ansible.windows range")
    for value in ("name: ansible.windows", "version: 2.4.0"):
        if value not in requirements:
            raise AssertionError(f"exact Windows collection lock missing: {value}")
    for value in (
        "quay.io/ansible/awx-ee@sha256:d6fca88c8c26e143b1fc71cc60db3b0ee06c43cc46fd395e902dcec3dbc5af9b",
        "galaxy: requirements.yml",
        "ansible\\.windows[[:space:]]+2\\.4\\.0",
    ):
        if value not in execution_environment:
            raise AssertionError(f"Windows AWX execution environment missing: {value}")

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


def check_linux_trusted_ca() -> None:
    missing = sorted(
        name for name in LINUX_TRUSTED_CA_REQUIRED_FILES if not (ROOT / name).is_file()
    )
    if missing:
        raise AssertionError(f"missing Linux trusted CA content: {missing}")

    wrapper = (ROOT / "install-linux-trusted-ca.yml").read_text(encoding="utf-8")
    for value in (
        "hosts: \"{{ target_hosts | default('all') }}\"",
        "become: true",
        "role: linux_trusted_ca",
        "gather_facts: true",
    ):
        if value not in wrapper:
            raise AssertionError(f"Linux trusted CA wrapper contract missing: {value}")

    task_text = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in LINUX_TRUSTED_CA_REQUIRED_FILES
        if name.endswith((".yml", ".md"))
    )
    required = {
        "CA:TRUE",
        "sha256_fingerprint",
        "checksum_algorithm: sha256",
        "/usr/local/share/ca-certificates",
        "/etc/pki/ca-trust/source/anchors",
        "update-ca-certificates",
        "update-ca-trust",
        "validate_certs: true",
        "follow_redirects: none",
        "use_netrc: false",
        "use_proxy: false",
        "openssl\n          - verify",
        "-partial_chain",
        "Refresh Linux CA trust",
        "Restart CA consumers",
        "state: absent",
    }
    absent = sorted(value for value in required if value not in task_text)
    if absent:
        raise AssertionError(f"Linux trusted CA security boundary missing: {absent}")

    forbidden = {
        "validate_certs: false",
        "get_url:",
        "url_username:",
        "url_password:",
        "-----BEGIN PRIVATE KEY-----",
        "ignore_errors: true",
    }
    present = sorted(value for value in forbidden if value in task_text)
    if present:
        raise AssertionError(f"unsafe Linux trusted CA pattern present: {present}")


def check_proxmox_inventory() -> None:
    missing = sorted(
        name for name in PROXMOX_INVENTORY_REQUIRED_FILES if not (ROOT / name).is_file()
    )
    if missing:
        raise AssertionError(f"missing Proxmox inventory content: {missing}")

    inventory = (ROOT / "inventory/proxmox.proxmox.yml").read_text(encoding="utf-8")
    required = {
        "plugin: community.proxmox.proxmox",
        "PROXMOX_URL",
        "PROXMOX_USER",
        "PROXMOX_TOKEN_ID",
        "PROXMOX_TOKEN_SECRET",
        "validate_certs: true",
        "want_facts: true",
        "proxmox_agent_interfaces",
        "proxmox_lxc_interfaces",
    }
    absent = sorted(value for value in required if value not in inventory)
    if absent:
        raise AssertionError(f"Proxmox inventory security boundary missing: {absent}")
    if "validate_certs: false" in inventory:
        raise AssertionError("Proxmox inventory must never disable TLS verification")

    requirements = (ROOT / "collections/requirements.yml").read_text(encoding="utf-8")
    for value in ("name: community.proxmox", "version: 2.0.0"):
        if value not in requirements:
            raise AssertionError(f"pinned Proxmox collection dependency missing: {value}")

    inputs = json.loads(
        (
            ROOT
            / "awx/credential-types/proxmox-api-token-ca/v1/inputs.json"
        ).read_text(encoding="utf-8")
    )
    injectors = json.loads(
        (
            ROOT
            / "awx/credential-types/proxmox-api-token-ca/v1/injectors.json"
        ).read_text(encoding="utf-8")
    )

    fields = {field["id"]: field for field in inputs.get("fields", [])}
    if set(fields) != {"url", "user", "token_id", "token_secret", "ca_bundle"}:
        raise AssertionError("Proxmox credential type has an unexpected input surface")
    if fields["token_secret"].get("secret") is not True:
        raise AssertionError("Proxmox token secret must be an AWX secret input")
    if set(inputs.get("required", [])) != set(fields):
        raise AssertionError("Proxmox credential type must require every reviewed field")
    if injectors.get("file") != {"template": "{{ ca_bundle }}"}:
        raise AssertionError("Proxmox CA must use the AWX temporary credential file")

    environment = injectors.get("env", {})
    if environment.get("REQUESTS_CA_BUNDLE") != "{{ tower.filename }}":
        raise AssertionError("Proxmox credential must bind requests to the reviewed CA file")
    if environment.get("PROXMOX_VALIDATE_CERTS") != "true":
        raise AssertionError("Proxmox credential must force certificate validation")
    if "PROXMOX_TOKEN_SECRET" not in environment:
        raise AssertionError("Proxmox token secret injector is missing")

    relay_inputs = json.loads(
        (
            ROOT
            / "awx/credential-types/proxmox-api-token-ca-connect-relay/v1/inputs.json"
        ).read_text(encoding="utf-8")
    )
    relay_injectors = json.loads(
        (
            ROOT
            / "awx/credential-types/proxmox-api-token-ca-connect-relay/v1/injectors.json"
        ).read_text(encoding="utf-8")
    )
    relay_fields = {field["id"]: field for field in relay_inputs.get("fields", [])}
    expected_relay_fields = set(fields) | {"https_proxy"}
    if set(relay_fields) != expected_relay_fields:
        raise AssertionError("Proxmox relay credential type has an unexpected input surface")
    if set(relay_inputs.get("required", [])) != expected_relay_fields:
        raise AssertionError("Proxmox relay credential must require every reviewed field")
    if relay_fields["token_secret"].get("secret") is not True:
        raise AssertionError("Proxmox relay token secret must be an AWX secret input")
    if relay_fields["https_proxy"].get("secret") is not False:
        raise AssertionError("Proxmox CONNECT relay origin must be a non-secret input")
    if relay_injectors.get("file") != {"template": "{{ ca_bundle }}"}:
        raise AssertionError("Proxmox relay CA must use the AWX temporary credential file")
    relay_environment = relay_injectors.get("env", {})
    expected_relay_environment = dict(environment)
    expected_relay_environment["HTTPS_PROXY"] = "{{ https_proxy }}"
    if relay_environment != expected_relay_environment:
        raise AssertionError("Proxmox relay credential injectors do not match the reviewed contract")


def check_fleet_ssh_enroll() -> None:
    missing = sorted(
        name for name in FLEET_SSH_REQUIRED_FILES if not (ROOT / name).is_file()
    )
    if missing:
        raise AssertionError(f"missing fleet SSH enrollment content: {missing}")

    wrapper = (ROOT / "install-fleet-ssh-ca.yml").read_text(encoding="utf-8")
    for value in (
        "hosts: \"{{ target_hosts | default('all') }}\"",
        "become: true",
        "role: fleet_ssh_enroll",
        "gather_facts: true",
    ):
        if value not in wrapper:
            raise AssertionError(f"fleet SSH wrapper contract missing: {value}")

    task_text = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in FLEET_SSH_REQUIRED_FILES
        if name.endswith((".yml", ".md", ".j2"))
    )
    required = {
        "password: \"!\"",
        "TrustedUserCAKeys",
        "AuthorizedPrincipalsFile",
        "srp_v1_",
        "/usr/sbin/sshd\n      - -t",
        "sshd\n      - -T",
        "state: reloaded",
        "FLEET_SSH_CA_PUBLIC_KEY",
        "FLEET_SSH_CA_FINGERPRINT",
        "FLEET_SSH_PRINCIPALS",
        "ssh-keyscan",
        "known_hosts",
    }
    absent = sorted(value for value in required if value not in task_text)
    if absent:
        raise AssertionError(f"fleet SSH security boundary missing: {absent}")

    forbidden = {
        "state: restarted",
        "ignore_errors: true",
        "validate_certs: false",
        "-----BEGIN PRIVATE KEY-----",
        "10.0.0.3",
        "192.168.2.10",
        "192.168.2.22",
    }
    present = sorted(value for value in forbidden if value in task_text)
    if present:
        raise AssertionError(f"unsafe fleet SSH pattern present: {present}")

    example = (ROOT / "examples/fleet-ssh-ca-inventory.yml").read_text(
        encoding="utf-8"
    )
    if "192.0.2." not in example:
        raise AssertionError(
            "fleet SSH example inventory must use documentation addresses"
        )


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
    lint_and_molecule = workflow.split("  lint-and-syntax:\n", maxsplit=1)
    if len(lint_and_molecule) != 2:
        raise AssertionError("lint job is missing from the quality workflow")

    job_sections = lint_and_molecule[1].split("  molecule-systemd-sshd:\n", maxsplit=1)
    if len(job_sections) != 2:
        raise AssertionError("Molecule job is missing from the quality workflow")

    lint, molecule = job_sections

    approved_label = "serviceradar-public-ephemeral-ubuntu-24.04-20260701"
    approved_runs_on = f"runs-on: [{approved_label}]"
    boundary_required = {
        approved_runs_on,
        "persist-credentials: false",
        'test "${GITHUB_REPOSITORY:-}" = "carverauto/serviceradar-ansible"',
        'test "${SERVICERADAR_RUNNER_BOUNDARY:-}" = "public-ephemeral-lxc-v1"',
        'test "${SERVICERADAR_RUNNER_REPOSITORY_ID:-}" = "85"',
        'test "${SERVICERADAR_RUNNER_REPOSITORY:-}" = "carverauto/serviceradar-ansible"',
        'test "${SERVICERADAR_RUNNER_VERSION:-}" = "12.8.0"',
        "SERVICERADAR_RUNNER_GUEST_ID",
        "test ! -S /run/forgejo-docker/docker.sock",
        "test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token",
        "PLUGIN_UPLOAD_SIGNING_PRIVATE_KEY",
        "FORGEJO_API_TOKEN",
        "FORGEJO_RUNNER_TOKEN",
        "FORGEJO_RUNNER_REGISTRATION_TOKEN",
    }

    for job_name, job in (("lint", lint), ("Molecule", molecule)):
        missing = sorted(value for value in boundary_required if value not in job)
        if missing:
            raise AssertionError(
                f"isolated {job_name} runner contract missing: {missing}"
            )
        denylist = job.split("for name in \\", maxsplit=1)[1].split(
            "; do", maxsplit=1
        )[0]
        if "FORGEJO_TOKEN" in denylist:
            raise AssertionError(
                f"isolated {job_name} runner must allow Forgejo's automatic job token"
            )
        for required in (
            'test -n "${FORGEJO_TOKEN:-}"',
            'test "${FORGEJO_TOKEN}" = "${GITHUB_TOKEN:-}"',
        ):
            if required not in job:
                raise AssertionError(
                    f"isolated {job_name} runner job-token assertion missing: {required}"
                )

    runs_on_lines = re.findall(r"^\s+runs-on:\s*.+$", workflow, flags=re.MULTILINE)
    if runs_on_lines != [f"    {approved_runs_on}", f"    {approved_runs_on}"]:
        raise AssertionError(
            f"quality jobs must use only the approved runner: {runs_on_lines}"
        )

    if "permissions:\n  contents: read" not in workflow:
        raise AssertionError(
            "quality workflow must retain its contents: read intent declaration"
        )
    if "defaults:\n  run:\n    shell: bash" not in workflow:
        raise AssertionError("quality workflow must execute boundary checks with Bash")

    molecule_required = {
        "DOCKER_HOST: unix:///var/run/docker.sock",
        'test "${#platform_images[@]}" -eq 4',
    }
    missing = sorted(value for value in molecule_required if value not in molecule)
    if missing:
        raise AssertionError(f"isolated Molecule runner contract missing: {missing}")

    forbidden = {
        "runs-on: [ubuntu24]",
        "runs-on: [ubuntu-latest]",
        "serviceradar-signing",
        "pull_request_target",
    }
    present = sorted(value for value in forbidden if value in workflow)
    if present:
        raise AssertionError(f"unsafe quality workflow runner contract present: {present}")

    shell_gate_required = {
        "shellcheck=0.9.0-1",
        'test "$(shellcheck --version | awk \'/^version:/ {print $2}\')" = "0.9.0"',
    }
    missing = sorted(value for value in shell_gate_required if value not in lint)
    if missing:
        raise AssertionError(f"exact ShellCheck quality gate missing: {missing}")

    check_script = (ROOT / "scripts/check.sh").read_text(encoding="utf-8")
    for required in (
        "command -v shellcheck",
        "scripts/public_runner_diagnostic.sh",
        "shellcheck \\",
    ):
        if required not in check_script:
            raise AssertionError(f"repository ShellCheck gate missing: {required}")


def check_public_runner_diagnostic() -> None:
    missing_files = sorted(
        name
        for name in PUBLIC_RUNNER_DIAGNOSTIC_REQUIRED_FILES
        if not (ROOT / name).is_file()
    )
    if missing_files:
        raise AssertionError(
            f"missing public runner diagnostic content: {missing_files}"
        )

    requirements = (ROOT / "requirements-ci.txt").read_text(encoding="utf-8")
    lock = (ROOT / "requirements-ci.lock").read_text(encoding="utf-8")
    if "pyyaml==6.0.3" not in requirements or "pyyaml==6.0.3" not in lock:
        raise AssertionError(
            "strict workflow YAML parser dependency is not exactly pinned"
        )

    workflow_path = ROOT / ".forgejo/workflows/public-runner-diagnostic.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    parsed = load_unique_yaml(workflow_path)
    if not isinstance(parsed, dict):
        raise AssertionError("public runner diagnostic workflow must be a mapping")
    if set(parsed) != {
        "name",
        "on",
        "permissions",
        "concurrency",
        "defaults",
        "jobs",
    }:
        raise AssertionError(
            f"public runner diagnostic has unexpected top-level keys: {sorted(parsed)}"
        )
    if parsed.get("name") != "controlled-public-runner-isolation-diagnostic":
        raise AssertionError("public runner diagnostic name differs")
    triggers = parsed.get("on")
    if not isinstance(triggers, dict) or set(triggers) != {"workflow_dispatch"}:
        raise AssertionError(
            "public runner diagnostic must have only workflow_dispatch"
        )
    dispatch = triggers["workflow_dispatch"]
    if not isinstance(dispatch, dict) or set(dispatch) != {"inputs"}:
        raise AssertionError("public runner workflow_dispatch must contain only inputs")
    inputs = dispatch["inputs"]
    if not isinstance(inputs, dict) or set(inputs) != {
        "expected_commit",
        "scenario",
        "previous_guest_id",
    }:
        raise AssertionError(
            "public runner diagnostic inputs differ from the reviewed set"
        )
    if (
        inputs["expected_commit"].get("required") is not True
        or inputs["expected_commit"].get("type") != "string"
    ):
        raise AssertionError("expected_commit must be a required string input")
    if "default" in inputs["expected_commit"]:
        raise AssertionError("expected_commit must never have a moving default")
    if (
        inputs["scenario"].get("required") is not True
        or inputs["scenario"].get("default") != "success"
    ):
        raise AssertionError("diagnostic scenario input contract differs")
    if inputs["scenario"].get("type") != "string":
        raise AssertionError("diagnostic scenario must be a string input")
    if (
        inputs["previous_guest_id"].get("required") is not False
        or inputs["previous_guest_id"].get("default") != ""
        or inputs["previous_guest_id"].get("type") != "string"
    ):
        raise AssertionError("previous_guest_id input contract differs")
    if parsed.get("permissions") != {"contents": "read"}:
        raise AssertionError(
            "public runner diagnostic permissions intent must be contents: read"
        )
    if parsed.get("concurrency") != {
        "group": "controlled-public-runner-isolation-diagnostic",
        "cancel-in-progress": False,
    }:
        raise AssertionError("public runner diagnostic concurrency contract differs")
    if parsed.get("defaults") != {"run": {"shell": "bash"}}:
        raise AssertionError("public runner diagnostic shell defaults differ")

    approved_label = "serviceradar-public-ephemeral-ubuntu-24.04-20260701"
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict) or set(jobs) != {"diagnostic", "verify-next-guest"}:
        raise AssertionError("public runner diagnostic must contain exactly two jobs")
    checkout = "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
    expected_job_keys = {
        "diagnostic": {"runs-on", "timeout-minutes", "outputs", "steps"},
        "verify-next-guest": {
            "needs",
            "if",
            "runs-on",
            "timeout-minutes",
            "steps",
        },
    }
    for job_name, job in jobs.items():
        if set(job) != expected_job_keys[job_name]:
            raise AssertionError(f"{job_name} job keys differ from the reviewed set")
        if job.get("runs-on") != [approved_label]:
            raise AssertionError(
                f"{job_name} must use only the exact public runner label"
            )
        if job.get("timeout-minutes") != 8:
            raise AssertionError(f"{job_name} must retain the reviewed timeout")
        for forbidden_key in ("container", "services", "environment", "permissions"):
            if forbidden_key in job:
                raise AssertionError(
                    f"{job_name} contains forbidden job key: {forbidden_key}"
                )
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            raise AssertionError(f"{job_name} steps are missing")
        if len(steps) != 3 or not all(isinstance(step, dict) for step in steps):
            raise AssertionError(f"{job_name} must contain exactly three mapping steps")
        expected_step_keys = (
            ({"name", "id", "env", "run"}, {"name", "uses", "with"}, {"name", "env", "run"})
            if job_name == "diagnostic"
            else ({"name", "env", "run"}, {"name", "uses", "with"}, {"name", "env", "run"})
        )
        if tuple(set(step) for step in steps) != expected_step_keys:
            raise AssertionError(f"{job_name} step keys or ordering differ")
        pre_checkout = steps[0].get("run", "")
        for required in (
            'name.startswith("GIT_")',
            '"ALL_PROXY"',
            '"FORGEJO_API_TOKEN"',
            '"FORGEJO_RUNNER_REGISTRATION_TOKEN"',
            '"FORGEJO_RUNNER_TOKEN"',
            '("credential.", "filter.", "http.", "include.", "url.")',
            '"core.fsmonitor"',
            '"init.templatedir"',
            'key.casefold().startswith("remote.")',
            "forbidden pre-checkout environment category is present",
            "Git configuration contains a pre-checkout credential or execution hook",
            "serviceradar-public-runner-diagnostic-workspace-sentinel",
        ):
            if required not in pre_checkout:
                raise AssertionError(
                    f"{job_name} pre-checkout isolation gate is missing: {required}"
                )
        credential_denylist = pre_checkout.split(
            "forbidden_environment = {", maxsplit=1
        )[1].split("\n}", maxsplit=1)[0]
        if '"FORGEJO_TOKEN"' in credential_denylist:
            raise AssertionError(
                f"{job_name} pre-checkout gate must allow Forgejo's automatic job token"
            )
        if (
            'os.environ.get("FORGEJO_TOKEN", "")' not in pre_checkout
            or 'os.environ.get("GITHUB_TOKEN", "")' not in pre_checkout
            or "automatic Forgejo job token aliases differ or are empty"
            not in pre_checkout
        ):
            raise AssertionError(
                f"{job_name} pre-checkout job-token alias assertion is missing"
            )
        if steps[1].get("uses") != checkout:
            raise AssertionError(f"{job_name} checkout must follow its isolation gate")
        checkout_steps = [step for step in steps if step.get("uses") == checkout]
        if len(checkout_steps) != 1 or checkout_steps[0].get("with") != {
            "persist-credentials": False
        }:
            raise AssertionError(
                f"{job_name} checkout is not exact and credential-free"
            )
        unexpected_actions = [
            step.get("uses")
            for step in steps
            if "uses" in step and step.get("uses") != checkout
        ]
        if unexpected_actions:
            raise AssertionError(f"{job_name} contains unexpected actions")
    if jobs["diagnostic"].get("outputs") != {
        "guest_id": "${{ steps.identity.outputs.guest_id }}"
    }:
        raise AssertionError("diagnostic job output contract differs")
    if jobs["verify-next-guest"].get("needs") != ["diagnostic"]:
        raise AssertionError("replacement guest job dependency differs")
    if jobs["verify-next-guest"].get("if") != (
        "${{ always() && github.event.inputs.scenario != 'verify-clean' && "
        "github.event.inputs.scenario != 'hold-for-cancel' }}"
    ):
        raise AssertionError("replacement guest terminal-state condition differs")

    workflow_required = {
        '"on":\n  workflow_dispatch:',
        "permissions:\n  contents: read",
        "cancel-in-progress: false",
        f"runs-on: [{approved_label}]",
        "timeout-minutes: 8",
        "persist-credentials: false",
        "scripts/public_runner_diagnostic.sh run",
        "scripts/public_runner_diagnostic.sh verify-clean",
        "needs: [diagnostic]",
        "always()",
        "needs.diagnostic.outputs.guest_id",
        "github.event.inputs.expected_commit",
        "github.event.inputs.previous_guest_id",
        'test "${GITHUB_SHA:-}" = "${EXPECTED_COMMIT}"',
        'test "${GITHUB_SERVER_URL:-}" = "https://code.carverauto.dev"',
        'name.startswith("GIT_")',
        "forbidden pre-checkout environment category is present",
        "Git configuration contains a pre-checkout credential or execution hook",
        "serviceradar-public-runner-diagnostic-workspace-sentinel",
        "test ! -S /run/forgejo-docker/docker.sock",
        "test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token",
        "test ! -e /etc/forgejo-public-runner/api-token",
    }
    missing = sorted(value for value in workflow_required if value not in workflow)
    if missing:
        raise AssertionError(
            f"public runner diagnostic workflow contract missing: {missing}"
        )

    scenarios = {
        "success",
        "forced-failure",
        "timeout",
        "hold-for-cancel",
        "hold-for-runner-crash",
        "hold-for-host-restart",
        "verify-clean",
    }
    missing = sorted(value for value in scenarios if value not in workflow)
    if missing:
        raise AssertionError(f"public runner lifecycle scenarios missing: {missing}")

    if workflow.count(f"runs-on: [{approved_label}]") != 2:
        raise AssertionError(
            "both diagnostic jobs must use only the public runner label"
        )
    if workflow.count("persist-credentials: false") != 2:
        raise AssertionError(
            "both diagnostic checkouts must disable credential persistence"
        )
    for forbidden in (
        "${{ secrets.",
        "actions/upload-artifact",
        "serviceradar-signing",
        "runs-on: [ubuntu24]",
        "runs-on: [ubuntu-latest]",
    ):
        if forbidden in workflow:
            raise AssertionError(
                f"unsafe public runner diagnostic workflow content: {forbidden}"
            )

    diagnostic = (ROOT / "scripts/public_runner_diagnostic.sh").read_text(
        encoding="utf-8"
    )
    diagnostic_required = {
        "0 && $2 == 1000000 && $3 == 65536",
        "FORGEJO_RUNNER_REGISTRATION_TOKEN",
        "/etc/forgejo-public-runner/api-token",
        "/run/forgejo-docker/docker.sock",
        "/run/containerd/containerd.sock",
        "/var/run/secrets/kubernetes.io/serviceaccount/token",
        "Docker config exposes reusable authentication",
        "docker volume inspect",
        "docker image inspect",
        "previous guest evidence is malformed",
        "previous guest evidence is required and malformed",
        "the same disposable guest identity accepted a second job",
        "PID 1 ${map_kind} map is not the exact singleton reviewed mapping",
        "https://code.carverauto.dev",
        "forbidden Git or askpass environment category is present",
        "ALL_PROXY",
        '("credential.", "filter.", "http.", "include.", "url.")',
        '"core.fsmonitor"',
        '"init.templatedir"',
        'key.casefold().startswith("remote.")',
        "Git configuration contains a credential, rewrite, proxy, or execution hook",
        "cloud or Kubernetes credential/cache state is present under HOME",
        "private key material is present under HOME",
        "serviceradar-public-runner-diagnostic-workspace-sentinel",
        'printf \'%s\\n\' "${evidence}" >"${GITHUB_WORKSPACE}/${workspace_sentinel}"',
        "Docker config exposes reusable authentication",
        '("kubernetes-api-service", "10.43.0.1", 443)',
        '("openbao-active", "10.43.201.1", 8200)',
        '("proxmox-management", "192.168.2.10", 8006)',
        '("runner-host-management", "10.213.1.6", 22)',
        "time.cloudflare.com",
        "https://registry-1.docker.io/v2/",
        "https://snapshot.ubuntu.com/ubuntu/20260714T000000Z/dists/noble/InRelease",
        "docker pull",
        "--privileged --cgroupns=host",
        "sentinel_written_for_guest",
        "exit 42",
        "operator_hook_ready=true",
        "expected=host-firewall-drop",
    }
    missing = sorted(value for value in diagnostic_required if value not in diagnostic)
    if missing:
        raise AssertionError(f"public runner diagnostic assertions missing: {missing}")
    ambient_function = diagnostic.split(
        "assert_no_ambient_credentials() {", maxsplit=1
    )[1].split("\n}\n", maxsplit=1)[0]
    credential_denylist = ambient_function.split(
        "local -a forbidden_environment=(", maxsplit=1
    )[1].split("\n  )", maxsplit=1)[0]
    for required in (
        "FORGEJO_API_TOKEN",
        "FORGEJO_RUNNER_REGISTRATION_TOKEN",
        "FORGEJO_RUNNER_TOKEN",
    ):
        if required not in credential_denylist:
            raise AssertionError(
                f"public runner diagnostic must reject persistent credential: {required}"
            )
    if "FORGEJO_TOKEN" in credential_denylist:
        raise AssertionError(
            "public runner diagnostic must allow Forgejo's automatic job token"
        )
    for required in (
        "automatic Forgejo job token is absent",
        "automatic Forgejo job token aliases differ",
    ):
        if required not in ambient_function:
            raise AssertionError(
                f"public runner diagnostic job-token assertion missing: {required}"
            )
    for forbidden in ("set -x", "printenv", "curl -k", "--insecure"):
        if forbidden in diagnostic:
            raise AssertionError(
                f"unsafe public runner diagnostic behavior: {forbidden}"
            )

    guide = (ROOT / "docs/public-runner-isolation-diagnostic.md").read_text(
        encoding="utf-8"
    )
    guide_required = {
        "ssh -J root@192.168.2.10 serviceradar-operator@10.213.1.6",
        "pkill -KILL -x forgejo-runner",
        'qm config 167 | grep -Fxq "name: forgejo-public-runner-01" && qm reset 167',
        "verify-isolation.sh --api",
        "QUARANTINED",
        "verify-clean",
        "always()",
        "VM-host forbidden-destination counter",
        "Never display the credential",
        "runner identity verified",
        "The workspace tree is searched before checkout",
        "write-capable",
        "not an enforcement boundary",
        "previous_guest_id",
        "expected_commit",
        "cannot be used to claim an increment in a PVE counter",
        "never compare a post-boot value with the pre-reset value",
        "cat /proc/sys/kernel/random/boot_id",
        "verify-pve-network.sh --active",
    }
    missing = sorted(value for value in guide_required if value not in guide)
    if missing:
        raise AssertionError(f"public runner diagnostic runbook missing: {missing}")


def main() -> None:
    check_json()
    check_callback_response_schema()
    check_wrappers()
    check_no_private_material()
    check_windows_qga()
    check_linux_trusted_ca()
    check_proxmox_inventory()
    check_fleet_ssh_enroll()
    check_integrated_catalog_only()
    check_ci_boundary()
    check_public_runner_diagnostic()
    print("repository contract checks passed")


if __name__ == "__main__":
    main()
