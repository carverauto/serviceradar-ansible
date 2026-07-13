# `windows_qemu_guest_agent`

Installs or upgrades the upstream QEMU Guest Agent MSI on a 64-bit Windows
guest, configures `QEMU-GA` as automatic/running, and verifies the service's
actual binary and version.

The role accepts exactly two source modes:

- `https`: an HTTPS `.msi` URL without embedded credentials, query string, or
  fragment, plus a mandatory exact SHA-256.
- `mounted_iso`: an absolute `.msi` path that the guest reports as CD-ROM
  media. A SHA-256 is optional but recommended.

Authenticode validation is always enabled. The role never downloads `latest`,
disables TLS validation, stores credentials, configures WinRM/OpenSSH, installs
the VirtIO serial driver, or changes Proxmox VM hardware.

Use the root
[`install-qemu-guest-agent-windows.yml`](../../install-qemu-guest-agent-windows.yml)
wrapper and read the complete
[`docs/windows-qemu-guest-agent.md`](../../docs/windows-qemu-guest-agent.md)
operator guide before launch.
