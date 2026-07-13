# SSH user-CA enrollment operator guide

## Scope

This content teaches an existing OpenSSH server to trust one or more **public**
user-CA keys for named, existing, non-root accounts. It deliberately does not:

- generate or distribute a CA private key or signed user certificate;
- create accounts, grant sudo, or modify passwords/PAM/LDAP;
- change host keys or unrelated sshd/session policy;
- enroll root, UID 0, login-disabled users, hypervisors, or control-plane hosts;
- configure AWX, ServiceRadar, an edge route, or claim readiness.

The fixed ownership boundary is:

| Path | Purpose |
| --- | --- |
| `/etc/ssh/serviceradar/current/trusted-user-ca-keys.pub` | Public user-CA overlap bundle |
| `/etc/ssh/serviceradar/current/authorized-principals/<account>` | Opaque per-target principals |
| `/etc/ssh/sshd_config.d/10-serviceradar-remote-access.conf` | References to the two paths |
| `/var/lib/serviceradar/remote-access-ssh-ca` | Credential-free transaction state |

Path overrides fail closed. Offboarding removes only the first three paths and
never removes an account or unmanaged policy.

## Supported matrix

| Distribution | Version | Service | Layout |
| --- | --- | --- | --- |
| Ubuntu | 22.04, 24.04 | `ssh.service` | One standard `sshd_config.d/*.conf` include |
| Debian | 12 | `ssh.service` | One standard `sshd_config.d/*.conf` include |
| Rocky Linux | 9 | `sshd.service` | One standard `sshd_config.d/*.conf` include |

Only a single, non-socket-activated systemd service is supported. Preflight
rejects multiple instances, socket activation, symlinked/unsafe parents,
unknown include ordering, ambiguous CA/principal directives, and unsupported
Match policy. Rocky SELinux labels are restored with `restorecon`. FIPS mode
rejects Ed25519 CA keys.

## Public direct-mode input

Direct wrappers use the operator controller's authorization model. Variables
are set per inventory host; do not put a private key or signed machine
credential in any role variable.

```yaml
sr_ra_target_identity:
  operator_target_id: linux-042
sr_ra_ca_keys:
  - id: active-2026
    public_key: "ssh-ed25519 AAAA... public-ca-2026"
    fingerprint: "SHA256:base64FingerprintWithoutPadding"
sr_ra_accounts:
  - name: existing_operator
    principals:
      - srp_v1_6d8b1e49fbe24ad487ce2c5c
sr_ra_transaction:
  id: tx-unique-at-least-eight-characters
  stage_job_id: controller-job-1042
  generation: gen-unique-at-least-eight-characters
  machine_credential_ref: controller-credential-ref:17
```

The account must already exist, have UID greater than zero, and have a usable
shell. Principals are opaque tokens using `srp_v1_` followed by 20-96
high-entropy base64url characters; whitespace,
human-readable account/role labels, and authorized_keys-style options are rejected.
The role verifies every supplied public key with `ssh-keygen -E sha256 -lf -`.

## Direct lifecycle

Use an inventory limit even though direct wrappers accept `target_hosts`.

```text
remote-access-direct-preflight.yml
       |
remote-access-direct-stage.yml       (or overlap/retire/absent stage)
       | rollback timer remains armed
remote-access-direct-verify.yml      (new controller job and SSH connection)
       |
remote-access-direct-commit.yml      (proof comparison under host lock)
```

The verify job must reuse the exact transaction/generation/stage job and opaque
machine-credential **reference**, add a distinct `verification_job_id`, and
connect through OpenSSH. For overlap, retirement, or removal, direct verify and
commit also set `direct_verify_operation`/`direct_commit_operation` and
`direct_verify_state`/`direct_commit_state` to the original staged values.
Commit uses the same desired public policy variables.
If verify or commit does not complete before the 5-60 minute configured bound,
the persistent systemd timer restores the complete prior role-owned snapshot.
A boot-enabled recovery unit also restores an uncommitted generation after a
reboot or systemd restart.

Native check mode is supported for preflight/stage and reports the exact owned
paths and policy digest without writing or reloading. Verification and commit
are intentionally real lifecycle operations, not check-mode simulations.

## Rotation

Rotation is two changes, never a single desired-set replacement:

1. Run the overlap stage with both old and new public keys, then verify/commit.
2. Independently authenticate using a user certificate signed by the new CA.
3. Run the retirement stage with only the new public key, a fresh proof bound to
   the target/new fingerprint/principal-policy version, and a confirmation that
   names the retiring and remaining fingerprints. Verify/commit again.

Direct proof kind is `controller_new_ca_ssh_login`. Integrated proof kind is
`serviceradar_selected_edge_ca_login`; it also binds the selected route and
requires `devices.remote_access.ssh.ca_trust.retire`. The two proof kinds cannot
substitute for each other.

Direct removal requires an explicit confirmation with `action: remove`, the
exact `operator_target_id`, the exact committed `policy_digest`, and
`confirmed: true`. Integrated removal requires
`devices.remote_access.ssh.ca_trust.remove`. Both are staged and guarded.

## ServiceRadar-integrated execution

Do not create surveys or prompt-on-launch fields for integrated templates.
ServiceRadar must create immutable project/template/inventory/credential/host
bindings and an exact non-empty AWX limit. Only root wrappers listed under
`integrated_wrappers` in `catalog/remote-access-ssh-ca.yml` are eligible.

The ephemeral custom credential injects the environment values documented
in `roles/serviceradar_callback/README.md`. The callback role:

- runs only after a controller-local task has materialized one AWX host-bound
  event for every limited target, so ServiceRadar can prove exact host-ID set
  equality without contacting a managed host;
- reads AWX's system-provided `JOB_ID` directly, never from a custom credential
  or playbook variable, and requires the response to echo that exact job;
- uses one controller-local HTTP task with strict TLS, no proxy, no redirects,
  a five-second per-attempt timeout, `no_log`, and at most thirty attempts;
- sends a server-minted idempotency key bound to the exact request so an
  operator can safely retry only a byte-equivalent request after a lost
  response; key reuse with different request bytes must fail closed;
- retries only the same key and request after a sanitized pending response or
  ambiguous lost response, without adding a second logical read budget;
- requires the server and reviewed EE egress boundary to cap the response at
  256 KiB, then performs a second post-receipt size check;
- compares the response to the injected manifest, SCM revision, content digest,
  operation, state, permissions, policy approval, and immutable binding;
- requires exact set equality between limited play hosts and unique immutable
  target tuples;
- attaches only a target's public bundle/principals and non-secret references to
  that exact in-memory inventory host.

The bearer and fleet response stay transient in the reviewed execution
environment. Disable fact caching, job artifacts, support capture, relaunch/copy,
and backup of the ephemeral credential. Terminal or ambiguous jobs must detach
the AWX credential and revoke its one-use callback grant.

## Failure handling

Candidate and live `sshd -t`, account-aware `sshd -T -C`, reload, and immediate
stage failures execute rollback while the original stage connection remains
open. The rollback helper restores absence/content/owner/group/mode plus ACL and
SELinux xattrs preserved by the supported GNU `cp -a --preserve=all` baseline,
revalidates sshd, and reloads the prior service.

If restoration or reload cannot be proven, the role emits
`critical_manual_recovery`. ServiceRadar's separately implemented hardened AWX
targeting must durably quarantine that canonical device and exclude it from
later waves. This public repository does not mutate ServiceRadar to create that
quarantine.

## Immutable import checklist

1. Review a pull request and all CI provenance.
2. Record the full SCM commit, the CI deterministic content SHA256, and collection
   artifact SHA256 emitted by the pinned quality job.
3. Build a reviewed AWX execution environment from the pinned dependencies.
4. Bind an exact project, template, inventory, custom credential type, machine
   credential reference, wrapper, and content revision.
5. Disable prompt-on-launch inventory, credential, SCM, limit, and extra-vars
   substitutions for integrated templates.
6. Start with read-only preflight, then a single standard-risk canary.

Never import a moving branch into a production template.

Public pull-request CI runs only on the versioned, disposable, secretless
`serviceradar-public-ephemeral-ubuntu-24.04-20260701` runner pool. Molecule uses
a repository-scoped one-job runner inside a disposable VM, then an LXC job with
its own inner Docker daemon. The runner has no Kubernetes service-account token,
OpenBao access, signing material, private-LAN egress, persistent workspace, or
cross-job Docker state. Workflows never mount a trusted host or Kubernetes
runner Docker socket. Organization runner policy must keep signing and other
trusted labels unavailable to this public repository even if a pull request
modifies workflow YAML.
