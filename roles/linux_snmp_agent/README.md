# `linux_snmp_agent`

Installs and configures the distribution `snmpd` on a Linux VM or container so
that a ServiceRadar agent can poll it. The agent is read-only, answers only the
poller sources you list, and takes its SNMP secret from an AWX credential.

Use the root `install-linux-snmp-agent.yml` wrapper.

Supported targets are Debian 12, Ubuntu 22.04/24.04 and Rocky Linux 9 with
systemd, as VMs or as LXC containers. Other Enterprise Linux 9 rebuilds are
accepted but only Rocky Linux 9 is tested.

## Where the SNMP secret lives

Nothing secret belongs in this repository, an inventory, a survey, or a job
template's extra variables. The secret is an AWX credential:

1. An AWX administrator creates the custom credential type once from
   [`inputs.json`](../../awx/credential-types/linux-snmp-agent/v1/inputs.json)
   and
   [`injectors.json`](../../awx/credential-types/linux-snmp-agent/v1/injectors.json).
2. An operator creates a credential of that type and types the SNMPv3 user
   name, authentication passphrase and privacy passphrase into it. AWX
   encrypts them at rest and never shows them again.
3. The credential is attached to the job template. At launch AWX injects the
   values into the job's environment as `SERVICERADAR_SNMP_V3_USER`,
   `SERVICERADAR_SNMP_V3_AUTH_PASSPHRASE`, `SERVICERADAR_SNMP_V3_PRIV_PASSPHRASE`
   and `SERVICERADAR_SNMP_V2C_COMMUNITY`, and shows them masked in the job
   details.
4. The role's defaults read those variables on the execution environment. No
   task prints them: every task that handles one runs with `no_log: true`,
   file changes are never shown as a diff, and the role's own queries read
   the credential from a root-only temporary file instead of a command line.

On the managed host the secret ends up in exactly one place:

| Mode | At rest on the host |
| --- | --- |
| SNMPv3 | Keys derived from the passphrases and bound to that agent's engine ID, in the agent's persistent store (`/var/lib/snmp/snmpd.conf`, or `/var/lib/net-snmp/snmpd.conf` on Enterprise Linux). The passphrases themselves are not stored; the role fails if a plaintext `createUser` line is left behind. |
| SNMPv2c | The community string, in `/etc/snmp/snmpd.conf` (root, mode `0600`). snmpd offers no hashed form. |

### ServiceRadar keeps its own copy

This role configures the host side only. ServiceRadar polls with the
credentials in its own credential store, which is separate from AWX. Enter the
same user name, passphrases, authentication protocol (`SHA-256` by default)
and privacy protocol (`AES`) in ServiceRadar's credential settings. Neither
system reads the other's store, so a value changed in one must be changed in
the other.

### Creating the credential in AWX

1. **Administration > Credential Types > Add.** Name it, for example,
   `ServiceRadar SNMP agent`. Paste `inputs.json` into *Input configuration*
   and `injectors.json` into *Injector configuration* unchanged.
2. **Resources > Credentials > Add.** Choose that credential type and fill in
   the three SNMPv3 fields. Leave the community empty unless you run the
   SNMPv2c mode.
3. **Resources > Templates > Add job template.** Project: this repository at a
   reviewed revision. Playbook: `install-linux-snmp-agent.yml`. Credentials:
   the machine credential for the hosts, plus the SNMP credential from step 2.
   Set the non-secret variables below in the template's variables, keep
   *Prompt on launch* off for them, and use the job limit to choose hosts.

Use one credential per group of hosts that should share an SNMP user. A job
template accepts only one credential of a given custom type.

## Inputs

`linux_snmp_agent_poller_sources` is the only required variable.

| Variable | Default | Purpose |
| --- | --- | --- |
| `linux_snmp_agent_poller_sources` | required | IPv4 addresses or CIDRs of the ServiceRadar agents that poll the host. At most 64 entries, each `/8` or longer. |
| `linux_snmp_agent_state` | `present` | `absent` removes what the role manages. |
| `linux_snmp_agent_mode` | `v3` | `v2c` is an explicit opt-in. |
| `linux_snmp_agent_v3_auth_protocol` | `SHA-256` | `SHA-256`, `SHA-384` or `SHA-512`. Privacy is always `AES` (AES-128). |
| `linux_snmp_agent_bind_address` | `0.0.0.0` | IPv4 address to listen on. `127.0.0.1` is always included. |
| `linux_snmp_agent_port` | `161` | UDP port. |
| `linux_snmp_agent_view_oids` | system, interfaces, ifMIB, host resources, UCD | Subtrees in the read-only view. The system group is always included. |
| `linux_snmp_agent_view_extra_oids` | `[]` | Further subtrees to add to the view. |
| `linux_snmp_agent_view_excluded_oids` | `hrSWRunParameters` | Subtrees removed from the view. Process command lines are hidden by default. |
| `linux_snmp_agent_sys_location` | empty | Optional `sysLocation`. |
| `linux_snmp_agent_sys_contact` | empty | Optional `sysContact`. |
| `linux_snmp_agent_include_dropin_dir` | `false` | Also read `/etc/snmp/snmpd.conf.d/*.conf`. |
| `linux_snmp_agent_systemd_ip_filter` | `true` | Enforce the sources with a systemd IP filter on `snmpd.service`. |
| `linux_snmp_agent_manage_firewall` | `true` | Add rules to firewalld or ufw when one is already active. |
| `linux_snmp_agent_firewalld_zone` | empty | firewalld zone for the rules; empty is the default zone. |
| `linux_snmp_agent_remove_package` | `false` | With `absent`, also remove the agent package and its persistent store. |

The four credential variables (`linux_snmp_agent_v3_user`,
`linux_snmp_agent_v3_auth_passphrase`, `linux_snmp_agent_v3_priv_passphrase`,
`linux_snmp_agent_v2c_community`) come from the AWX credential. Do not set
them anywhere else.

Example job-template variables. The addresses are documentation examples:

```yaml
linux_snmp_agent_poller_sources:
  - 192.0.2.10
  - 198.51.100.0/28
linux_snmp_agent_sys_location: Rack 01, SITE01
linux_snmp_agent_sys_contact: noc@example.com
```

Credential rules: the user name is 1-32 characters of letters, digits, `_`,
`.`, `-`, starting with a letter. Each passphrase is 12-64 characters, and the
community 16-64, of letters, digits and `. _ ~ ! @ % ^ * + = : , / -`. The two
passphrases must differ. A missing or invalid value fails the run before the
host is changed, with a message that names the rule and never the value.

## How the poller sources are enforced

The role refuses an empty source list, a source broader than `/8`, and
anything that is not a unicast IPv4 address or a CIDR without host bits.

snmpd itself can restrict SNMPv2c by source, and the role writes one rule per
source. For SNMPv3, net-snmp has no per-user source list, so the role applies
every layer the host offers:

| Layer | Where it applies |
| --- | --- |
| TCP wrappers (`/etc/hosts.allow`, `/etc/hosts.deny`) | Debian 12 and Ubuntu, whose snmpd is built with it. Works in unprivileged containers. |
| systemd IP filter on `snmpd.service` | Every platform. systemd ignores it without an error where the kernel does not let it load cgroup BPF programs, which is the usual case in an unprivileged container. |
| firewalld or ufw rules | Only when that firewall is already active. The role never installs or enables one. |

Because a layer can be configured and still not enforce anything, the role
tests the result on every run. It queries the agent with the correct
credential from `127.0.0.2`, a loopback address that is never in the allow
list. If that query is answered and no managed firewall is active, the role
stops and disables snmpd and fails.

On Rocky Linux 9 in an unprivileged container, snmpd has no TCP wrappers and
the systemd filter is usually not enforced. The role then succeeds only if
firewalld is active in the container; otherwise it fails closed as described.

The role also queries the agent with the community `public` and fails, after
stopping the agent, if that is answered.

## SNMPv3 user and passphrase rotation

snmpd creates a user from a `createUser` line that it reads once at startup,
converts into keys, and deletes. The role therefore does not write that line
on every run. It asks the running agent whether it accepts the supplied
credential and replaces the user only when it does not. A second run with the
same credential changes nothing.

To rotate a passphrase:

1. Edit the AWX credential and enter the new passphrases.
2. Run the job template. On each host the agent no longer accepts the
   credential, so the role stops snmpd, queues the user again, starts snmpd,
   and verifies the new credential. The old passphrases stop working.
3. Update the credential in ServiceRadar.

Polling of a host fails between steps 2 and 3, so do them in one change
window. Changing the user name works the same way; the previous user loses
access immediately, and its unused keys stay in the persistent store until
the role is run with `linux_snmp_agent_state: absent` for that user name or
with `linux_snmp_agent_remove_package: true`.

## SNMPv2c

SNMPv2c sends the community in clear text. It is available only by setting
`linux_snmp_agent_mode: v2c` and filling in the credential's community field.
There is no default community. `public`, `private` and other well-known values
are refused in any letter case. Access is read-only, SNMPv1 is not enabled,
and each rule names one poller source.

## Drop-in directory

With `linux_snmp_agent_include_dropin_dir: true` the agent also reads
`/etc/snmp/snmpd.conf.d/*.conf`. Before rendering its configuration the role
reads those files and fails if one contains a directive other than `disk`,
`extend`, `extendfix`, `file`, `ignoredisk`, `includeAllDisks`, `interface`,
`load`, `pass`, `pass_persist`, `proc`, `procfix`, `realStorageUnits`,
`skipNFSInHostResources`, `storageUseNFS` or `swap`. A drop-in therefore
cannot grant access, add a listener, or include another file.

## What the role changes

- Installs `snmpd` and `snmp` (Debian, Ubuntu) or `net-snmp` and
  `net-snmp-utils` (Enterprise Linux). The client tools are needed for the
  verification queries.
- Replaces `/etc/snmp/snmpd.conf`. The file found on the first run is kept as
  `/etc/snmp/snmpd.conf.pre-serviceradar` (root, `0600`). The new file is
  parsed by snmpd before it is installed, and a file with an error is not
  installed. snmpd is restarted only when a managed file changed.
- Adds a marked block to `/etc/hosts.allow` and `/etc/hosts.deny` where snmpd
  supports TCP wrappers.
- Adds `/etc/systemd/system/snmpd.service.d/50-serviceradar-source-filter.conf`.
- Adds one firewalld rich rule or ufw rule per source when that firewall is
  active, and removes the rule of a source that was taken off the list.
- Records the firewall rules it added in
  `/etc/snmp/serviceradar-linux-snmp-agent.json`.
- Enables and starts `snmpd`.

The agent always listens on `127.0.0.1` so that the role can verify it.

## Removal

`linux_snmp_agent_state: absent` stops and disables snmpd, removes the
firewall rules, the TCP wrappers blocks, the systemd drop-in and the role's
record, removes the SNMPv3 user named by the attached credential from the
persistent store, and puts back the configuration kept from before the first
run. With `linux_snmp_agent_remove_package: true` it also removes the agent
package and deletes the persistent store. The client tools stay installed.
`linux_snmp_agent_poller_sources` must still be defined; an empty list is
accepted for removal.

## Check mode

`--check` reports configuration drift on a host where snmpd is installed. It
does not query the agent or change the SNMPv3 user. On a host without snmpd
the dry run ends for that host after the package step.

## Limitations

- IPv4 only, for both the listener and the poller sources.
- One SNMPv3 user or one community at a time.
- Rules added to firewalld or ufw by hand for the agent port are left alone,
  so a broader manual rule stays in effect.
- The firewall layer is trusted when the firewall is active and the role's
  rules were accepted; the role's own negative query runs over loopback and
  does not pass through the firewall.
