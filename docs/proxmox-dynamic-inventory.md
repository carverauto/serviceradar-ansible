# Proxmox dynamic inventory with verified TLS

The public `inventory/proxmox.proxmox.yml` source discovers running Proxmox
guests without committing an API token or CA certificate. It always enables
certificate validation. AWX supplies the API fields and a reviewed CA bundle
through a versioned custom credential definition under `awx/credential-types/`.

## Controller setup

1. Use an execution environment whose supported Ansible Core,
   `community.proxmox`, `proxmoxer`, and `requests` versions are mutually
   compatible. Treat a collection compatibility warning as a failed readiness
   check rather than silently accepting an unsupported combination. The AWX
   project dependency is pinned in `collections/requirements.yml`; project
   collection syncing must be enabled so AWX installs that exact version.
2. For a directly reachable cluster, create the custom credential type from
   `proxmox-api-token-ca/v1/inputs.json` and `injectors.json` without changing
   the fields or injectors. For a cluster reachable only through a controlled
   network relay, use `proxmox-api-token-ca-connect-relay/v1/` instead.
3. Create one credential instance for one Proxmox cluster. Set `url` to the
   reviewed bare HTTPS PVE origin, use a least-privilege API token, and paste
   only the independently obtained public CA chain into `ca_bundle`.
4. Create one AWX inventory and SCM inventory source for that cluster. Select
   this repository, source path `inventory/proxmox.proxmox.yml`, and the exact
   cluster credential. Enable overwrite and update-on-launch as appropriate.
5. Sync the inventory and reject the result if stdout contains an
   `InsecureRequestWarning`, certificate-validation failure, unsupported
   collection warning, or an unexpected host set.
6. Import the inventory into ServiceRadar. ServiceRadar binds execution to the
   controller ID, AWX inventory ID, AWX host ID, and canonical device UID;
   display names and IP addresses are not execution identities.

## Management address selection

The address comes from data Proxmox holds. No per-host input is needed and the
order in which a guest lists its interfaces does not matter.

Proxmox records the virtual NIC it gave each guest: `net0` in the guest's
configuration, or the lowest-numbered `netN` when there is no `net0`, carries
that NIC's MAC address. The inventory treats it as the primary NIC and reads
the management address from the guest interface that reports the same MAC,
compared without regard to case. A Kubernetes node that lists an IPVS dummy
device, CNI veth pairs and tunnel devices ahead of its real NIC therefore
resolves to the NIC Proxmox attached, not to an address only the node itself
can reach.

Sources are tried in this order and the first one that yields an address wins:

1. **QEMU guest with a working QEMU Guest Agent.** Among the interfaces the
   agent reports with the primary MAC, the first IPv4 address that is neither
   loopback (`127.0.0.0/8`) nor link-local (`169.254.0.0/16`). When several
   interfaces carry that MAC, such as a bridge or VLAN device on top of the
   NIC, they are read in name order. No other interface of the guest is ever
   used, even when the primary NIC has no usable IPv4 address.
2. **LXC container with a static address.** An `ip=<cidr>` on the primary NIC
   that is not `dhcp` or `manual` is authoritative, including when the
   container reports nothing.
3. **LXC container without a static address.** The same rule as for a QEMU
   guest, applied to the interfaces Proxmox reports for the container and the
   primary NIC's `hwaddr`.
4. **The inventory plugin's own address.** The plugin sets one for Proxmox
   nodes only: the first interface, sorted by name, that reports an active
   field, an address, and a gateway.

Only IPv4 is selected. A guest whose primary NIC has only IPv6 addresses is
unresolved.

### What the inventory reports

Every host carries the decision as host variables, so neither an operator nor
a downstream tool has to read the expressions:

| Variable | Meaning |
| --- | --- |
| `ansible_host` | The chosen address. Absent when nothing resolved; it is never an empty string. |
| `serviceradar_address_source` | Which Proxmox-held data produced the address; see the next table. |
| `serviceradar_primary_mac` | Lower-case MAC of the primary NIC, or an empty string when the guest has no configured NIC. |

| `serviceradar_address_source` | Meaning |
| --- | --- |
| `guest_agent_primary_nic` | Reported by the QEMU Guest Agent on the interface with the primary MAC. |
| `lxc_config` | The static `ip=` of the container's primary NIC. |
| `lxc_interface` | Reported by Proxmox for the container interface with the primary MAC. |
| `plugin_default` | The plugin's own address; Proxmox nodes. |
| `none` | Proxmox data produced no address. |

A guest with source `none` has no `ansible_host` and is placed in the
`address_unresolved` group. Exclude it from a run with
`--limit '!address_unresolved'`, or list the group to see what needs
attention. Without `ansible_host`, Ansible would try to connect to the guest's
Proxmox display name, so do not treat a host in this group as a reviewed
connection target. The plugin does not evaluate groups for Proxmox nodes; read
`serviceradar_address_source` on a node instead.

### A QEMU guest needs a working guest agent

Automatic addressing of a QEMU guest depends on the QEMU Guest Agent: the
agent option must be enabled on the VM, and the agent must be installed and
running inside it. When the agent is disabled, stopped, or not answering, or
when it reports no interface with the primary MAC, the operator sees:

- `serviceradar_address_source: none` on the host, with
  `serviceradar_primary_mac` still showing the NIC that was looked for;
- the host in the `address_unresolved` group;
- no `ansible_host` on the host.

There is no manual override: the inventory has no per-host address input, so
the way to address such a guest is to get its agent working. For Windows
guests, `install-qemu-guest-agent-windows.yml` installs it.

Earlier revisions read an operator-supplied map from SMBIOS UUID to address
out of the `SERVICERADAR_PROXMOX_UUID_ADDRESSES` environment variable. It has
been removed and the variable is ignored; delete it from the inventory source
configuration.

### Changing the expressions

A `compose` entry cannot read another composed variable, so the entries repeat
the fragments they share. The fragments are defined once in
`scripts/render_proxmox_address_compose.py`, and the inventory carries the
rendered block between two marker comments. Edit the script, run it with
`--write`, and commit both files; the repository checks fail when they differ.
Inventory `compose` runs with lookups disabled before ansible-core 2.19, so an
expression must not call `lookup` or `query`.

After every source change, sync AWX, import memberships into ServiceRadar,
and review the resulting controller/inventory/host/device bindings again.

## Restricted CONNECT relay

The relay credential type adds one required, non-secret `https_proxy` field.
Set it to a reviewed HTTP proxy origin such as `http://relay.example:3128`.
The Python HTTPS client sends a CONNECT request and then authenticates the PVE
certificate through that tunnel with the independently supplied CA bundle. The
relay must never terminate or re-sign TLS.

Treat the relay as network policy, not as an authentication service. Restrict
its listeners to the AWX execution-node addresses and restrict CONNECT targets
to the exact PVE addresses and TCP port 8006. Do not configure proxy userinfo,
response caching, TLS interception, a broad destination ACL, or an Internet-
reachable listener. Keep each Proxmox credential bound to its original PVE
HTTPS origin; do not replace the PVE URL with the relay address.

Create a separate inventory and credential for every cluster. This is required
when two clusters reuse names such as `pve01` or VMID `100`: AWX may reuse the
same display hostname in different inventories, while ServiceRadar preserves
the inventory-scoped identity. Do not merge such clusters into a single
hostname-keyed inventory.

The CA file is public trust material, but it still comes from an operator-owned
credential so a project commit cannot replace the trust anchor. The token
secret remains an AWX secret input and is exposed only to the inventory update
process. Never put the token, an API authorization header, or
`validate_certs: false` in SCM, source variables, surveys, or job extra vars.
