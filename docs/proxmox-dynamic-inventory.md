# Proxmox dynamic inventory with verified TLS

The public `inventory/proxmox.proxmox.yml` source discovers running Proxmox
guests without committing an API token or CA certificate. It always enables
certificate validation. AWX supplies the API fields and a reviewed CA bundle
through the versioned custom credential definition under
`awx/credential-types/proxmox-api-token-ca/v1/`.

## Controller setup

1. Use an execution environment whose supported Ansible Core,
   `community.proxmox`, `proxmoxer`, and `requests` versions are mutually
   compatible. Treat a collection compatibility warning as a failed readiness
   check rather than silently accepting an unsupported combination.
2. Create the custom credential type from the published `inputs.json` and
   `injectors.json` without changing the fields or injectors.
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
