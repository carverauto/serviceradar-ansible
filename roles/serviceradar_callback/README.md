# `serviceradar_callback`

This role is a narrow consumer for `remote_access.ssh_ca.bundle.read`. It runs
once on the reviewed AWX execution environment. A dedicated ephemeral AWX custom
credential injects these environment variables:

- `SERVICERADAR_CALLBACK_URL`
- `SERVICERADAR_CALLBACK_GRANT`
- `SERVICERADAR_CALLBACK_IDEMPOTENCY_KEY`
- `SERVICERADAR_CALLBACK_ALLOWED_ORIGIN`
- `SERVICERADAR_CALLBACK_MANIFEST_SHA256`
- `SERVICERADAR_SCM_REVISION`
- `SERVICERADAR_CONTENT_SHA256`
- `SERVICERADAR_CALLBACK_PHASE`
- `SERVICERADAR_CALLBACK_OPERATION`
- `SERVICERADAR_CALLBACK_STATE`

AWX itself supplies `JOB_ID` for the running job. It is not an input on the
custom credential, in inventory, in a survey, or in extra vars. The role reads
that system environment value directly and sends it as a JSON integer so
ServiceRadar can bind the callback to the exact accepted AWX runtime job.

Do not place these values in inventory, surveys, ordinary extra vars, logs,
artifacts, fact caches, or support bundles. The role never sends the callback
response or bearer to a managed host.

The idempotency key is minted with the callback grant and bound to the exact
request body. It permits only a byte-equivalent replay after an ambiguous lost
response; it is not a second bearer and cannot authorize another action or
request body. ServiceRadar must reject key reuse with different request bytes.
The one controller-local HTTP task makes at most thirty bounded attempts, each
with a five-second transport timeout, using that same key and body. This gives
ServiceRadar time to prove the accepted AWX job and exact host scope after a
sanitized pending response, while a lost response can recover without adding a
second logical read.

The integrated entrypoint first executes one `delegate_to: localhost` assertion
for every AWX-limited inventory host. That contacts no managed target, but it
materializes a host-ID-bound AWX event for each exact host before this role runs.
ServiceRadar can therefore compare the accepted job's complete AWX host-summary
set with its immutable execution targets before activating the grant.
