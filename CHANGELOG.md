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

### Changed

- Make canonical-only AWX callback contract output and its checked-in vector
  byte-identical to the bytes covered by the published SHA-256.
- Pin the Windows role to the AWX 24.6.1-supported `ansible.windows 2.4.0`
  runtime and enforce Authenticode policy explicitly before package execution.
