"""Exercise address selection using Ansible's actual inventory templating engine."""

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from ansible.errors import AnsibleUndefinedVariable
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import init_plugin_loader
from ansible.template import Templar
import yaml

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = yaml.safe_load((ROOT / "inventory/proxmox.proxmox.yml").read_text())
UUID = "11111111-2222-4333-8444-555555555555"
init_plugin_loader()


class ProxmoxInventoryAddressesTest(unittest.TestCase):
    def render(self, variables, overrides=None):
        with patch.dict(
            os.environ,
            {"SERVICERADAR_PROXMOX_UUID_ADDRESSES": json.dumps(overrides or {})},
        ):
            return Templar(loader=DataLoader(), variables=variables).template(
                "{{ " + INVENTORY["compose"]["ansible_host"] + " }}"
            )

    def test_node_discovery_is_enabled_and_native_address_is_preserved(self):
        self.assertTrue(INVENTORY["want_proxmox_nodes_ansible_host"])
        self.assertEqual(self.render({"ansible_host": "192.0.2.10"}), "192.0.2.10")

    def test_reported_qemu_address_precedes_reviewed_uuid_fallback(self):
        variables = {
            "proxmox_smbios1": {"uuid": UUID},
            "proxmox_agent_interfaces": [
                {"name": "lo", "ip-addresses": ["127.0.0.1/8"]},
                {"name": "eth0", "ip-addresses": ["192.0.2.11/24"]},
            ],
        }
        self.assertEqual(self.render(variables, {UUID: "192.0.2.12"}), "192.0.2.11")

    def test_lxc_address_ignores_loopback(self):
        variables = {
            "proxmox_lxc_interfaces": [
                {"name": "lo", "inet": "127.0.0.1/8"},
                {"name": "eth0", "inet": "192.0.2.13/24"},
            ]
        }
        self.assertEqual(self.render(variables), "192.0.2.13")

    def test_reviewed_address_requires_exact_smbios_uuid(self):
        self.assertEqual(
            self.render({"proxmox_smbios1": {"uuid": UUID}}, {UUID: "192.0.2.14"}),
            "192.0.2.14",
        )
        with self.assertRaises(AnsibleUndefinedVariable):
            self.render({"proxmox_name": "host01.example.com"}, {UUID: "192.0.2.14"})

    def test_missing_address_is_undefined_instead_of_empty_string(self):
        with self.assertRaises(AnsibleUndefinedVariable):
            self.render({})


if __name__ == "__main__":
    unittest.main()
