# `linux_trusted_ca`

Installs or removes explicitly named public CA certificates in the Linux system
trust store. Every installed certificate must be marked `CA:TRUE`, remain valid
for the configured minimum window, and match a required SHA-256 fingerprint of
its canonical DER encoding. The role validates every present certificate before
it makes the first trust-store change, including during Ansible check mode.
Certificate validation cannot be disabled.

This role is useful when a ServiceRadar edge agent must connect to a private
HTTPS API such as Proxmox. It does not fetch certificates from the endpoint it
is about to trust, transport private keys, or accept credentials. Obtain and
verify each public CA through an independent administrative channel.

Use the root `install-linux-trusted-ca.yml` wrapper. Configure immutable public
CA inputs in a reviewed AWX job template and let ServiceRadar select the exact
inventory/limit. Do not enable prompt-on-launch for these variables.

Example non-secret variables:

```yaml
serviceradar_linux_trusted_ca_certificates:
  - name: site01-proxmox-root
    state: present
    certificate: |-
      -----BEGIN CERTIFICATE-----
      <public CA PEM supplied by the operator>
      -----END CERTIFICATE-----
    sha256_fingerprint: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
serviceradar_linux_trusted_ca_restart_services:
  - serviceradar-agent
serviceradar_linux_trusted_ca_verify_urls:
  - https://192.0.2.10:8006/api2/json/version
```

The URL proof runs only after the trust-store update and requested consumer
restarts. It always uses the system trust store, disables proxy use, and keeps
TLS verification enabled. It does not use ambient `.netrc` credentials or
follow redirects.
