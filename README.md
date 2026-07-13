# serviceradar-ansible

Public Apache-2.0 automation for ServiceRadar operators. This repository now
contains three independent content families:

- Transactional Linux SSH user-CA enrollment for ServiceRadar remote access.
- Trusted QEMU Guest Agent installation for Windows Proxmox/QEMU guests.
- Existing ServiceRadar agent installation and AWX connectivity playbooks.

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
unknown layouts and higher-risk targets such as hypervisors.

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

## Agent installation content

Ansible playbooks for installing the [ServiceRadar](https://code.carverauto.dev/carverauto/serviceradar)
agent on managed hosts. This repository is registered as a git playbook
project in ServiceRadar/AWX; all playbooks live at the repository root so
the AWX project sync lists them.

## Playbooks

| Playbook | Purpose |
| --- | --- |
| `ping.yml` | Smoke test for the AWX -> device launch path. `ansible.builtin.ping` plus a fact-based debug line printing hostname, default IPv4, distro, and architecture. Read-only, no `become`. |
| `install-agent-debian.yml` | Installs `serviceradar-agent` on Debian/Ubuntu hosts (`apt`, `.deb`). |
| `install-agent-redhat.yml` | Installs `serviceradar-agent` on RHEL/Rocky/Alma/Fedora hosts (`dnf`/`dnf5`/`yum` via `ansible.builtin.package`, `.rpm`). |
| `install-qemu-guest-agent-windows.yml` | Installs and verifies QEMU Guest Agent on a pre-bootstrapped Windows QEMU/Proxmox guest. |
| `qemu-guest-agent-windows-preflight.yml` | Read-only discovery of mounted QGA MSI path, SHA-256, and Authenticode status. |

Both installers:

1. Resolve the release at runtime from the Forgejo API
   (`https://code.carverauto.dev/api/v1/repos/carverauto/serviceradar/releases/latest`,
   or `/releases/tags/v<version>` when `serviceradar_version` is set). The
   API call and download run **on the managed host**, so targets need
   outbound HTTPS to `code.carverauto.dev`.
2. Pick the asset matching the host architecture (see mapping below) and
   fail with the list of published agent assets if none matches.
3. Skip download + install when the exact target version is already
   installed (`dpkg-query` / `rpm -q`); a second run reports no changes.
4. Download to `/tmp`, install, delete the downloaded package.
5. Ensure the `serviceradar-agent` systemd service is **enabled and
   started**.

### Variables

| Variable | Default | Notes |
| --- | --- | --- |
| `target_hosts` | `all` | Host pattern for the play. In AWX, prefer leaving this alone and using the job template **limit** instead. |
| `serviceradar_version` | latest release | Pin a release, e.g. `1.4.2` or `v1.4.2` (leading `v` optional). |
| `serviceradar_validate_certs` | `true` | Set `false` only behind TLS-intercepting proxies. |
| `serviceradar_gateway_url` | unset | **Accepted but not applied** — see [Enrollment](#enrollment). The playbook prints a warning if set. |
| `serviceradar_join_token` | unset | **Accepted but not applied** — see [Enrollment](#enrollment). |

## Release artifact naming (observed from the API)

Verified against the latest release (`v1.4.2`) via
`GET /api/v1/repos/carverauto/serviceradar/releases/latest` (no auth
required):

- Debian package: `serviceradar-agent_1.4.2_amd64.deb`
  → pattern `serviceradar-agent_<version>_<debarch>.deb`
- RPM package: `serviceradar-agent-1.4.2-1-1.4.2-1.x86_64.rpm`
  → pattern `serviceradar-agent-<version>-<release>-<version>-<release>.<rpmarch>.rpm`
  (the doubled version-release is a CI artifact-naming quirk; the package
  inside is NVR `serviceradar-agent-<version>-<release>.<arch>`)
- Tarball (not used here): `serviceradar-agent_1.4.2_linux_amd64.tar.gz`
- Beware the near-miss `serviceradar-agent-gateway…` assets — those are a
  different component; the playbooks anchor their asset regex on
  `serviceradar-agent<sep><version>` to exclude them.

Architecture handling: `x86_64 -> amd64` for `.deb`, `x86_64` kept as-is
for `.rpm`; `aarch64`/`arm64` are mapped (`arm64` deb, `aarch64` rpm).
**As of v1.4.2 only amd64/x86_64 agent packages are published** — on an
ARM host the playbook fails fast with a clear message listing the assets
that do exist.

### Checksums

The `v1.4.2` release publishes **no per-package checksums** for the `.deb`
/ `.rpm` assets (no `.sha256` sidecars, no checksums file). The only
checksum published is inside `serviceradar-agent-release-manifest.json`,
which covers just the `linux_amd64` tarball used by the agent
self-updater. The packages are also not GPG-signed. Downloads therefore
run without checksum verification over TLS; if a `<asset>.sha256` sidecar
appears in a future release the playbooks pick it up and enforce it
automatically. RPM note: local installs succeed because dnf's
`localpkg_gpgcheck` defaults to off; hardened hosts that enable it must
relax it for this package.

## Package, service, and config facts

- Package name (deb and rpm): `serviceradar-agent`
- Systemd unit: `serviceradar-agent.service` (runs as user
  `serviceradar`, `Restart=always`; the package postinstall also enables
  it)
- Config shipped by the package: `/etc/serviceradar/agent.json`
  (`gateway_addr`, mTLS `gateway_security`), certs expected under
  `/etc/serviceradar/certs/`

### Enrollment

The package intentionally does not take a gateway URL or join token via a
config drop-in: the agent enrolls against the agent-gateway with an
onboarding token using the bundled CLI:

```sh
serviceradar-cli enroll   # uses an onboarding token issued by the core
```

Until enrollment assets exist (`/etc/serviceradar/agent.json` +
`/etc/serviceradar/certs/*.pem`), the started service retries/restarts on
its own (`Restart=always`) — that is expected. Because no config drop-in
exists, these playbooks deliberately do **not** template
`serviceradar_gateway_url` / `serviceradar_join_token` into any file
(inventing paths would be worse than skipping); they only print a warning
when those vars are set. The smoke goal of the installers is package
installed + service up.

## AWX job template setup

1. **Project**: this repository
   (`ssh://git@git.carverauto.dev/carverauto/serviceradar-ansible.git`,
   branch `main`). Playbooks are at the repo root, so the project sync lists
   every supported wrapper.
2. **Inventory**: the ServiceRadar device inventory.
3. **Job template (smoke)**: playbook `ping.yml`, machine credential for
   the device, **limit** = target hostname. No extra vars needed. Run
   this first to prove the AWX -> device path cheaply.
4. **Job template (install)**: playbook `install-agent-debian.yml` or
   `install-agent-redhat.yml`, machine credential, *privilege
   escalation* enabled (plays use `become: true`), **limit** = target
   host(s). Optional `extra_vars`:

   ```yaml
   serviceradar_version: 1.4.2   # omit to track latest
   ```

Each installer asserts the host's `os_family`, so launching the wrong
variant against a host fails immediately with a pointer to the right one.
