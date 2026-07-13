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
- Pinned lint, syntax, secret-scanning, and systemd/sshd Molecule CI definitions.
- A reusable Windows QEMU Guest Agent role and AWX-visible wrapper.
- A read-only mounted-MSI path, SHA-256, and Authenticode preflight wrapper.
- Fail-closed HTTPS/checksum and mounted VirtIO ISO artifact trust modes.
- QEMU-GA service, binary/version, VirtIO serial, and reboot-policy verification.
