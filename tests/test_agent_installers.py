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
def release_api(status: int = 404, document=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body = json.dumps(document or {"message": "Not Found"}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
    def run_tasks(self, installer, variables, tasks):
        play = yaml.safe_load((ROOT / installer).read_text())[0]
        play = {
            "name": "Exercise installer contract without changing the host",
            "hosts": "localhost",
            "gather_facts": False,
            "vars": {
                **play["vars"],
                "ansible_python_interpreter": sys.executable,
                "ansible_facts": {"architecture": "x86_64"},
                **variables,
            },
            "tasks": tasks,
        }
        executable = shutil.which("ansible-playbook")
        self.assertIsNotNone(executable, "install the pinned requirements-ci.lock before running these tests")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.yml"
            path.write_text(yaml.safe_dump([play], sort_keys=False))
            return subprocess.run(
                [executable, "-i", "localhost,", "--connection", "local", str(path)],
                cwd=ROOT,
                env={**os.environ, "ANSIBLE_NOCOLOR": "1", "ANSIBLE_LOCAL_TEMP": directory,
                     "NO_PROXY": "127.0.0.1,localhost"},
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )

    def resolve(self, installer, variables, assertions=()):
        tasks = [{"ansible.builtin.import_tasks": str(ROOT / "tasks/agent_artifact.yml")}]
        if assertions:
            tasks.append({"ansible.builtin.assert": {"that": list(assertions)}})
        return self.run_tasks(installer, variables, tasks)

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
