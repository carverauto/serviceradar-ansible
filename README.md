# serviceradar-ansible

Public Apache-2.0 automation for ServiceRadar operators. This repository now
contains six independent content families:

- Transactional Linux SSH user-CA enrollment for ServiceRadar remote access.
- Trusted QEMU Guest Agent installation for Windows Proxmox/QEMU guests.
- Fingerprint-pinned Linux system CA trust for private HTTPS integrations.
- CA-verified Proxmox dynamic inventory for cluster-scoped ServiceRadar import.
- A source-restricted, read-only SNMP agent on Linux hosts for ServiceRadar polling.
- Existing ServiceRadar agent installation and AWX connectivity playbooks.

Repository CI is the GitHub Actions workflow
[`.github/workflows/quality.yml`](.github/workflows/quality.yml). It runs for
every pull request and for pushes to `main` on GitHub-hosted `ubuntu-24.04`
runners, with a read-only token and no secrets, so fork pull requests get the
same gate. It must not be moved to a self-hosted runner. Run the same checks
locally with `scripts/check.sh` after installing `requirements-ci.lock` and
`requirements.yml`.

## SSH remote-access enrollment

The `serviceradar.remote_access` collection-compatible layout installs only
public SSH user-CA trust and target-specific principals. It never contains,
requests, or transports a CA private key. It also does not create accounts or
change passwords, PAM, LDAP, sudo, host keys, or unrelated sshd policy.

The safe lifecycle is intentionally split across AWX jobs:

1. `preflight` validates OS, systemd/sshd layout, conflicts, accounts, public
   key fingerprints, FIPS compatibility, and effective Match contexts without
   changing the host.
2. `stage` snapshots all role-owned state, validates a complete candidate,
   atomically activates it, arms a persistent boot/deadline rollback guard,
   validates the live daemon, and reloads (never restarts) sshd.
3. `verify` runs as a separate SSH job with the snapshotted machine-credential
   reference and writes a target/transaction/generation/files-digest proof.
4. `commit` compares that proof under the same host lock used by rollback,
   then disarms the guard. A missing or failed verify/commit rolls back.

Supported targets are Ubuntu 22.04/24.04, Debian 12, and Rocky Linux 9 with a
single non-socket-activated systemd ssh/sshd instance and the standard
`/etc/ssh/sshd_config.d/*.conf` include. The first release fails closed on
unknown layouts and higher-risk targets such as hypervisors. On Rocky Linux 9
the stock `50-redhat.conf` crypto-policy `Include` is the one nested include
preflight accepts; see the
[supported matrix](docs/remote-access-ssh-ca.md#supported-matrix).

### Security modes

`remote-access-direct-*.yml` wrappers are for operator-managed controllers.
They accept explicit per-host public material and make no ServiceRadar RBAC,
audit, canonical identity, or readiness claim.

`remote-access-integrated-*.yml` wrappers are the only catalog-eligible paths.
They call `remote_access.ssh_ca.bundle.read` once on the reviewed AWX execution
environment using a one-use custom credential. They verify exact play-host and
immutable `(controller, inventory, AWX host ID, canonical device UID)` tuple set
equality before gathering target facts. Direct inputs cannot downgrade an
integrated wrapper. The callback bearer and fleet response are never sent to a
managed host or written to facts, artifacts, relaunch data, or logs.
The callback also carries AWX's system-provided `JOB_ID`, read directly from the
execution environment rather than injected by the custom credential, so a copy
or relaunch cannot reuse another accepted job's grant.
Before the callback, one controller-local task runs for every AWX-limited host
to materialize the exact host-ID set in AWX without opening a managed-host
connection; ServiceRadar activates the grant only after that set matches.

Create the exact versioned custom credential type with the published
[`inputs.json`](awx/credential-types/serviceradar-ephemeral-callback/v1/inputs.json)
and
[`injectors.json`](awx/credential-types/serviceradar-ephemeral-callback/v1/injectors.json),
then generate the ServiceRadar binding digest from AWX's assigned type ID. The
[operator guide](docs/awx-ephemeral-callback-credential.md) documents the UI/API
workflow, canonical contract, and cross-language conformance vector. The
artifacts contain definitions and placeholders only, never a live credential.

Integrated launch requires both `ansible.runs.launch` and
`devices.remote_access.ssh.ca_bundle.read`. Retirement additionally requires
`devices.remote_access.ssh.ca_trust.retire` plus a fresh selected-edge login
proof from the new CA. Removal additionally requires
`devices.remote_access.ssh.ca_trust.remove`.

See [the operator guide](docs/remote-access-ssh-ca.md),
[`catalog/remote-access-ssh-ca.yml`](catalog/remote-access-ssh-ca.yml), and the
non-secret examples in `examples/`. Production imports must pin a reviewed
commit and content SHA256; do not bind AWX to a moving branch.

The initial catalog metadata is deliberately gated with
`production_import_ready: false`. Do not bind these integrated wrappers to a
live ServiceRadar/AWX instance until the mutation/rollback matrix and the
separate callback-grant and hardened-targeting dependencies pass together.

## Windows QEMU Guest Agent

`install-qemu-guest-agent-windows.yml` installs or upgrades the upstream QEMU
Guest Agent MSI on an existing 64-bit Windows guest. It accepts either a pinned
HTTPS `.msi` plus mandatory SHA-256, or an explicit MSI path on a mounted
VirtIO CD-ROM. TLS validation is always enabled; Authenticode is required by
default, with an explicit checksum-pinned mounted-ISO exception for upstream
unsigned QGA MSI builds. After installation it configures `QEMU-GA` as
automatic/running and verifies the service's actual binary and version.

The playbook does not bootstrap Windows management, install the VirtIO serial
driver, alter VM hardware, or hold a Proxmox credential. Enable the QGA channel
on the exact VM and establish WinRM or Windows OpenSSH first. See the
[Windows QGA operator guide](docs/windows-qemu-guest-agent.md), the
[role interface](roles/windows_qemu_guest_agent/README.md), and the non-secret
[inventory example](examples/windows-qemu-guest-agent-inventory.yml).
The repository also includes a reproducible
[`execution-environment.yml`](execution-environment.yml) that layers the pinned
`ansible.windows 2.4.0` collection onto AWX EE 24.6.1. This keeps the collection
inside that AWX release's supported Ansible Core 2.15 runtime.

## Linux private-API CA trust

`install-linux-trusted-ca.yml` installs or removes operator-supplied public CA
certificates on Debian/Ubuntu or EL 9 hosts. A present certificate must be a
valid `CA:TRUE` certificate and match its required SHA-256 DER fingerprint.
The role never fetches a CA from the endpoint it is about to trust and never
accepts a TLS-disable option. It validates the complete supplied CA set before
making the first trust-store change and still performs that validation in
Ansible check mode.

This is intended for edge agents that call private HTTPS integrations such as
Proxmox. It can restart exact named services after a trust-store change and
then prove selected HTTPS URLs with normal certificate verification. Keep the
public CA inputs immutable in a reviewed AWX job template, disable prompting
for them, and launch the template from ServiceRadar rather than directly in AWX,
against the exact canonical device limit. See the
[role interface](roles/linux_trusted_ca/README.md).

## Linux SNMP agent for ServiceRadar polling

`install-linux-snmp-agent.yml` installs and configures the distribution `snmpd`
on Debian 12, Ubuntu 22.04/24.04 and Rocky Linux 9 hosts, as VMs or LXC
containers, so that a ServiceRadar agent can poll them. SNMPv3 with
authentication and privacy (SHA-256 or stronger, AES) is the default. SNMPv2c
is an explicit, read-only opt-in that has no default community and refuses
well-known ones such as `public`.

The SNMP secret is never set in this repository, an inventory, a survey, or
job-template extra variables. Create the custom credential type from
[`inputs.json`](awx/credential-types/linux-snmp-agent/v1/inputs.json) and
[`injectors.json`](awx/credential-types/linux-snmp-agent/v1/injectors.json),
store the SNMPv3 user and passphrases in a credential of that type, and attach
it to the job template. AWX encrypts the values at rest and injects them into
the job's environment at launch; the role reads them there and logs none of
them. ServiceRadar polls with its own, separate credential store, so enter the
same values in ServiceRadar's credential settings as well.

The one required variable is `linux_snmp_agent_poller_sources`, the IPv4
addresses or CIDRs of the ServiceRadar agents that poll the host:

```yaml
linux_snmp_agent_poller_sources:
  - 192.0.2.10
  - 198.51.100.0/28
```

The role refuses an empty or over-broad source list. It restricts the agent
to those sources with TCP wrappers, a systemd IP filter and, when firewalld or
ufw is already active, firewall rules; it does not install a firewall. Every
run then queries the local agent with the supplied credential, and fails and
stops the agent if it answers a source outside the list or the community
`public`. `linux_snmp_agent_state: absent` removes the configuration. See the
[role interface](roles/linux_snmp_agent/README.md) for the inputs, the AWX
steps, passphrase rotation and the container limits.

## Fleet SSH-CA enrollment (serviceradar#4376)

`install-fleet-ssh-ca.yml` converges every fleet host on one verified
reference layout: a locked, privilege-free POSIX user plus OpenSSH user-CA
trust with opaque policy principals on Debian 12 hosts. `sshd -t` and
account-aware `sshd -T -C` proofs gate an `ssh` reload (never a restart).
`install-fleet-ssh-known-hosts.yml` collects fleet host keys into a fragment
for the webconsole `knownhosts` verifier. Secrets and real inventory travel
only via ansible-vault, environment, or per-run extra vars; the public tree
carries placeholders. See the
[fleet enrollment guide](docs/fleet-ssh-ca-enrollment.md), the
[role interface](roles/fleet_ssh_enroll/README.md), and the non-secret
[inventory example](examples/fleet-ssh-ca-inventory.yml). This path is
separate from the transactional `remote_access_ssh_ca` collection (which
fails closed on hypervisors), the host-agent installer, and the demo
Settings page.

## Proxmox dynamic inventory

`inventory/proxmox.proxmox.yml` discovers running guests with TLS verification
enabled. AWX reaches the Proxmox API directly. The published AWX custom
credential type injects a least-privilege API token and a temporary
`REQUESTS_CA_BUNDLE` file; neither belongs in git or inventory variables. Use
one AWX inventory per Proxmox cluster so reused PVE hostnames and VMIDs remain
distinct through ServiceRadar's controller/inventory/host identity.

Each guest's management address is chosen from data Proxmox holds, with no
per-host input: the guest interface whose MAC equals that of the guest's
primary configured NIC (`net0`), or the static address of an LXC container.
A QEMU guest needs a working QEMU Guest Agent for this. Every host reports the
decision in `serviceradar_address_source`, and a guest with no resolvable
address has no `ansible_host` and lands in the `address_unresolved` group. See
the [Proxmox inventory guide](docs/proxmox-dynamic-inventory.md).

## Agent installation content

The root `install-agent-debian.yml` and `install-agent-redhat.yml` playbooks
install the [ServiceRadar](https://github.com/carverauto/serviceradar) agent on
Debian-family and RedHat-family Linux hosts respectively. They require an
existing Ansible SSH connection and privilege escalation. `ping.yml` remains a
read-only connectivity check; it does not install or enroll an agent.

Both installers select a package for the target architecture, verify the exact
installed version, and enable the `serviceradar-agent` systemd service. They
start the service only when its enrollment configuration and certificates
already exist. An installed package without those assets is reported as
`installed_awaiting_enrollment`.

### Pinned package deployment

Use all three variables together to deploy a reviewed artifact without making
any release API request:

```yaml
serviceradar_version: "5.6.7"
serviceradar_agent_package_url: "https://artifacts.example.com/serviceradar-agent_5.6.7_amd64.deb"
serviceradar_agent_package_sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
```

These values are synthetic examples. Supply the URL, actual package version,
and independently obtained SHA-256 of the package being deployed. The URL may
use HTTP or HTTPS; the required checksum is enforced in either case. The
managed host downloads the package, so it needs access to that artifact URL.
Use the RPM installer and its matching artifact for RPM-based hosts. A partial
pin, an invalid checksum, or a missing version fails before any download.

### GitHub release discovery

When both pinned artifact inputs are omitted, the installers resolve
`https://api.github.com/repos/carverauto/serviceradar/releases/latest`, or
`/releases/tags/v<version>` when `serviceradar_version` is provided.

The Ansible controller (the AWX execution environment) makes that request,
without privilege escalation, once per distinct release for each batch of
hosts in the play. Every host then selects the package for its own
architecture from the same answer. The controller therefore needs access to
the GitHub API, and managed hosts need access only to the returned package
download URLs. The request is anonymous, so no API token is stored or passed.

GitHub limits anonymous API requests per source address. A rate-limited
lookup fails before any host is changed, reports the HTTP status and the time
the limit resets, and is not retried. Any other unusable answer reports its
HTTP status; only transport and server errors are retried. A missing release
or missing/ambiguous package fails as well. Each of these failures points to
the pinned package inputs, which make no API request.

Debian asset names must match `serviceradar-agent_<version>_<architecture>.deb`.
RPM names must start with `serviceradar-agent-<version>` and end in
`.<architecture>.rpm`. These patterns exclude the agent-gateway packages.
Debian maps `x86_64` to `amd64` and `aarch64` to `arm64`; RPM uses `x86_64` or
`aarch64`. Exactly one matching asset must be available.

Release discovery uses a `<package-name>.sha256` sidecar when one is present.
Pinned deployment always requires SHA-256. The installers do not disable
package-manager signature policy; RPM hosts requiring signed local packages
must use an artifact that satisfies their configured policy.

### Installer inputs

| Variable | Default | Purpose |
| --- | --- | --- |
| `serviceradar_version` | Latest GitHub release | Required with a pinned URL; leading `v` is optional. |
| `serviceradar_agent_package_url` | Unset | Exact HTTP(S) package URL; requires SHA-256 and version. |
| `serviceradar_agent_package_sha256` | Unset | Exact 64-character package SHA-256. |
| `target_hosts` | `all` | Leave this default in AWX and use the reviewed job limit. |
| `serviceradar_validate_certs` | `true` | HTTPS certificate verification for metadata and downloads. |

Pinned deployment records the verified package SHA-256 in
`/etc/serviceradar/agent-package.sha256`, owned by root. A changed or unrecorded
pin installs the requested bytes even when the package version is unchanged;
the same version and pin skip download and installation on subsequent runs.
GitHub release discovery remains version-based. The installers check the
installed version before recording a pin and verify that an
enrolled agent's service is active. A successful service check does not prove
connectivity; verify a fresh agent heartbeat in ServiceRadar after deployment.

### Check mode

Both installers support `--check`. A dry run resolves the artifact, compares it
with the installed package, probes the package URL without downloading it, and
changes nothing. Its final report has `status: planned`, a `package` action of
`install`, `reinstall`, or `unchanged`, and the package `source`. On a host
that does not have the package yet, the steps that need the packaged account
and systemd unit are skipped until the real run.

### Separate enrollment

The package includes `srctl`. Enroll each new agent using a separately issued
onboarding token with `srctl enroll`, then start `serviceradar-agent`. The
installers do not accept or persist onboarding secrets and do not configure a
gateway from `serviceradar_gateway_url` or `serviceradar_join_token`.

Enrollment readiness requires these existing files:

- `/etc/serviceradar/agent.json`
- `/etc/serviceradar/certs/component.pem`
- `/etc/serviceradar/certs/component-key.pem`
- `/etc/serviceradar/certs/ca-chain.pem`

Their contents are not read by the readiness check. Existing enrollment assets
remain in place during an upgrade. Hosts without them have the package and
enabled service installed, awaiting explicit enrollment; the installer does
not force an unconfigured service to start.

### AWX deployment

Sync this repository into an AWX project and pin the reviewed SCM revision.
Create separate templates for `install-agent-debian.yml` and
`install-agent-redhat.yml`, using a reviewed execution environment and machine
credential with privilege escalation. Keep artifact inputs fixed for the
rollout and let ServiceRadar supply the exact canonical device limit.

Deploy one canary of each operating-system family first. Check the package
version, service state, and a fresh connected-agent heartbeat before expanding
to the remaining compatible inventory hosts. Record unenrolled or failed hosts
explicitly; an AWX job completing does not establish agent connectivity.
