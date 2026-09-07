# Fleet SSH-CA enrollment operator guide

Replicates the manually verified **pve02** fix to the rest of the fleet for
[serviceradar#4376](https://github.com/carverauto/serviceradar/issues/4376)
(`knownhosts: key is unknown` in the webconsole). Two halves:

1. **Server side** (`install-fleet-ssh-ca.yml`): create the locked,
   privilege-free POSIX user and install the user-CA trust plus
   dusk01-policy principals on every fleet host.
2. **Client side** (`install-fleet-ssh-known-hosts.yml`): collect fleet host
   keys into a fragment and install it in the ServiceRadar host's
   `known_hosts` bundle so the Go `knownhosts` verifier accepts the fleet.

## Reference layout (pve02, verified 2026-09-07)

| Item | pve02 value |
| --- | --- |
| Account | `mfreeman`, uid 1000, `/bin/bash`, `passwd -S` → `L`, groups: `mfreeman` only |
| Sudo | none (no grant; `sudo` is not installed) |
| Drop-in | `/etc/ssh/sshd_config.d/60-serviceradar-user-ca.conf` (0644) |
| CA trust | `/etc/ssh/serviceradar_user_ca.pub` (0644), fingerprint `SHA256:O/GMeaLmQ57/uygd+nF0lSXapNngTeQ4gXqhHtwPQfk` |
| Principals | `/etc/ssh/auth_principals/mfreeman` (0644), one `srp_v1_…` line identical to dusk01's policy |
| Effective policy | `sshd -T -C user=mfreeman,addr=127.0.0.1,host=localhost` shows the CA path, principals path, `pubkeyauthentication yes` |

dusk01 carries the same CA and principals under its own IPA-managed paths;
it is the principal-policy reference, not an enrollment target.

## Secrets contract

The public tree stays non-secret. Never commit the CA private key, signed
certificates, tokens, fingerprints-plus-host bindings, or real
hostnames/addresses. Supply the three required values per run:

```bash
# Option A: vault file (recommended for AWX/CLI reuse)
ansible-vault create /run/secrets/fleet-ssh-ca.yml   # defines
# fleet_ssh_ca_public_key, fleet_ssh_ca_fingerprint, fleet_ssh_principals
ansible-playbook install-fleet-ssh-ca.yml -i inventory/fleet.ini \
  -e @/run/secrets/fleet-ssh-ca.yml

# Option B: environment (ephemeral CI/operator shell)
FLEET_SSH_CA_PUBLIC_KEY='ssh-ed25519 AAAA... fleet-user-ca' \
FLEET_SSH_CA_FINGERPRINT='SHA256:...' \
FLEET_SSH_PRINCIPALS='srp_v1_...,srp_v1_...' \
  ansible-playbook install-fleet-ssh-ca.yml -i inventory/fleet.ini

# Option C: extra vars file (documented, non-vault only for placeholders)
ansible-playbook install-fleet-ssh-ca.yml -i inventory/fleet.ini \
  -e @examples/fleet-ssh-ca-inventory.yml
```

`examples/fleet-ssh-ca-inventory.yml` uses TEST-NET-1 documentation
addresses and placeholder key material only. Your runtime inventory
(`inventory/fleet.ini` or AWX inventory with a reviewed limit) holds the
real fleet and is never committed.

## Run order

```bash
# 0. Dry run: reports planned changes, runs no verify gates.
ansible-playbook install-fleet-ssh-ca.yml -i inventory/fleet.ini \
  -e @/run/secrets/fleet-ssh-ca.yml --check

# 1. Enroll one canary first (pve02 already matches; start with one peer).
ansible-playbook install-fleet-ssh-ca.yml -i inventory/fleet.ini \
  -e @/run/secrets/fleet-ssh-ca.yml --limit fleet-host-01

# 2. Prove certificate login through a fresh connection before widening:
ssh -o IdentitiesOnly=yes -i /path/to/signed-cert-key \
  mfreeman@fleet-host-01 'whoami && sshd -V 2>&1 | head -1'

# 3. Enroll the rest of the fleet (no moving-branch import in AWX: pin the
#    reviewed commit per the immutable import checklist).
ansible-playbook install-fleet-ssh-ca.yml -i inventory/fleet.ini \
  -e @/run/secrets/fleet-ssh-ca.yml

# 4. Refresh the webconsole known_hosts fragment (controller-local, no secrets).
ansible-playbook install-fleet-ssh-known-hosts.yml \
  -e '{"fleet_host_key_targets": ["fleet-host-01", "fleet-host-02"]}' \
  -e fleet_known_hosts_path=/tmp/fleet-known-hosts
ssh-keygen -Hf /tmp/fleet-known-hosts
# Append the hashed fragment to the ServiceRadar known_hosts bundle and
# restart the webconsole service; confirm the 4376 handshake error is gone.
```

## Safety properties

- Fail-closed platform gate: Debian 12 only (the pve02 reference).
- Fixed paths: overrides are not variables, so the fleet cannot drift.
- Locked account: `password: "!"` converges `passwd -S` to `L` even when the
  account already exists; supplementary groups are stripped; any existing
  `/etc/sudoers.d/<user>` grant aborts the run.
- CA key shape plus `ssh-keygen` fingerprint proof against the pinned
  `SHA256:` value before reload.
- Full `sshd -t` plus account-aware `sshd -T -C` proof before reload; the
  `ssh` service is reloaded, never restarted, and only when every proof on
  the host passes (failed proofs stop the play before handlers run).
- Principals must be opaque `srp_v1_` tokens; account names and key options
  are rejected.
- Removal is out of scope: this playbook only converges the enrolled state.
  To decommission a host, delete the three owned paths by hand and reload
  sshd; the account itself is never removed automatically.
