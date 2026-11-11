#!/usr/bin/env python3
"""Render the address-selection block of inventory/proxmox.proxmox.yml.

An inventory `compose` entry is one Jinja expression and cannot read another
composed variable, so every entry has to repeat the fragments it shares with
the others. They are defined once here and the inventory carries the rendered
result between two marker comments. Run with --write after changing a
fragment; tests/test_proxmox_inventory_addresses.py fails when the two differ.
"""

from __future__ import annotations

from pathlib import Path
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "inventory/proxmox.proxmox.yml"
BEGIN = "# BEGIN rendered by scripts/render_proxmox_address_compose.py\n"
END = "# END rendered by scripts/render_proxmox_address_compose.py\n"
# Proxmox accepts net0 through net31 on a guest.
NET_DEVICE_COUNT = 32

# The configured primary NIC: net0, else the lowest-numbered netN. The plugin
# exposes each as proxmox_netN, parsed into a dict when every comma-separated
# part is key=value and left as the raw string otherwise; `string` makes one
# text of either shape, and of nothing at all.
PRIMARY_NET = (
    "(["
    + ", ".join(f"proxmox_net{index}" for index in range(NET_DEVICE_COUNT))
    + "] | select('defined') | first | default('') | string)"
)
# A complete MAC, so that a slice of an IPv6 address can never match.
PRIMARY_MAC = (
    f"({PRIMARY_NET} | regex_search("
    "'(?<![0-9a-f:.])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f:.])', ignorecase=True))"
)
# `(?!)` matches nothing, so a guest without a configured MAC selects no
# interface instead of every interface that reports an empty one.
PRIMARY_MAC_PATTERN = f"('(?i)^' ~ ({PRIMARY_MAC} | default('(?!)', true)) ~ '$')"
# First IPv4 address that is neither loopback nor link-local.
FIRST_USABLE_IPV4 = (
    "map('string') | map('regex_replace', '/.*$', '') "
    "| select('match', '^[0-9]+([.][0-9]+){3}$') "
    "| reject('match', '^(127|169[.]254)[.]') | first | default('')"
)


def reported_address(interfaces: str, mac_key: str, addresses: str) -> str:
    """Address of the reported interface that carries the primary MAC."""
    return (
        f"([{interfaces} | default([])] | flatten | select('mapping') "
        f"| selectattr('name', 'string') | selectattr('{mac_key}', 'string') "
        f"| selectattr('{mac_key}', 'match', {PRIMARY_MAC_PATTERN}) | sort(attribute='name') "
        f"| {addresses} | {FIRST_USABLE_IPV4})"
    )


GUEST_AGENT_ADDRESS = reported_address(
    "proxmox_agent_interfaces", "mac-address", "map(attribute='ip-addresses', default=[]) | flatten"
)
LXC_INTERFACE_ADDRESS = reported_address(
    "proxmox_lxc_interfaces", "hwaddr", "map(attribute='inet', default='')"
)
# A static ip=<cidr> on an LXC primary NIC; ip=dhcp and ip=manual do not match.
# Two searches and no capture group: a backreference argument needs a
# backslash, which ansible-core releases do not unescape alike.
LXC_CONFIG_ADDRESS = (
    f"(({PRIMARY_NET} | regex_search("
    "\"(?:^|[{, ])'?ip'?[=:] ?'?[0-9]+(?:[.][0-9]+){3}(?=[/,']|$)\") | default('', true) "
    "| regex_search('[0-9]+(?:[.][0-9]+){3}$') | default('', true)) "
    "if (proxmox_vmtype | default('')) == 'lxc' else '')"
)
UUID_MAP_ADDRESS = (
    "((lookup('ansible.builtin.env', 'SERVICERADAR_PROXMOX_UUID_ADDRESSES') "
    "| default('{}', true) | from_json)"
    ".get((proxmox_smbios1 | default({})).get('uuid'), None))"
)

COMPOSE = {
    "ansible_host": (
        f"{GUEST_AGENT_ADDRESS} or {LXC_CONFIG_ADDRESS} or {LXC_INTERFACE_ADDRESS} "
        f"or {UUID_MAP_ADDRESS} or ansible_host"
    ),
    "serviceradar_address_source": (
        f"'guest_agent_primary_nic' if {GUEST_AGENT_ADDRESS} "
        f"else 'lxc_config' if {LXC_CONFIG_ADDRESS} "
        f"else 'lxc_interface' if {LXC_INTERFACE_ADDRESS} "
        "else 'plugin_default' if (ansible_host | default('', true)) else 'none'"
    ),
    "serviceradar_primary_mac": f"{PRIMARY_MAC} | default('', true) | lower",
    "serviceradar_uuid_map_address": f"{UUID_MAP_ADDRESS} | default('', true)",
}


def render() -> str:
    lines = ["compose:"]
    for name, expression in COMPOSE.items():
        lines.append(f"  {name}: >-")
        lines.extend(
            textwrap.wrap(
                expression,
                width=100,
                initial_indent="    ",
                subsequent_indent="    ",
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return "\n".join(lines) + "\n"


def rendered_inventory() -> str:
    """The inventory text with the block between the markers re-rendered."""
    text = INVENTORY.read_text(encoding="utf-8")
    head, _, rest = text.partition(BEGIN)
    _, _, tail = rest.partition(END)
    if not rest or not tail:
        raise SystemExit(f"{INVENTORY} has lost its rendered-block markers")
    return head + BEGIN + render() + END + tail


def main() -> None:
    if sys.argv[1:] == ["--write"]:
        INVENTORY.write_text(rendered_inventory(), encoding="utf-8")
    elif sys.argv[1:]:
        raise SystemExit("usage: render_proxmox_address_compose.py [--write]")
    else:
        sys.stdout.write(render())


if __name__ == "__main__":
    main()
