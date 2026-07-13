# Windows QEMU Guest Agent enrollment

`install-qemu-guest-agent-windows.yml` installs or upgrades the upstream QEMU
Guest Agent MSI in an existing 64-bit Windows guest. It is reusable outside
ServiceRadar: the only ServiceRadar-specific behavior is the recommendation to
scope launches through the AWX job-template limit.

The role deliberately does not manage Proxmox credentials or VM hardware. QGA
is an in-guest service; Proxmox must expose the corresponding VirtIO serial
channel before the role runs. The upstream QGA documentation describes that
channel as `org.qemu.guest_agent.0`:
<https://virtio-win.github.io/Knowledge-Base/Qemu-ga-win.html>.

## Bootstrap prerequisites

Complete these in order:

1. Establish an independent Ansible management path to Windows. QGA cannot bootstrap WinRM or OpenSSH because it is
   not installed yet.
2. In Proxmox, enable **QEMU Guest Agent** for the exact VM (`agent: 1`; the
   equivalent CLI is `qm set <vmid> --agent enabled=1`). Restart the guest if
   Proxmox cannot add the channel live.
3. Attach a pinned VirtIO-Win ISO when using `mounted_iso` or when the guest
   lacks its VirtIO serial driver.
4. In Windows Device Manager, install the `vioserial` driver from that pinned
   media and confirm the VirtIO serial controller is healthy. Reboot Windows if
   requested.
5. Run the playbook with a pinned artifact input and an administrative Windows
   machine credential.
6. After the play succeeds, verify the host-to-guest channel from Proxmox with
   `qm agent <vmid> ping` or the equivalent authenticated PVE API call.

The role checks the Windows PnP device, MSI trust, service configuration,
binary existence, and binary version. A running Windows service is necessary
but does not by itself prove that a specific Proxmox VM record owns the other
end of the channel; step 6 is the end-to-end proof.

## Controller dependency

The collection declares `ansible.windows >=2.4.0,<3.0.0`; CI pins version
`2.4.0` in `requirements.yml`. Install the reviewed dependency before running
source-tree playbooks:

```sh
ansible-galaxy collection install -r requirements.yml -p .collections
```

`ansible.windows` is not included in `ansible-core`. The role reads
Authenticode status with PowerShell and refuses non-compliant artifacts before
calling `win_package`; `win_package` independently rechecks the pinned SHA-256.
This avoids pairing AWX 24.6.1's Ansible Core 2.15 runtime with an unsupported
3.x collection while preserving the same fail-closed trust boundary.

For AWX, build `execution-environment.yml` and register the resulting immutable
image digest. It starts from the pinned linux/amd64 AWX EE 24.6.1 digest,
installs the exact collection lock, and fails its image build unless
`ansible.windows 2.4.0` is present:

```sh
ansible-builder build \
  --file execution-environment.yml \
  --tag registry.example.net/automation/serviceradar-awx-ee:24.6.1-windows-2.4.0
```

Do not assume AWX's bundled default EE has a recent enough `ansible.windows`.
Pin the custom EE on the job template and verify its image digest before a
mutating launch.

## Secure artifact sources

### Pinned HTTPS MSI

HTTPS mode requires a literal `.msi` URL and an exact SHA-256. URLs containing
userinfo, a query string, or a fragment are refused so credentials and
short-lived download grants cannot leak into inventory, logs, or AWX relaunch
data. TLS certificate validation cannot be disabled. Authenticode validation is
required for HTTPS sources.

```yaml
windows_qemu_guest_agent_source: https
windows_qemu_guest_agent_msi_url: >-
  https://artifacts.example.net/virtio-win/0.1.271/qemu-ga-x86_64.msi
windows_qemu_guest_agent_msi_checksum: REPLACE_WITH_64_HEX_SHA256
windows_qemu_guest_agent_expected_version: "108.0.2.0"  # optional exact check
```

The HTTPS download is removed in an `always` block, including when MSI
installation fails. The checksum is checked during both download and package
execution.

### Mounted VirtIO ISO

Mounted-media mode requires an absolute path on a drive that Windows reports as
CD-ROM (`Win32_LogicalDisk.DriveType == 5`). This prevents a nominal
`mounted_iso` launch from silently using a mutable local disk. The mandatory
SHA-256 adds an exact-media assertion after the read-only discovery step.

```yaml
windows_qemu_guest_agent_source: mounted_iso
windows_qemu_guest_agent_msi_path: 'D:\guest-agent\qemu-ga-x86_64.msi'
windows_qemu_guest_agent_msi_checksum: REPLACE_WITH_64_HEX_SHA256
windows_qemu_guest_agent_signature_policy: require_valid
```

Some upstream VirtIO-Win QGA MSI builds report `NotSigned`. After the operator
has independently reviewed and pinned the exact ISO/MSI hashes, that specific
mounted-media case may use:

```yaml
windows_qemu_guest_agent_signature_policy: allow_unsigned_pinned_iso
```

This exception is rejected for HTTPS sources and still requires the exact MSI
SHA-256. It does not accept `UnknownError`, `HashMismatch`, `NotTrusted`, or any
other invalid Authenticode status.

VirtIO media normally contains both `qemu-ga-i386.msi` and
`qemu-ga-x86_64.msi`. This role supports 64-bit Windows and requires the x64
package selected by the operator; it never guesses among attached media.

## Variables

| Variable | Default | Contract |
| --- | --- | --- |
| `target_hosts` | `all` | Wrapper host pattern. In AWX, keep this default and use the job-template limit. |
| `windows_qemu_guest_agent_source` | `mounted_iso` | `mounted_iso` or `https`. |
| `windows_qemu_guest_agent_msi_url` | empty | HTTPS `.msi` URL; required only in HTTPS mode. |
| `windows_qemu_guest_agent_msi_path` | empty | Absolute MSI path on mounted CD-ROM; required only in mounted-media mode. |
| `windows_qemu_guest_agent_msi_checksum` | empty | Mandatory 64-hex SHA-256 for both HTTPS and mounted media. Run preflight to discover it before installation. |
| `windows_qemu_guest_agent_signature_policy` | `require_valid` | Require `Valid` Authenticode, or explicitly allow `NotSigned` only for a checksum-pinned mounted ISO. |
| `windows_qemu_guest_agent_expected_version` | empty | Optional exact file or product version assertion. The role always requires a non-empty installed version. |
| `windows_qemu_guest_agent_reboot_policy` | `never` | `never`, `if_required`, or `on_change`. |
| `windows_qemu_guest_agent_reboot_timeout` | `900` | Maximum Windows reboot wait in seconds. |
| `windows_qemu_guest_agent_post_reboot_delay` | `15` | Settle time after Windows responds. |
| `windows_qemu_guest_agent_require_virtio_serial` | `true` | Require a healthy VirtIO serial PnP device. Set `false` only for an intentional package-staging run that makes no readiness claim. |
| `windows_qemu_guest_agent_use_proxy` | `true` | Honor the managed user's Windows proxy configuration for HTTPS downloads. |

`reboot_policy=never` fails after a successful install if MSI return code 3010
reports a required reboot. It never hides a partially completed state; reboot
the guest in a maintenance window before rerunning verification. To have the
same installation job perform that reboot, select `if_required` before the
first mutating launch. `on_change` reboots after an install or upgrade even
when the MSI does not request it. An already-converged host is never rebooted
by any policy.

## WinRM inventory

Prefer WinRM over HTTPS with a certificate trusted by the AWX execution
environment. Keep the username/password or certificate in an AWX machine
credential, not in inventory or extra vars.

```yaml
all:
  hosts:
    windows-vm-01:
      ansible_host: 192.0.2.25
      ansible_connection: winrm
      ansible_port: 5986
      ansible_winrm_scheme: https
      ansible_winrm_transport: ntlm
      ansible_winrm_server_cert_validation: validate
```

Kerberos is preferable in an AD environment. NTLM and Kerberos provide WinRM
message encryption even when an operator is temporarily bootstrapping over
port 5985, but production inventory should move to validated TLS rather than
setting `ansible_winrm_server_cert_validation: ignore`.

## Windows OpenSSH inventory

Ansible can also manage Windows over an already-configured OpenSSH Server:

```yaml
all:
  hosts:
    windows-vm-01:
      ansible_host: 192.0.2.25
      ansible_connection: ssh
      ansible_shell_type: powershell
```

The OpenSSH service, firewall rule, administrator key, and PowerShell default
shell must exist before launch. This role does not create that access path.

## AWX launch

Before the mutating launch, run `qemu-guest-agent-windows-preflight.yml` against
the same exact AWX limit and machine credential. It is read-only and emits only
the discovered CD-ROM MSI path, SHA-256, and Authenticode status. The expected
digest is mandatory. The signature policy defaults to `require_valid`; use the
same explicit pinned-ISO exception only after reviewing an upstream unsigned
build:

```yaml
windows_qemu_guest_agent_preflight_expected_checksum: REPLACE_WITH_64_HEX_SHA256
windows_qemu_guest_agent_preflight_signature_policy: require_valid
```

1. Pin the AWX project to a reviewed commit/content digest of this repository.
2. Select the ServiceRadar inventory and an administrative Windows machine
   credential. Do not put its secret fields in extra vars.
3. Select `install-qemu-guest-agent-windows.yml`.
4. Set **Limit** to the exact Windows device. Do not use `target_hosts` as a
   substitute for a reviewed AWX limit.
5. Supply one source-mode variable set as inventory variables or reviewed
   prompt-on-launch extra vars.
6. Choose an explicit reboot policy appropriate for the maintenance window.
7. After success, require the PVE-side `guest-ping` proof before ServiceRadar
   marks the Proxmox console/inventory integration ready.

For the chicken-and-egg case where QGA, WinRM, and OpenSSH are all absent, use
the Proxmox graphical console or an existing RDP session to bootstrap WinRM or
OpenSSH first. The QGA channel is not an interactive Ansible transport and
cannot safely stand in for a Windows machine credential.

## Idempotence and upgrade behavior

`ansible.windows.win_package` reads the MSI product identity. Upstream QEMU
uses a stable MSI `UpgradeCode` with major-upgrade semantics, so an older build
is upgraded and a newer installed build is not silently downgraded. A second
run with the same package reports no package change, does not reboot, and only
reasserts/validates service readiness.

The upstream MSI defines service name `QEMU-GA`, display name `QEMU Guest
Agent`, automatic start, and LocalSystem. The role refuses service-name
overrides because accepting another service would weaken verification.
