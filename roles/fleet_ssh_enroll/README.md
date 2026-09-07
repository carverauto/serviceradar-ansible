# Fleet SSH enrollment role

Converges one Debian 12 fleet host on the manually verified pve02 layout for
[serviceradar#4376](https://github.com/carverauto/serviceradar/issues/4376):

- POSIX account `fleet_ssh_user` (default `mfreeman`) with `/bin/bash`, a
  locked password (`!`), and no supplementary groups.
- No sudo: the role fails closed when `/etc/sudoers.d/<user>` exists and
  never creates a grant.
- Public user-CA trust at `/etc/ssh/serviceradar_user_ca.pub` (0644).
- Per-account principals at `/etc/ssh/auth_principals/<user>` (0644)
  matching the dusk01 principal policy.
- `sshd` drop-in at
  `/etc/ssh/sshd_config.d/60-serviceradar-user-ca.conf` carrying
  `TrustedUserCAKeys` and `AuthorizedPrincipalsFile`.
- `sshd -t` plus account-aware `sshd -T -C` proof before the `ssh` service
  is reloaded (never restarted). A failed proof stops the play, so the
  reload handler never runs.

## Scope

This role is deliberately separate from `remote_access_ssh_ca`: that
collection path fails closed on hypervisors and manages a transactional
overlap/retire lifecycle, while Proxmox VE fleet nodes need the exact static
pve02 layout. It is also separate from the host-agent installer and the demo
Settings page.

Only Debian 12 is supported. The CA private key, signed certificates,
tokens, and inventory secrets never appear here: the three required values
(`fleet_ssh_ca_public_key`, `fleet_ssh_ca_fingerprint`,
`fleet_ssh_principals`) arrive per run from ansible-vault, environment, or
extra vars. See `docs/fleet-ssh-ca-enrollment.md`.
