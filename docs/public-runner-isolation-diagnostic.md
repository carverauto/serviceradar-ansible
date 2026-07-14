# Public runner isolation diagnostic

The manual `controlled-public-runner-isolation-diagnostic` workflow is the
acceptance test for the repository-scoped public CI runner. It is not a general
debug workflow and has no `push` or `pull_request` trigger. Run it only from a
reviewed commit while normal public pull-request CI is paused.

Each job uses the exact
`serviceradar-public-ephemeral-ubuntu-24.04-20260701` label. The runner host
creates a new unprivileged LXC guest and a new repository-85 ephemeral runner
identity for that one job. Docker is privileged only inside that disposable
guest. The diagnostic must never be moved to a generic, Kubernetes, or signing
runner.

## What the workflow proves

Before contacting a target, the diagnostic fails closed unless all six
non-secret runner evidence values match the reviewed repository, label,
version, boundary, and disposable guest identity. It then verifies:

- before either checkout, no proxy, askpass, Git trace/config injection,
  credential file/cache, dangerous Git config key, or prior workspace sentinel
  can observe or redirect the checkout credential; the post-checkout gate then
  independently proves checkout removed its temporary authorization config;
- the Kubernetes service-account token, kubeconfig, host runner API token,
  OpenBao/signing/registry environment variables, reusable Docker auth, SSH
  keys, and common cloud credentials are absent;
- the Kubernetes runner Docker socket, containerd/LXC control sockets, and host
  LXC state are absent, while only the guest's inner Docker socket works;
- PID 1 has exactly one UID map and one GID map, each the reviewed
  `0 -> 1000000` range of length `65536`;
- representative Kubernetes, OpenBao, PVE, VM-management, private-LAN,
  database, link-local, and IPv6 ULA connections are denied;
- public DNS, NTP, Forgejo HTTPS, anonymous Docker Registry HTTPS, and the
  exact pinned Ubuntu package snapshot are reachable without a workflow
  credential;
- inner Docker anonymously pulls the same immutable image used by Molecule and
  runs a privileged cgroup probe inside the LXC boundary; and
- fixed filesystem, workspace, process, Docker-volume, and Docker-image
  sentinels from one job are absent in the next job, whose guest identity must
  differ. The workspace tree is searched before checkout so checkout cleanup
  cannot erase the evidence before it is inspected.

The workflow emits only names, immutable digests, endpoint labels/statuses,
runner/guest IDs, and denial result classes. It does not print environment
values, authorization headers, runner tokens, or response bodies. Do not add a
workflow secret, artifact upload, proxy, credential helper, or checkout with
credential persistence to this workflow.

The Forgejo runner process necessarily receives a single-job ephemeral identity
token inside its disposable guest. Forgejo also provides a repository-scoped,
job-lifetime runtime token. On Forgejo 15, a manual `workflow_dispatch` token is
write-capable; only fork pull-request tasks are forced to read-only access. The
workflow's `permissions: contents: read` declaration records least-privilege
intent but is not an enforcement boundary on this Forgejo version. Because
workflow steps run as root inside that guest, neither token is treated as a
secret from that same job. The diagnostic only checks that Forgejo's two
automatic job-token aliases are non-empty and equal; it never prints or persists
their values. Host-side API evidence must
prove the runner identity was repository-85 scoped, ephemeral, accepted only
one job, and was deleted with the guest. This is distinct from the persistent
repository-85 API credential, which must remain on the VM host and is asserted
absent from both the job environment and guest filesystem.

## Preconditions

Before the first dispatch:

1. Merge and synchronize the reviewed GitOps public-runner change.
2. Confirm repository 85 cannot see a generic, Kubernetes, or signing runner.
3. Confirm the dedicated host has its repository-85-only API credential in the
   documented root-only path, the public-runner supervisor is enabled, and no
   quarantine marker exists. Never display the credential.
4. Keep ordinary repository-85 pull-request jobs paused until every case below
   has accepted evidence.
5. Record the reviewed commit SHA being dispatched. A branch name alone is not
   immutable evidence.
6. Capture the VM-host forbidden-destination counter line described below
   before each dispatch. Except for the deliberate host-reset case, capture it
   again after the workflow reaches a terminal state and do not reset the
   firewall or its counters between those observations. The host-reset case
   uses the two explicitly separated counter epochs described below.

## Controlled scenario matrix

Dispatch `.forgejo/workflows/public-runner-diagnostic.yml` from the Forgejo
Actions UI with one of the following `scenario` values. The pool deliberately
has one job of capacity, so run these serially. Every dispatch requires
`expected_commit`; paste the exact reviewed 40-character commit SHA and verify
it matches the selected Forgejo ref. Leave `previous_guest_id` empty except for
the manual `verify-clean` case.

- `success`: no operator action. The diagnostic and `verify-next-guest` jobs
  pass. The second guest ID differs and all sentinels are absent.
- `forced-failure`: no operator action. The first job exits 42 and the workflow
  is red by design. `verify-next-guest` still runs with `always()` and passes in
  a fresh guest.
- `timeout`: no operator action. The first job exceeds its eight-minute
  workflow timeout and the follow-up passes in a fresh guest. If this Forgejo
  version does not schedule an `always()` dependency after timeout, dispatch
  `verify-clean` immediately with the timed-out job's logged guest ID as
  `previous_guest_id`.
- `hold-for-cancel`: wait for `operator_hook_ready=true`, then cancel the
  workflow from the Forgejo UI. Cancellation suppresses the remaining job, so
  dispatch `verify-clean` after Forgejo reports the workflow cancelled and pass
  the held job's logged guest ID as `previous_guest_id`.
- `hold-for-runner-crash`: wait for readiness, then use the host-side crash hook
  below. The supervisor must clean the guest and identity before the follow-up
  passes. If Forgejo does not schedule the follow-up, dispatch `verify-clean`
  with the crashed job's logged guest ID.
- `hold-for-host-restart`: wait for readiness, then use the host-side restart
  hook below. Boot recovery must remove the interrupted job before replacement
  capacity starts. The follow-up or a manual `verify-clean` passes in a
  different guest; the manual case requires the interrupted guest ID.
- `verify-clean`: use after a cancelled or otherwise interrupted workflow. A
  fresh guest has no sentinel, workspace, process, or Docker state and all
  local boundary and network-denial assertions pass. `previous_guest_id` is
  mandatory and the new guest ID must differ.

An expected red `forced-failure`, timeout, or cancelled workflow is evidence
only when the subsequent cleanup verification passes and the host-side checks
below show no residual runner identity or guest state.

## Operator-controlled disruption hooks

Connect only through the reviewed management path:

```sh
ssh -J root@192.168.2.10 serviceradar-operator@10.213.1.6
```

For `hold-for-runner-crash`, read only the non-secret guest ID and kill the
runner process inside that guest. Do not kill the cleanup process or delete
state manually:

```sh
guest=$(sudo jq -er \
  '.guest | select(test("^serviceradar-public-job-[0-9]+-[0-9a-f]{8}$"))' \
  /var/lib/forgejo-public-runner/active-job.json)
sudo lxc-attach --name "${guest}" -- pkill -KILL -x forgejo-runner
unset guest
```

For `hold-for-host-restart`, leave the VM session alone. From an operator shell,
use the PVE control plane to perform a hard reset after the readiness line
appears. Immediately before the reset, capture the exact VM-host counter line
and require its packet count to exceed the pre-dispatch value. This proves the
held guest's probes reached the VM-host drop rule before power was removed.
The exact VM name check prevents resetting an unrelated VMID:

```sh
ssh root@192.168.2.10 \
  'qm config 167 | grep -Fxq "name: forgejo-public-runner-01" && qm reset 167'
```

Reconnect through the same ProxyJump after the VM returns. The enabled
supervisor performs idempotent power-loss recovery from `active-job.json`; do
not remove that file or the LXC guest by hand. A graceful in-guest reboot is
not acceptable evidence for this case. The hard reset starts a new nftables
counter epoch, so never compare a post-boot value with the pre-reset value.
Retain the current boot ID and the successful firewall-service journal for that
boot, then require the exact drop-rule packet count to be nonzero after the
replacement or manual `verify-clean` job. Together, the pre-reset increment and
the nonzero post-boot value prove denial on both sides of the interruption.

For cancellation, use Forgejo's workflow Cancel control. The job intentionally
has no API token with which to cancel itself.

If an operator misses a hold window, the workflow's eight-minute timeout is
the safe terminal outcome. Record it as a timeout case, not as the intended
cancel/crash/restart case, and repeat the intended case.

## Required cleanup and denial evidence

After each workflow reaches a terminal state and before starting the next
scenario, run the reviewed host verifier. It reads the root-only API token
without printing it and requires the repository runner list to be empty:

```sh
sudo /usr/local/libexec/forgejo-public-runner/verify-isolation.sh --api
sudo test ! -e /var/lib/forgejo-public-runner/QUARANTINED
sudo systemctl is-active forgejo-public-runner.service
```

Retain the relevant non-secret lifecycle lines. Before cleanup deletes the
identity, the supervisor emits one `runner identity verified` marker containing
only guest ID, runner ID, `repository_id=85`, `ephemeral=true`, and the exact
public label. Never attach the complete environment, runner UUID, token, URL,
userinfo, filesystem path inventory, or a credential file:

```sh
sudo journalctl --no-pager -u forgejo-public-runner.service \
  --grep='runner identity verified\|cleanup proven\|one-job runner exited\|recovery\|quarantined'
```

Capture the exact VM-host forbidden-destination counter line immediately before
the diagnostic probes and again after the job terminates. Within one boot epoch
the packet count must increase; IPv4 guest probes must report a timeout
consistent with the VM-host `drop` rule. The IPv6 ULA probe may instead report
the expected no-route/drop errno:

```sh
sudo nft -a list chain inet serviceradar_public_runner forward | \
  grep -F 'iifname "lxcbr-public" ip daddr @forbidden_v4 counter'
```

For `hold-for-host-restart`, retain three observations instead: the
pre-dispatch line, the increased line immediately before `qm reset`, and the
nonzero line from the new boot after cleanup verification. Also retain the new
boot ID and firewall-service success without treating counters from different
boots as a monotonic sequence:

```sh
cat /proc/sys/kernel/random/boot_id
sudo systemctl is-active serviceradar-public-runner-firewall.service
sudo journalctl --no-pager -b -u serviceradar-public-runner-firewall.service
```

The LXC probes are intentionally dropped by the VM-host firewall before they
reach PVE, so they cannot be used to claim an increment in a PVE counter. The
PVE owner must instead retain an active structural verification of the separate
upstream boundary without changing or bypassing either firewall:

```sh
ssh root@192.168.2.10 \
  '/usr/local/libexec/forgejo-public-runner-pve/verify-pve-network.sh --active'
```

Accept a case only when:

- the pre-deletion `runner identity verified` journal marker proves repository
  85, ephemeral identity, and only the versioned public label, and its runner
  ID correlates with the cleanup line and Forgejo job audit;
- no identity accepts a second job and no repository-85 runner remains visible
  while idle;
- the old and replacement guest IDs differ;
- the follow-up or manual `verify-clean` job passes;
- the host verifier passes with no quarantine marker; and
- the exact VM-host forbidden-destination counter increases for the controlled
  private probes within each boot epoch (using the pre-reset increment and
  nonzero new-boot evidence for the host-reset case), the separate PVE verifier
  passes, and approved public egress succeeds.

Any ambiguous cleanup, unexpected successful private connection, missing
denial evidence, credential/socket finding, repeated guest identity, or
sentinel survival blocks ordinary public CI. Leave the host quarantined and
follow the GitOps public-runner recovery runbook; deleting the quarantine
marker alone is not recovery.
