"""Exercise address selection through Ansible's own inventory compose path.

Every host variable below is invented and has the shape that the pinned
community.proxmox inventory plugin produces: the guest agent's
`hardware-address` arrives as `mac-address`, `ip-addresses` is a list of
`address/prefix` strings, and a `netN` value is a dict when every
comma-separated part is `key=value`.
"""

import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from ansible.inventory.data import InventoryData
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.inventory import BaseInventoryPlugin, Constructable
from ansible.plugins.loader import init_plugin_loader
from ansible.template import Templar
from ansible.utils.unsafe_proxy import wrap_var
import yaml

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "inventory/proxmox.proxmox.yml"
INVENTORY = yaml.safe_load(INVENTORY_PATH.read_text(encoding="utf-8"))
UUID = "11111111-2222-4333-8444-555555555555"
PRIMARY_MAC = "bc:24:11:00:00:01"
HOST = "host01"
UNRESOLVED = "address_unresolved"
RETIRED_MAP_VARIABLE = "SERVICERADAR_PROXMOX_UUID_ADDRESSES"
init_plugin_loader()
# One templating environment for the whole module keeps its compiled-expression cache.
TEMPLAR = Templar(loader=DataLoader())


def qemu_net(mac=PRIMARY_MAC.upper()):
    return {"virtio": mac, "bridge": "vmbr0", "firewall": "1"}


def lxc_net(address, mac=PRIMARY_MAC.upper()):
    return {"name": "eth0", "bridge": "vmbr0", "hwaddr": mac, "ip": address, "type": "veth"}


def agent_interface(name, mac, *addresses):
    return {"name": name, "mac-address": mac, "ip-addresses": list(addresses)}


def kubernetes_node_interfaces():
    """A dummy device listed first, address-less veth pairs, and the NIC last."""
    return [
        agent_interface("lo", "00:00:00:00:00:00", "127.0.0.1/8", "::1/128"),
        agent_interface(
            "kube-ipvs0", "02:00:5e:10:00:01", *[f"198.51.100.{index}/32" for index in range(1, 41)]
        ),
        *[agent_interface(f"veth{index:04x}", f"02:00:5e:20:00:{index:02x}") for index in range(1, 9)],
        agent_interface("flannel.1", "02:00:5e:30:00:01", "198.51.100.200/32"),
        agent_interface("ens18", PRIMARY_MAC, "fe80::1/64", "192.0.2.21/24"),
    ]


class _Composer(BaseInventoryPlugin, Constructable):
    NAME = "serviceradar_test_composer"

    def __init__(self):
        super().__init__()
        self.inventory = InventoryData()
        self.templar = TEMPLAR


class Composed:
    def __init__(self, variables, groups):
        self.variables = variables
        self.groups = groups

    @property
    def address(self):
        return self.variables.get("ansible_host", "<no ansible_host>")

    @property
    def source(self):
        return self.variables.get("serviceradar_address_source", "<no source>")

    @property
    def unresolved(self):
        return UNRESOLVED in self.groups


def compose(variables):
    """Repeat what the plugin does for one guest: set facts, compose, group."""
    plugin = _Composer()
    plugin.inventory.add_host(HOST)
    for name, value in wrap_var(variables).items():
        plugin.inventory.set_variable(HOST, name, value)
    facts = plugin.inventory.get_host(HOST).get_vars()
    entries = INVENTORY["compose"]
    # The two entries an operator reads must evaluate for every input, so a
    # failure in them raises here; `strict: false` would silently drop them.
    total = {
        name: entries[name]
        for name in ("serviceradar_address_source", "serviceradar_primary_mac")
        if name in entries
    }
    partial = {name: entries[name] for name in entries if name not in total}
    plugin._set_composite_vars(total, facts, HOST, strict=True)
    plugin._set_composite_vars(partial, facts, HOST, strict=INVENTORY["strict"])
    unresolved = {name: rule for name, rule in INVENTORY["groups"].items() if name == UNRESOLVED}
    plugin._add_host_to_composed_groups(unresolved, facts, HOST, strict=True)
    host = plugin.inventory.get_host(HOST)
    return Composed(host.get_vars(), {group.name for group in host.get_groups()})


class QemuGuestAgentAddressTest(unittest.TestCase):
    def guest(self, interfaces, net=None, **extra):
        return {
            "proxmox_vmtype": "qemu",
            "proxmox_net0": qemu_net() if net is None else net,
            "proxmox_agent_interfaces": interfaces,
            **extra,
        }

    def test_kubernetes_node_uses_the_nic_proxmox_configured_not_the_first_listed(self):
        result = compose(self.guest(kubernetes_node_interfaces()))
        self.assertEqual(result.address, "192.0.2.21")
        self.assertEqual(result.source, "guest_agent_primary_nic")
        self.assertEqual(result.variables["serviceradar_primary_mac"], PRIMARY_MAC)
        self.assertFalse(result.unresolved)

    def test_interface_order_does_not_change_the_address(self):
        interfaces = kubernetes_node_interfaces()
        for ordering in (interfaces, interfaces[::-1], interfaces[3:] + interfaces[:3]):
            self.assertEqual(compose(self.guest(ordering)).address, "192.0.2.21")

    def test_mac_comparison_ignores_case(self):
        for configured, reported in (
            (PRIMARY_MAC.upper(), PRIMARY_MAC),
            (PRIMARY_MAC, PRIMARY_MAC.upper()),
            ("Bc:24:11:00:00:01", "bC:24:11:00:00:01"),
        ):
            with self.subTest(configured=configured, reported=reported):
                result = compose(
                    self.guest([agent_interface("ens18", reported, "192.0.2.22/24")], qemu_net(configured))
                )
                self.assertEqual(result.address, "192.0.2.22")
                self.assertEqual(result.variables["serviceradar_primary_mac"], PRIMARY_MAC)

    def test_unparsed_net_string_is_read_like_the_parsed_dict(self):
        result = compose(
            self.guest(kubernetes_node_interfaces(), f"virtio={PRIMARY_MAC.upper()},bridge=vmbr0,link_down")
        )
        self.assertEqual(result.address, "192.0.2.21")
        self.assertEqual(result.variables["serviceradar_primary_mac"], PRIMARY_MAC)

    def test_lowest_numbered_nic_is_primary_when_net0_is_absent(self):
        other = "bc:24:11:00:00:02"
        interfaces = [
            agent_interface("ens19", other, "198.51.100.9/24"),
            agent_interface("ens18", PRIMARY_MAC, "192.0.2.23/24"),
        ]
        facts = {
            "proxmox_vmtype": "qemu",
            "proxmox_agent_interfaces": interfaces,
            "proxmox_net5": qemu_net(other),
            "proxmox_net2": qemu_net(),
        }
        self.assertEqual(compose(facts).address, "192.0.2.23")
        facts["proxmox_net0"] = qemu_net(other)
        self.assertEqual(compose(facts).address, "198.51.100.9")

    def test_every_net_index_proxmox_accepts_is_considered(self):
        for index in range(32):
            with self.subTest(index=index):
                result = compose(
                    {
                        "proxmox_vmtype": "qemu",
                        f"proxmox_net{index}": qemu_net(),
                        "proxmox_agent_interfaces": kubernetes_node_interfaces(),
                    }
                )
                self.assertEqual(result.address, "192.0.2.21")
                self.assertEqual(result.source, "guest_agent_primary_nic")

    def test_interfaces_sharing_the_primary_mac_are_read_in_name_order(self):
        result = compose(
            self.guest(
                [
                    agent_interface("ens18.20", PRIMARY_MAC, "198.51.100.20/24"),
                    agent_interface("ens18", PRIMARY_MAC),
                    agent_interface("br0", PRIMARY_MAC, "192.0.2.24/24"),
                ]
            )
        )
        self.assertEqual(result.address, "192.0.2.24")

    def assert_unresolved(self, result):
        self.assertEqual(result.address, "<no ansible_host>")
        self.assertEqual(result.source, "none")
        self.assertTrue(result.unresolved)

    def test_primary_nic_with_only_ipv6_does_not_borrow_another_interface(self):
        self.assert_unresolved(
            compose(
                self.guest(
                    [
                        agent_interface("docker0", "02:00:5e:40:00:01", "198.51.100.1/24"),
                        agent_interface("ens18", PRIMARY_MAC, "2001:db8::21/64", "fe80::1/64"),
                    ]
                )
            )
        )

    def test_primary_nic_with_only_link_local_or_loopback_is_unresolved(self):
        self.assert_unresolved(
            compose(self.guest([agent_interface("ens18", PRIMARY_MAC, "169.254.10.20/16", "127.0.0.2/8")]))
        )

    def test_link_local_is_skipped_for_a_later_usable_address(self):
        result = compose(self.guest([agent_interface("ens18", PRIMARY_MAC, "169.254.10.20/16", "192.0.2.25/24")]))
        self.assertEqual(result.address, "192.0.2.25")

    def test_agent_reporting_no_interface_with_the_primary_mac_is_unresolved(self):
        self.assert_unresolved(
            compose(self.guest([agent_interface("ens18", "bc:24:11:00:00:09", "192.0.2.26/24")]))
        )

    def test_guest_without_agent_data_is_unresolved(self):
        result = compose({"proxmox_vmtype": "qemu", "proxmox_net0": qemu_net()})
        self.assert_unresolved(result)
        self.assertEqual(result.variables["serviceradar_primary_mac"], PRIMARY_MAC)

    def test_guest_without_a_configured_nic_never_matches_an_empty_reported_mac(self):
        result = compose(
            {
                "proxmox_vmtype": "qemu",
                "proxmox_agent_interfaces": [agent_interface("tun0", "", "198.51.100.30/24")],
            }
        )
        self.assert_unresolved(result)
        self.assertEqual(result.variables["serviceradar_primary_mac"], "")

    def test_incomplete_interface_records_are_ignored_not_fatal(self):
        incomplete = [
            {"name": "veth0001"},
            {"name": "veth0002", "mac-address": PRIMARY_MAC},
            {"name": "veth0003", "ip-addresses": ["198.51.100.31/24"]},
            {"mac-address": PRIMARY_MAC, "ip-addresses": ["198.51.100.32/24"]},
            {"name": "veth0004", "mac-address": PRIMARY_MAC, "ip-addresses": None},
            {"name": "veth0005", "mac-address": None, "ip-addresses": ["198.51.100.33/24"]},
            "ens19",
            None,
        ]
        self.assert_unresolved(compose(self.guest(incomplete)))
        result = compose(self.guest([*incomplete, agent_interface("ens18", PRIMARY_MAC, "192.0.2.27/24")]))
        self.assertEqual(result.address, "192.0.2.27")

    def test_unexpected_fact_shapes_still_report_a_source(self):
        for interfaces in (None, "", "ens18", {}, 7, [[]]):
            for net in (None, "", 7, [], ["virtio"], {"bridge": "vmbr0"}):
                with self.subTest(interfaces=interfaces, net=net):
                    result = compose(
                        {"proxmox_agent_interfaces": interfaces, "proxmox_net0": net, "proxmox_vmtype": None}
                    )
                    self.assert_unresolved(result)


class LxcAddressTest(unittest.TestCase):
    def container(self, address, interfaces=None):
        facts = {"proxmox_vmtype": "lxc", "proxmox_net0": lxc_net(address)}
        if interfaces is not None:
            facts["proxmox_lxc_interfaces"] = interfaces
        return facts

    def test_static_configuration_is_used_when_the_container_reports_nothing(self):
        result = compose(self.container("192.0.2.31/24"))
        self.assertEqual(result.address, "192.0.2.31")
        self.assertEqual(result.source, "lxc_config")
        self.assertFalse(result.unresolved)

    def test_static_configuration_precedes_a_reported_address(self):
        result = compose(
            self.container(
                "192.0.2.31/24", [{"name": "eth0", "hwaddr": PRIMARY_MAC, "inet": "198.51.100.40/24"}]
            )
        )
        self.assertEqual(result.address, "192.0.2.31")
        self.assertEqual(result.source, "lxc_config")

    def test_unparsed_static_configuration_is_read_like_the_parsed_dict(self):
        result = compose(
            {
                "proxmox_vmtype": "lxc",
                "proxmox_net0": f"name=eth0,bridge=vmbr0,hwaddr={PRIMARY_MAC.upper()},ip=192.0.2.33/24,link_down",
            }
        )
        self.assertEqual(result.address, "192.0.2.33")
        self.assertEqual(result.source, "lxc_config")

    def test_dhcp_container_uses_the_reported_interface_with_the_configured_mac(self):
        result = compose(
            self.container(
                "dhcp",
                [
                    {"name": "lo", "hwaddr": "00:00:00:00:00:00", "inet": "127.0.0.1/8", "inet6": "::1/128"},
                    {"name": "docker0", "hwaddr": "02:00:5e:40:00:01", "inet": "198.51.100.1/24"},
                    {"name": "eth0", "hwaddr": PRIMARY_MAC, "inet": "192.0.2.32/24", "inet6": "2001:db8::32/64"},
                ],
            )
        )
        self.assertEqual(result.address, "192.0.2.32")
        self.assertEqual(result.source, "lxc_interface")
        self.assertFalse(result.unresolved)

    def test_dhcp_or_manual_container_without_a_reported_address_is_unresolved(self):
        for address in ("dhcp", "manual"):
            for interfaces in (
                None,
                [{"name": "eth0", "hwaddr": PRIMARY_MAC}],
                [{"name": "eth0", "hwaddr": PRIMARY_MAC, "inet6": "2001:db8::34/64"}],
                [{"name": "docker0", "hwaddr": "02:00:5e:40:00:01", "inet": "198.51.100.1/24"}],
            ):
                with self.subTest(address=address, interfaces=interfaces):
                    result = compose(self.container(address, interfaces))
                    self.assertEqual(result.address, "<no ansible_host>")
                    self.assertEqual(result.source, "none")
                    self.assertTrue(result.unresolved)

    def test_ipv6_text_is_never_mistaken_for_the_primary_mac(self):
        result = compose(
            {
                "proxmox_vmtype": "lxc",
                "proxmox_net0": {
                    "name": "eth0",
                    "bridge": "vmbr0",
                    "ip": "dhcp",
                    "ip6": "2001:db8:aa:bb:cc:dd:ee:ff/64",
                    "gw6": "2001:db8:aa:bb:cc:dd:ee:1",
                },
            }
        )
        self.assertEqual(result.variables["serviceradar_primary_mac"], "")
        self.assertEqual(result.source, "none")

    def test_static_address_field_of_a_qemu_guest_is_not_an_lxc_configuration(self):
        result = compose({"proxmox_vmtype": "qemu", "proxmox_net0": lxc_net("192.0.2.35/24")})
        self.assertEqual(result.source, "none")
        self.assertTrue(result.unresolved)


class FallbackAddressTest(unittest.TestCase):
    def test_node_keeps_the_address_the_plugin_discovered(self):
        self.assertTrue(INVENTORY["want_proxmox_nodes_ansible_host"])
        result = compose({"ansible_host": "192.0.2.10"})
        self.assertEqual(result.address, "192.0.2.10")
        self.assertEqual(result.source, "plugin_default")
        self.assertFalse(result.unresolved)

    def test_missing_address_leaves_ansible_host_unset_instead_of_empty(self):
        result = compose({})
        self.assertNotIn("ansible_host", result.variables)
        self.assertEqual(result.source, "none")
        self.assertTrue(result.unresolved)


class NoManualOverrideTest(unittest.TestCase):
    def test_retired_uuid_address_map_does_not_address_a_guest(self):
        facts = {"proxmox_vmtype": "qemu", "proxmox_smbios1": {"uuid": UUID}, "proxmox_net0": qemu_net()}
        with patch.dict(os.environ, {RETIRED_MAP_VARIABLE: json.dumps({UUID: "192.0.2.14"})}):
            result = compose(facts)
        self.assertNotIn("ansible_host", result.variables)
        self.assertNotIn("serviceradar_uuid_map_address", result.variables)
        self.assertEqual(result.source, "none")
        self.assertTrue(result.unresolved)

    def test_inventory_does_not_name_the_retired_map(self):
        text = INVENTORY_PATH.read_text(encoding="utf-8")
        self.assertNotIn(RETIRED_MAP_VARIABLE, text)
        self.assertNotIn("serviceradar_uuid_map_address", text)

    def test_address_expressions_call_no_lookup(self):
        # Inventory compose refuses lookups before ansible-core 2.19, and
        # `strict: false` would hide the refusal by dropping the variable.
        expressions = {**INVENTORY["compose"], **INVENTORY["groups"]}
        for name, expression in expressions.items():
            with self.subTest(name=name):
                self.assertNotRegex(expression, r"\b(lookup|query|q)\s*\(")


class RenderedBlockTest(unittest.TestCase):
    def test_inventory_carries_what_the_render_script_produces(self):
        spec = importlib.util.spec_from_file_location(
            "render_proxmox_address_compose", ROOT / "scripts/render_proxmox_address_compose.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(
            INVENTORY_PATH.read_text(encoding="utf-8"),
            module.rendered_inventory(),
            "run scripts/render_proxmox_address_compose.py --write",
        )


if __name__ == "__main__":
    unittest.main()
