# `remote_access_ssh_ca`

This role owns only:

- `/etc/ssh/serviceradar/current/trusted-user-ca-keys.pub`
- `/etc/ssh/serviceradar/current/authorized-principals/`
- `/etc/ssh/sshd_config.d/10-serviceradar-remote-access.conf`

It does not generate certificates, hold a CA private key, create accounts, modify
PAM/sudo/LDAP/password policy, or restart sshd. Use the root wrappers rather than
calling the role directly; they isolate direct and ServiceRadar-integrated input.

See [`docs/remote-access-ssh-ca.md`](../../docs/remote-access-ssh-ca.md) for the
input schema and lifecycle.
