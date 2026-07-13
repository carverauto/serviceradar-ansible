# ServiceRadar ephemeral AWX callback credential type

ServiceRadar-integrated remote-access jobs require one reviewed AWX custom
credential type. ServiceRadar uses that type to create a different short-lived
credential instance for each child execution and deletes the instance at the
end of its lifecycle. Operators must not create a reusable credential instance
containing a callback grant.

The versioned AWX 24.6.1-compatible configuration is published as:

- [`inputs.json`](../awx/credential-types/serviceradar-ephemeral-callback/v1/inputs.json)
- [`injectors.json`](../awx/credential-types/serviceradar-ephemeral-callback/v1/injectors.json)

JSON is used because AWX accepts both JSON and YAML in its Input Configuration
and Injector Configuration fields, while the standard-library-only validation
tool can parse JSON without adding a YAML dependency. See the version-pinned
[AWX custom credential type documentation](https://docs.ansible.com/projects/awx/en/24.6.1/userguide/credential_types.html)
for the controller's configuration-field format.

## Create the type in AWX

1. Sign in to AWX as a superuser and open **Administration -> Credential
   Types -> Add**.
2. Set the name to `ServiceRadar Ephemeral Callback v1`. A useful description
   is `ServiceRadar one-use automation callback environment`.
3. Paste the complete contents of `inputs.json` into **Input Configuration**.
4. Paste the complete contents of `injectors.json` into **Injector
   Configuration** and save.
5. Record the positive integer credential type ID assigned by AWX. It appears
   in the detail URL and in `GET /api/v2/credential_types/<id>/`.

For API-driven creation, send the same two parsed JSON objects as `inputs` and
`injectors` in a `POST /api/v2/credential_types/` request with:

```json
{
  "name": "ServiceRadar Ephemeral Callback v1",
  "description": "ServiceRadar one-use automation callback environment",
  "kind": "cloud"
}
```

Merge the two artifact objects into that request under their matching keys. Do
not place an AWX token in a file, shell history, example, or source-control
variable. Authentication to AWX is an operator deployment concern and is not
part of these public artifacts.

The type must remain custom (`managed: false`) and `kind: cloud`. Do not add
fields, required entries, environment mappings, `extra_vars`, or file
injectors. ServiceRadar's selected edge agent fetches the AWX type before use,
normalizes it to the contract below, and rejects any digest drift.

## Exact security boundary

There are exactly ten required string inputs and ten environment mappings.
Only these inputs are secret in AWX:

- `callback_grant`
- `callback_idempotency_key`

The callback URL, allowed origin, immutable digests, revision, phase,
operation, and state are non-secret binding data. They are still server-minted
and must never be accepted from a survey, inventory, ordinary extra vars, or a
user-authored playbook variable.

`JOB_ID` is deliberately absent from both artifacts. AWX itself sets `JOB_ID`
for the running job. The callback role reads that system-provided value so a
copied or relaunched job cannot claim the ID of the original accepted job.
Adding `JOB_ID` to the credential type changes the trust boundary and is
rejected by repository tests and ServiceRadar's runtime validation.

The files contain only field definitions and Jinja placeholders. They never
contain a callback bearer, API key, private key, password, or credential value.

## Produce the ServiceRadar contract digest

After AWX assigns the type ID, run the dependency-free validator from this
repository. For example, ID `91` is the public conformance vector, not a value
to copy from another installation:

```sh
python3 scripts/awx_callback_credential_contract.py 91
```

The default output is two lines: exact canonical contract JSON followed by its
lowercase SHA-256. Pipe either value separately when needed:

```sh
python3 scripts/awx_callback_credential_contract.py 91 --output canonical > callback-contract.json
python3 scripts/awx_callback_credential_contract.py 91 --output sha256
```

For the ID-91 vector, the digest is:

```text
cd42bea50b45fcb010c1cc1e89243b8d9d0230bc2fe0b6bb9d49839d17f5a263
```

The canonical bytes are UTF-8 minified JSON with recursively sorted object
keys. Field objects and required IDs are sorted by input ID. The top-level
contract is:

- schema `serviceradar.awx_callback_credential_type`
- version `1`
- the AWX-assigned positive signed-32-bit credential type ID
- kind `cloud`
- normalized `id`, `type`, and `secret` field properties
- the exact required IDs and environment templates

The checked-in
[`conformance-id-91.canonical.json`](../awx/credential-types/serviceradar-ephemeral-callback/v1/conformance-id-91.canonical.json)
and
[`conformance-id-91.sha256`](../awx/credential-types/serviceradar-ephemeral-callback/v1/conformance-id-91.sha256)
must remain byte-compatible with ServiceRadar's Go runtime vector.

Record the actual AWX type ID and generated digest in the reviewed
ServiceRadar AWX template binding. Never substitute the ID-91 example digest
unless AWX actually assigned that ID and the saved type matches these
artifacts. Runtime drift is a launch denial; create and review a new versioned
artifact set rather than editing v1 in place.
