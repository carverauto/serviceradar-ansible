# serviceradar-ansible

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
   branch `main`). Playbooks are at the repo root, so the project sync
   lists all three.
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
