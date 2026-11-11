# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Collection-compatible SSH user-CA enrollment and offboarding roles.
- Separate direct-controller and ServiceRadar-integrated AWX wrappers.
- Fail-closed platform, account, CA fingerprint, principal, and sshd policy preflight.
- Generation-bound staged changes with persistent rollback, fresh-session proof, and commit.
- Explicit overlap, proof-gated retirement, and destructive removal workflows.
- A controller-only consumer for one-use ServiceRadar callback grants.
- Versioned AWX callback credential-type artifacts, a dependency-free canonical
  digest tool, and a Go-compatible conformance vector.
- Pinned lint, syntax, secret-scanning, and systemd/sshd Molecule CI definitions.
- A reusable Windows QEMU Guest Agent role and AWX-visible wrapper.
- A read-only mounted-MSI path, SHA-256, and Authenticode preflight wrapper.
- Fail-closed HTTPS/checksum and mounted VirtIO ISO artifact trust modes.
- An explicit mounted-ISO-only policy for upstream unsigned QGA MSI builds,
  gated by the exact pinned SHA-256; signed installers remain the default.
- QEMU-GA service, binary/version, VirtIO serial, and reboot-policy verification.
- A reusable Linux system-trust role and AWX-visible wrapper for operator-supplied
  public CAs, with per-host batch pre-validation, DER fingerprint pinning,
  active CA/expiry validation, check-mode support, bounded consumer restarts,
  removal, and credential-free verified HTTPS endpoint proofs.
- A controlled public-runner isolation workflow covering ambient credential and
  host-socket absence, private-network denial, anonymous public build egress,
  inner Docker, cross-job state removal, and abnormal lifecycle cleanup.
- A fleet SSH-CA enrollment role and wrappers replicating a verified reference
  layout (locked privilege-free account, user-CA trust, opaque policy
  principals, proof-gated sshd reload) plus a controller-local known_hosts
  fragment collector for serviceradar#4376. Secrets travel only via
  ansible-vault, environment, or per-run extra vars.
- A `linux_snmp_agent` role and `install-linux-snmp-agent.yml` wrapper that
  install and configure a read-only `snmpd` on Debian 12, Ubuntu 22.04/24.04
  and Rocky Linux 9 for ServiceRadar polling: SNMPv3 authPriv by default,
  SNMPv2c only as an explicit opt-in that refuses well-known communities, a
  required poller source list enforced by TCP wrappers, a systemd IP filter
  and an already active firewalld or ufw, configuration validation before
  restart, a local query that proves the credential and the source filter on
  every run, and a removal path.
- A versioned `linux-snmp-agent` AWX credential type that holds the SNMPv3
  user and passphrases and the optional SNMPv2c community as secret inputs
  and injects them into the job environment.
- A `linux_snmp_agent` Molecule scenario on the four pinned systemd fixtures
  covering idempotence, allowed and non-allowed peers, wrong credentials,
  passphrase rotation, the SNMPv2c opt-in, the refusal cases, the firewall
  rules and removal.

### Changed

- Run the quality gate in GitHub Actions for every pull request and push to
  `main`, on secretless GitHub-hosted `ubuntu-24.04` runners with actions
  pinned to full commits. The repository contract checks now validate that
  workflow instead of the retired Forgejo one.
- Run the Molecule job once per scenario (`preflight`, `linux_snmp_agent`) and
  record the platform images of the scenario being run.
- Pin the collections the Molecule Docker driver needs in
  `molecule/preflight/collections.yml`; the retired runner carried them
  preinstalled and nothing in the repository declared them.
- Install the ServiceRadar agent from GitHub releases or an explicit package
  URL, SHA-256, and version, instead of the retired release host. The
  installers start the agent only when its enrollment assets exist.
- Resolve agent release metadata once on the Ansible controller for each batch
  of hosts instead of once on every managed host, so hosts behind one address
  no longer exhaust the anonymous GitHub API limit. Managed hosts need access
  only to the package download URL.
- Preserve verified Proxmox management addresses in the dynamic inventory.
- Make canonical-only AWX callback contract output and its checked-in vector
  byte-identical to the bytes covered by the published SHA-256.
- Pin the Windows role to the AWX 24.6.1-supported `ansible.windows 2.4.0`
  runtime and enforce Authenticode policy explicitly before package execution.

### Fixed

- Accept a stock Rocky Linux 9 host in the SSH user-CA preflight. It rejected
  every unmanaged drop-in containing an `Include`, which includes the
  distribution's own `50-redhat.conf`. Preflight now tolerates exactly the line
  `Include /etc/crypto-policies/back-ends/opensshserver.config` in exactly that
  file, and reads the included back-end, failing closed if it is unreadable,
  not a root-controlled regular file, or contains an `Include`, `Match`,
  `TrustedUserCAKeys`, or `AuthorizedPrincipalsFile` directive. Every other
  nested include and every Match or CA/principal directive is still rejected.
- Reject sshd keywords written with `=` or quotes in the SSH user-CA preflight.
  The rules that refuse `Include`, `Match`, `TrustedUserCAKeys` and
  `AuthorizedPrincipalsFile` in the main configuration and in unmanaged
  drop-ins required whitespace after the keyword, but sshd also accepts
  `Keyword=value`, `Keyword = value` and a quoted keyword. Those forms are now
  rejected like the whitespace form. An effective `TrustedUserCAKeys` path
  containing a space is no longer read as unset.
- Make the Molecule preflight scenario runnable: use the digest-pinned fixture
  images without a local rebuild and refresh the fixture package index.
- Report a rate-limited or otherwise unusable agent release lookup with its
  cause and the pinned package inputs, rather than a dump of response headers.
- Let the agent installers complete in check mode and report the planned
  package action instead of failing on a package file that a dry run never
  downloads.

### Removed

- The Forgejo workflow definitions, which no longer run, and the controlled
  public-runner isolation workflow, script, and runbook that tested the
  retired self-hosted runner.
