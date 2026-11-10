#!/usr/bin/env python3
"""Run installer selection tasks against invented packages and a local release API."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def release_api(status: int = 404, document=None, headers=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body = json.dumps(document or {"message": "Not Found"}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def do_HEAD(self):
            requests.append("HEAD " + self.path)
            self.send_response(status)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class AgentInstallerTest(unittest.TestCase):
    def run_tasks(self, installer, variables, tasks, hosts=None, check=False):
        """Run tasks with the installer's variables; hosts maps invented names to host variables."""
        hosts = hosts or {"localhost": {}}
        play = yaml.safe_load((ROOT / installer).read_text())[0]
        play = {
            "name": "Exercise installer contract without changing the host",
            "hosts": "all",
            "gather_facts": False,
            "vars": {
                **play["vars"],
                "ansible_python_interpreter": sys.executable,
                "ansible_facts": {"architecture": "{{ contract_architecture | default('x86_64') }}"},
                **variables,
            },
            "tasks": tasks,
        }
        executable = shutil.which("ansible-playbook")
        self.assertIsNotNone(executable, "install the pinned requirements-ci.lock before running these tests")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.yml"
            path.write_text(yaml.safe_dump([play], sort_keys=False))
            inventory = Path(directory) / "inventory.yml"
            inventory.write_text(yaml.safe_dump({"all": {"hosts": hosts}}))
            return subprocess.run(
                [executable, "-i", str(inventory), "--connection", "local",
                 *(["--check"] if check else []), str(path)],
                cwd=ROOT,
                env={**os.environ, "ANSIBLE_NOCOLOR": "1", "ANSIBLE_LOCAL_TEMP": directory,
                     "NO_PROXY": "127.0.0.1,localhost"},
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )

    def resolve(self, installer, variables, assertions=(), hosts=None):
        tasks = [{"ansible.builtin.import_tasks": str(ROOT / "tasks/agent_artifact.yml")}]
        if assertions:
            tasks.append({"ansible.builtin.assert": {"that": list(assertions)}})
        return self.run_tasks(installer, variables, tasks, hosts=hosts)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pinned_packages_skip_release_discovery_and_preserve_checksum(self):
        for installer, expected_arch in [
            ("install-agent-debian.yml", "amd64"),
            ("install-agent-redhat.yml", "x86_64"),
        ]:
            with self.subTest(installer=installer), release_api() as (url, requests):
                result = self.resolve(installer, {
                    "serviceradar_api_base": url,
                    "serviceradar_version": "v5.6.7",
                    "serviceradar_agent_package_url": "https://artifacts.example.com/reviewed-package",
                    "serviceradar_agent_package_sha256": "ABCDEF01" * 8,
                }, [
                    "serviceradar_target_version == '5.6.7'",
                    "serviceradar_package_download_url == 'https://artifacts.example.com/reviewed-package'",
                    "serviceradar_package_checksum == 'sha256:' ~ ('abcdef01' * 8)",
                    f"serviceradar_package_arch == '{expected_arch}'",
                ])
                self.assert_success(result)
                self.assertEqual(requests, [])

    def test_partial_or_invalid_pins_fail_before_network(self):
        valid = {
            "serviceradar_version": "5.6.7",
            "serviceradar_agent_package_url": "https://artifacts.example.com/package.deb",
            "serviceradar_agent_package_sha256": "1" * 64,
        }
        cases = [
            {key: value for key, value in valid.items() if key != missing}
            for missing in valid
        ] + [
            {**valid, "serviceradar_agent_package_sha256": "not-a-digest"},
            {**valid, "serviceradar_agent_package_url": "file:///tmp/package.deb"},
        ]
        for variables in cases:
            with self.subTest(variables=variables), release_api() as (url, requests):
                result = self.resolve("install-agent-debian.yml", {**variables, "serviceradar_api_base": url})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(requests, [])

    def test_missing_release_fails_with_pinned_artifact_guidance(self):
        for status, document in [(404, {}), (200, {"tag_name": "v5.6.7", "assets": []})]:
            with self.subTest(status=status), release_api(status, document) as (url, requests):
                result = self.resolve("install-agent-debian.yml", {"serviceradar_api_base": url})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("No published ServiceRadar GitHub release", result.stdout)
                self.assertIn("serviceradar_agent_package_sha256", result.stdout)
                self.assertEqual(requests, ["/releases/latest"])

    def test_release_selection_rejects_gateway_and_other_architecture_assets(self):
        for installer, name in [
            ("install-agent-debian.yml", "serviceradar-agent_5.6.7_amd64.deb"),
            ("install-agent-redhat.yml", "serviceradar-agent-5.6.7-1.x86_64.rpm"),
        ]:
            asset_url = "https://artifacts.example.com/" + name
            document = {"tag_name": "v5.6.7", "assets": [
                {"name": name, "browser_download_url": asset_url},
                {"name": name + ".sha256", "browser_download_url": asset_url + ".sha256"},
                {"name": name.replace("agent", "agent-gateway"), "browser_download_url": "https://example.com/wrong"},
                {"name": name.replace("amd64", "arm64").replace("x86_64", "aarch64"),
                 "browser_download_url": "https://example.com/wrong-architecture"},
            ]}
            with self.subTest(installer=installer), release_api(200, document) as (url, requests):
                result = self.resolve(installer, {"serviceradar_api_base": url, "serviceradar_version": "5.6.7"}, [
                    f"serviceradar_package_download_url == '{asset_url}'",
                    f"serviceradar_package_checksum == 'sha256:{asset_url}.sha256'",
                ])
                self.assert_success(result)
                self.assertEqual(requests, ["/releases/tags/v5.6.7"])

    def test_release_metadata_is_fetched_once_for_every_host_in_the_play(self):
        for installer, names in [
            ("install-agent-debian.yml", {
                "x86_64": "serviceradar-agent_5.6.7_amd64.deb",
                "aarch64": "serviceradar-agent_5.6.7_arm64.deb",
            }),
            ("install-agent-redhat.yml", {
                "x86_64": "serviceradar-agent-5.6.7-1.x86_64.rpm",
                "aarch64": "serviceradar-agent-5.6.7-1.aarch64.rpm",
            }),
        ]:
            document = {"tag_name": "v5.6.7", "assets": [
                {"name": name, "browser_download_url": "https://artifacts.example.com/" + name}
                for name in names.values()
            ]}
            hosts = {
                f"host{number:02d}.example.com": {
                    "contract_architecture": architecture,
                    "expected_download_url": "https://artifacts.example.com/" + names[architecture],
                }
                for number, architecture in enumerate(["x86_64", "aarch64", "x86_64"], start=1)
            }
            with self.subTest(installer=installer), release_api(200, document) as (url, requests):
                result = self.resolve(installer, {"serviceradar_api_base": url, "serviceradar_version": "5.6.7"}, [
                    "serviceradar_package_download_url == expected_download_url",
                ], hosts=hosts)
                self.assert_success(result)
                self.assertEqual(requests, ["/releases/tags/v5.6.7"])

    def test_pinned_and_discovering_hosts_share_a_play(self):
        name = "serviceradar-agent_6.7.8_amd64.deb"
        document = {"tag_name": "v6.7.8", "assets": [
            {"name": name, "browser_download_url": "https://artifacts.example.com/" + name},
        ]}
        hosts = {
            "host01.example.com": {
                "serviceradar_version": "5.6.7",
                "serviceradar_agent_package_url": "https://artifacts.example.com/reviewed-package",
                "serviceradar_agent_package_sha256": "1" * 64,
                "expected_version": "5.6.7",
                "expected_download_url": "https://artifacts.example.com/reviewed-package",
            },
            "host02.example.com": {
                "expected_version": "6.7.8",
                "expected_download_url": "https://artifacts.example.com/" + name,
            },
        }
        with release_api(200, document) as (url, requests):
            result = self.resolve("install-agent-debian.yml", {"serviceradar_api_base": url}, [
                "serviceradar_target_version == expected_version",
                "serviceradar_package_download_url == expected_download_url",
            ], hosts=hosts)
            self.assert_success(result)
            self.assertEqual(requests, ["/releases/latest"])

    def test_rate_limited_lookup_names_the_cause_without_retrying(self):
        hosts = {"host01.example.com": {}, "host02.example.com": {}}
        cases = [
            (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1900000000"},
             "limit resets at 2030-03-17 17:46:40 UTC"),
            (429, {"Retry-After": "60"}, "limit resets at an unreported time"),
        ]
        for status, headers, reset in cases:
            with self.subTest(status=status), release_api(status, {}, headers) as (url, requests):
                result = self.resolve("install-agent-debian.yml", {"serviceradar_api_base": url}, hosts=hosts)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("GitHub rate limited the release lookup", result.stdout)
                self.assertIn(f"HTTP {status}", result.stdout)
                self.assertIn(reset, result.stdout)
                self.assertIn("serviceradar_agent_package_sha256", result.stdout)
                self.assertEqual(requests, ["/releases/latest"])

    def test_unexpected_lookup_response_names_the_status(self):
        # A 403 that carries no rate-limit evidence must not be reported as a rate limit.
        for status in [403, 418]:
            with self.subTest(status=status), release_api(status, {}) as (url, requests):
                result = self.resolve("install-agent-debian.yml", {"serviceradar_api_base": url})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("GitHub rate limited the release lookup", result.stdout)
                self.assertIn("did not get a usable answer", result.stdout)
                self.assertIn(f"HTTP status {status}", result.stdout)
                self.assertIn("serviceradar_agent_package_sha256", result.stdout)
                self.assertEqual(requests, ["/releases/latest"])

    def test_check_mode_plans_a_first_install_without_touching_the_package(self):
        for installer in ["install-agent-debian.yml", "install-agent-redhat.yml"]:
            install = next(
                task for task in yaml.safe_load((ROOT / installer).read_text())[0]["tasks"]
                if task["name"].startswith("Download and install")
            )
            with self.subTest(installer=installer), release_api(200) as (url, requests):
                result = self.run_tasks(installer, {
                    "serviceradar_version": "5.6.7",
                    "serviceradar_agent_package_url": url + "/reviewed-package",
                    "serviceradar_agent_package_sha256": "1" * 64,
                    "serviceradar_installed_version": "",
                }, [
                    {"ansible.builtin.import_tasks": str(ROOT / "tasks/agent_artifact.yml")},
                    {"ansible.builtin.import_tasks": str(ROOT / "tasks/agent_package_identity.yml")},
                    install,
                    {"ansible.builtin.import_tasks": str(ROOT / "tasks/agent_service.yml")},
                ], check=True)
                self.assert_success(result)
                self.assertIn('"package": "install"', result.stdout)
                self.assertIn('"status": "planned"', result.stdout)
                self.assertIn(f'"source": "{url}/reviewed-package"', result.stdout)
                # Check mode probes the artifact URL and never fetches its bytes.
                self.assertEqual(requests, ["HEAD /reviewed-package"])

    def test_service_start_requires_all_enrollment_assets(self):
        tasks = yaml.safe_load((ROOT / "tasks/agent_service.yml").read_text())
        readiness = next(task for task in tasks if "ansible.builtin.set_fact" in task)
        service = next(task["ansible.builtin.systemd_service"] for task in tasks if "ansible.builtin.systemd_service" in task)
        report = next(task["ansible.builtin.debug"]["msg"] for task in tasks if task["name"] == "Report package and enrollment state")
        for complete in [True, False]:
            with self.subTest(complete=complete):
                assets = [{"stat": {"isreg": True}} for _ in range(3)]
                assets.append({"stat": {"isreg": True}} if complete else {"stat": {"exists": False}})
                result = self.run_tasks("install-agent-debian.yml", {
                    "serviceradar_target_version": "5.6.7",
                    "serviceradar_package_install_required": False,
                    "serviceradar_reinstall_pinned_package": False,
                    "serviceradar_package_download_url": "https://artifacts.example.com/reviewed-package",
                    "serviceradar_enrollment_assets": {"results": assets},
                }, [
                    readiness,
                    {"ansible.builtin.set_fact": {"observed_service": service, "observed_report": report}},
                    {"ansible.builtin.assert": {"that": [
                        "serviceradar_enrollment_ready == " + ("true" if complete else "false"),
                        "observed_service.state == 'started'" if complete else "observed_service.state is not defined",
                        "observed_report.status == '" + ("installed_service_active" if complete else "installed_awaiting_enrollment") + "'",
                    ]}},
                ])
                self.assert_success(result)

    def test_same_version_pins_reconcile_artifact_identity_idempotently(self):
        tasks = yaml.safe_load((ROOT / "tasks/agent_package_identity.yml").read_text())
        comparisons = [task for task in tasks if "ansible.builtin.set_fact" in task]
        requested_sha = "1" * 64
        cases = [
            ("not installed", "", None, True, True, False),
            ("version upgrade", "4.5.6", requested_sha, True, True, False),
            ("changed pin", "5.6.7", "2" * 64, True, True, True),
            ("unrecorded pin", "5.6.7", None, True, True, True),
            ("unchanged pin", "5.6.7", requested_sha, True, False, False),
            ("unchanged release", "5.6.7", None, False, False, False),
            ("release upgrade", "4.5.6", None, False, True, False),
        ]
        for name, installed_version, recorded_sha, pinned, install, reinstall in cases:
            with self.subTest(case=name):
                variables = {
                    "serviceradar_target_version": "5.6.7",
                    "serviceradar_installed_version": installed_version,
                    "serviceradar_use_pinned_package": pinned,
                    "serviceradar_package_identity": {},
                }
                if pinned:
                    variables["serviceradar_agent_package_sha256"] = requested_sha
                if recorded_sha:
                    variables["serviceradar_package_identity"]["content"] = base64.b64encode(
                        (recorded_sha + "\n").encode()
                    ).decode()
                result = self.run_tasks("install-agent-debian.yml", variables, comparisons + [
                    {"ansible.builtin.assert": {"that": [
                        "serviceradar_package_install_required == " + str(install).lower(),
                        "serviceradar_reinstall_pinned_package == " + str(reinstall).lower(),
                    ]}},
                ])
                self.assert_success(result)


if __name__ == "__main__":
    unittest.main()
