#!/usr/bin/env bash
set -euo pipefail

readonly approved_repository=carverauto/serviceradar-ansible
readonly approved_repository_id=85
readonly approved_label=serviceradar-public-ephemeral-ubuntu-24.04-20260701
readonly approved_runner_version=12.8.0
readonly approved_boundary=public-ephemeral-lxc-v1
readonly approved_forgejo_url=https://code.carverauto.dev
readonly diagnostic_image='docker.io/geerlingguy/docker-ubuntu2204-ansible@sha256:114c729fe6540653b432bb8102bc760eb83a9569f95206f077ad74cb7e7361ee'
readonly diagnostic_image_digest=${diagnostic_image##*@}
readonly package_probe_url='https://snapshot.ubuntu.com/ubuntu/20260714T000000Z/dists/noble/InRelease'
readonly sentinel_name=serviceradar-public-runner-diagnostic-sentinel
readonly workspace_root=/run/forgejo-public-runner/workspace
readonly workspace_sentinel=serviceradar-public-runner-diagnostic-workspace-sentinel

fail() {
  echo "public runner diagnostic failed: $*" >&2
  exit 1
}

assert_exact_boundary() {
  [[ ${GITHUB_REPOSITORY:-} == "${approved_repository}" ]] || fail "repository identity differs"
  [[ ${SERVICERADAR_RUNNER_BOUNDARY:-} == "${approved_boundary}" ]] || fail "runner boundary differs"
  [[ ${SERVICERADAR_RUNNER_REPOSITORY_ID:-} == "${approved_repository_id}" ]] || fail "runner repository ID differs"
  [[ ${SERVICERADAR_RUNNER_REPOSITORY:-} == "${approved_repository}" ]] || fail "runner repository differs"
  [[ ${SERVICERADAR_RUNNER_LABEL:-} == "${approved_label}" ]] || fail "runner label differs"
  [[ ${SERVICERADAR_RUNNER_VERSION:-} == "${approved_runner_version}" ]] || fail "runner version differs"
  [[ ${SERVICERADAR_RUNNER_GUEST_ID:-} =~ ^serviceradar-public-job-[0-9]+-[0-9a-f]{8}$ ]] || \
    fail "disposable guest identity is invalid"
  [[ ${EXPECTED_COMMIT:-} =~ ^[0-9a-f]{40}$ ]] || fail "expected commit evidence is invalid"
  [[ ${GITHUB_SHA:-} == "${EXPECTED_COMMIT}" ]] || fail "workflow commit differs from reviewed commit"
  [[ $(git rev-parse HEAD) == "${EXPECTED_COMMIT}" ]] || fail "checked-out commit differs from reviewed commit"
  [[ ${GITHUB_SERVER_URL:-} == "${approved_forgejo_url}" ]] || fail "Forgejo server URL differs"

  [[ $(id -u) -eq 0 ]] || fail "diagnostic must run as root inside the disposable guest"
  local map_kind
  for map_kind in uid gid; do
    awk '
      NF > 0 { lines++ }
      NF == 3 && $1 == 0 && $2 == 1000000 && $3 == 65536 { exact++ }
      END { exit lines == 1 && exact == 1 ? 0 : 1 }
    ' "/proc/1/${map_kind}_map" || \
      fail "PID 1 ${map_kind} map is not the exact singleton reviewed mapping"
  done

  printf 'runner_boundary=%s\n' "${SERVICERADAR_RUNNER_BOUNDARY}"
  printf 'runner_repository_id=%s\n' "${SERVICERADAR_RUNNER_REPOSITORY_ID}"
  printf 'runner_repository=%s\n' "${SERVICERADAR_RUNNER_REPOSITORY}"
  printf 'runner_label=%s\n' "${SERVICERADAR_RUNNER_LABEL}"
  printf 'runner_version=%s\n' "${SERVICERADAR_RUNNER_VERSION}"
  printf 'runner_guest_id=%s\n' "${SERVICERADAR_RUNNER_GUEST_ID}"
}

assert_no_ambient_credentials() {
  local name
  local -a forbidden_environment=(
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    AWS_SESSION_TOKEN
    ALL_PROXY
    AZURE_CLIENT_SECRET
    AZURE_FEDERATED_TOKEN_FILE
    BAO_TOKEN
    BUILDBUDDY_ORG_API_KEY
    COSIGN_KEY
    COSIGN_KEY_REF
    DOCKER_AUTH_CONFIG
    DOCKER_CONFIG
    FORGEJO_API_TOKEN
    FORGEJO_RUNNER_REGISTRATION_TOKEN
    FORGEJO_RUNNER_TOKEN
    GOOGLE_APPLICATION_CREDENTIALS
    GOOGLE_OAUTH_ACCESS_TOKEN
    HARBOR_ROBOT_SECRET
    HTTPS_PROXY
    HTTP_PROXY
    KUBECONFIG
    KUBERNETES_SERVICE_HOST
    KUBERNETES_SERVICE_PORT
    NO_PROXY
    OCI_TOKEN
    OPENBAO_TOKEN
    PLUGIN_UPLOAD_SIGNING_PRIVATE_KEY
    REGISTRY_AUTH_FILE
    SERVICERADAR_AGENT_RELEASE_PRIVATE_KEY
    SERVICERADAR_CALLBACK_BEARER
    SIGSTORE_ID_TOKEN
    SSH_AUTH_SOCK
    VAULT_TOKEN
    AWS_WEB_IDENTITY_TOKEN_FILE
    all_proxy
    http_proxy
    https_proxy
    no_proxy
  )
  for name in "${forbidden_environment[@]}"; do
    [[ -z ${!name:-} ]] || fail "forbidden ambient environment variable is present: ${name}"
  done
  [[ -n ${FORGEJO_TOKEN:-} ]] || fail "automatic Forgejo job token is absent"
  [[ ${FORGEJO_TOKEN} == "${GITHUB_TOKEN:-}" ]] || fail "automatic Forgejo job token aliases differ"
  while IFS= read -r name; do
    case ${name} in
      GIT_*|SSH_ASKPASS)
        fail "forbidden Git or askpass environment category is present"
        ;;
    esac
  done < <(compgen -e)

  local -a forbidden_path_checks=(
    "container-registry-auth|/etc/containers/auth.json"
    "persistent-runner-api-token|/etc/forgejo-public-runner/api-token"
    "persistent-runner-host-config|/etc/forgejo-public-runner/host.env"
    "kubernetes-admin-config|/etc/kubernetes/admin.conf"
    "kubernetes-node-config|/etc/rancher/k3s/k3s.yaml"
    "container-registry-runtime-auth|/run/containers/0/auth.json"
    "kubernetes-runtime-socket|/run/k3s/containerd/containerd.sock"
    "kubernetes-service-account|/run/secrets/kubernetes.io/serviceaccount/token"
    "kubernetes-node-state|/var/lib/kubelet"
    "kubernetes-service-account|/var/run/secrets/kubernetes.io/serviceaccount/token"
    "git-credential-store|${HOME}/.git-credentials"
    "github-cli-auth|${HOME}/.config/gh/hosts.yml"
    "git-credential-store|${HOME}/.config/git/credentials"
    "forgejo-cli-auth|${HOME}/.config/tea/config.yml"
    "curl-config|${HOME}/.curlrc"
    "netrc-auth|${HOME}/.netrc"
    "npm-auth|${HOME}/.npmrc"
    "python-package-auth|${HOME}/.pypirc"
  )
  local label
  local path
  local check
  for check in "${forbidden_path_checks[@]}"; do
    IFS='|' read -r label path <<<"${check}"
    [[ ! -e ${path} && ! -L ${path} ]] || \
      fail "forbidden credential or host state category is present: ${label}"
  done

  local -a forbidden_sockets=(
    /run/containerd/containerd.sock
    /run/forgejo-docker/docker.sock
    /run/lxc/lxc-monitord.socket
    /var/run/containerd/containerd.sock
  )
  for path in "${forbidden_sockets[@]}"; do
    [[ ! -S ${path} ]] || fail "forbidden host control socket is present: ${path}"
  done
  [[ ! -e /var/lib/lxc ]] || fail "host LXC state is visible inside the job guest"

  python3 -I - "${HOME}" <<'PY'
import pathlib
import sys

home = pathlib.Path(sys.argv[1])
for relative in (".aws", ".azure", ".config/gcloud", ".kube"):
    if (home / relative).exists():
        raise SystemExit("cloud or Kubernetes credential/cache state is present under HOME")

private_markers = (
    b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----",
    b"-----BEGIN " + b"RSA PRIVATE KEY-----",
    b"-----BEGIN " + b"EC PRIVATE KEY-----",
    b"-----BEGIN " + b"DSA PRIVATE KEY-----",
    b"-----BEGIN " + b"ENCRYPTED PRIVATE KEY-----",
    b"-----BEGIN " + b"PRIVATE KEY-----",
)
for candidate in home.rglob("*"):
    try:
        if not candidate.is_file() or candidate.stat().st_size > 1024 * 1024:
            continue
        if candidate.name.startswith("id_") and not candidate.name.endswith(".pub"):
            raise SystemExit("private key material is present under HOME")
        if candidate.suffix.lower() in {".key", ".p12", ".pfx"}:
            raise SystemExit("private key material is present under HOME")
        content = candidate.read_bytes()
    except (FileNotFoundError, PermissionError, OSError):
        continue
    if any(marker in content for marker in private_markers):
        raise SystemExit("private key material is present under HOME")
PY

  python3 -I <<'PY'
import subprocess

result = subprocess.run(
    ["git", "config", "--null", "--name-only", "--list"],
    check=False,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
)
if result.returncode != 0:
    raise SystemExit("Git configuration cannot be inspected safely")
keys = result.stdout.decode("utf-8", "surrogateescape").split("\0")
dangerous_suffixes = (
    ".cookiefile",
    ".extraheader",
    ".insteadof",
    ".proxy",
    ".pushinsteadof",
    ".sslcert",
    ".sslkey",
)
if any(
    key.casefold().startswith(
        ("credential.", "filter.", "http.", "include.", "url.")
    )
    or key.casefold().startswith("includeif.")
    or key.casefold() in {
        "core.alternaterefscommand",
        "core.askpass",
        "core.attributesfile",
        "core.fsmonitor",
        "core.fsmonitorhookversion",
        "core.gitproxy",
        "core.hookspath",
        "core.pager",
        "core.sshcommand",
        "core.worktree",
        "init.templatedir",
    }
    or (
        key.casefold().startswith("remote.")
        and key.casefold().rsplit(".", 1)[-1].startswith("proxy")
    )
    or key.casefold().endswith(dangerous_suffixes)
    for key in keys
    if key
):
    raise SystemExit(
        "Git configuration contains a credential, rewrite, proxy, or execution hook"
    )
PY
  python3 -I - "${approved_forgejo_url}" <<'PY'
import subprocess
import sys
import urllib.parse

approved = urllib.parse.urlparse(sys.argv[1])
result = subprocess.run(
    ["git", "remote", "get-url", "--all", "origin"],
    check=False,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
)
if result.returncode != 0:
    raise SystemExit("Git origin cannot be inspected safely")
urls = [line for line in result.stdout.splitlines() if line]
if len(urls) != 1:
    raise SystemExit("Git origin does not have exactly one reviewed URL")
try:
    remote = urllib.parse.urlparse(urls[0])
    matches = (
        remote.scheme == "https"
        and remote.hostname == approved.hostname
        and remote.port is None
        and remote.username is None
        and remote.password is None
        and not remote.query
        and not remote.fragment
        and remote.path
        in (
            "/carverauto/serviceradar-ansible",
            "/carverauto/serviceradar-ansible.git",
        )
    )
except ValueError:
    matches = False
if not matches:
    raise SystemExit("Git origin URL differs from the reviewed credential-free origin")
PY

  if [[ -e ${HOME}/.docker/config.json ]]; then
    python3 -I - "${HOME}/.docker/config.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    config = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit("Docker config exists but is not a readable JSON object") from exc
if not isinstance(config, dict):
    raise SystemExit("Docker config exists but is not a JSON object")
if config.get("credsStore") or config.get("credHelpers"):
    raise SystemExit("Docker config exposes a credential helper")
auths = config.get("auths", {})
if not isinstance(auths, dict):
    raise SystemExit("Docker config authentication structure is invalid")
for entry in auths.values():
    if isinstance(entry, dict) and any(
        entry.get(key) for key in ("auth", "identitytoken", "identityToken", "username", "password")
    ):
        raise SystemExit("Docker config exposes reusable authentication")
PY
  fi

  echo "ambient_credential_and_host_socket_absence=verified"
}

assert_clean_start() {
  local previous_guest=${1:-}
  if [[ -n ${previous_guest} ]]; then
    [[ ${previous_guest} =~ ^serviceradar-public-job-[0-9]+-[0-9a-f]{8}$ ]] || \
      fail "previous guest evidence is malformed"
    [[ ${SERVICERADAR_RUNNER_GUEST_ID} != "${previous_guest}" ]] || \
      fail "the same disposable guest identity accepted a second job"
    printf 'previous_runner_guest_id=%s\n' "${previous_guest}"
  fi

  [[ ${GITHUB_WORKSPACE:-} == "${workspace_root}/"* ]] || \
    fail "workspace boundary differs"
  [[ ! -L ${workspace_root} ]] || fail "workspace root is a symbolic link"
  [[ $(realpath -e -- "${workspace_root}") == "${workspace_root}" ]] || \
    fail "workspace root is not canonical"
  [[ $(realpath -e -- "${GITHUB_WORKSPACE}") == "${GITHUB_WORKSPACE}" ]] || \
    fail "workspace directory is not canonical"
  [[ ! -e ${GITHUB_WORKSPACE}/${workspace_sentinel} && \
    ! -L ${GITHUB_WORKSPACE}/${workspace_sentinel} ]] || \
    fail "prior-job workspace sentinel survived"

  local -a sentinel_paths=(
    "/root/${sentinel_name}"
    "/run/forgejo-public-runner/${sentinel_name}"
    "/tmp/${sentinel_name}"
    "/var/tmp/${sentinel_name}"
  )
  local path
  for path in "${sentinel_paths[@]}"; do
    [[ ! -e ${path} && ! -L ${path} ]] || fail "prior-job filesystem sentinel survived: ${path}"
  done

  python3 -I - "${sentinel_name}" <<'PY'
import pathlib
import sys

needle = (sys.argv[1] + "\0").encode()
for cmdline in pathlib.Path("/proc").glob("[0-9]*/cmdline"):
    try:
        if cmdline.read_bytes().startswith(needle):
            raise SystemExit(f"prior-job process sentinel survived as PID {cmdline.parent.name}")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        pass
PY

  [[ ${DOCKER_HOST:-} == unix:///var/run/docker.sock ]] || fail "inner Docker endpoint differs"
  [[ -S /var/run/docker.sock ]] || fail "expected inner Docker socket is absent"
  docker info >/dev/null || fail "inner Docker daemon is unavailable"
  if docker volume inspect "${sentinel_name}" >/dev/null 2>&1; then
    fail "prior-job Docker volume sentinel survived"
  fi
  if docker image inspect "${diagnostic_image}" >/dev/null 2>&1; then
    fail "prior-job diagnostic image survived in inner Docker"
  fi

  echo "cross_job_workspace_process_and_docker_state_absence=verified"
}

assert_private_network_denial() {
  python3 -I <<'PY'
import errno
import socket

targets = (
    ("kubernetes-api-service", "10.43.0.1", 443),
    ("openbao-active", "10.43.201.1", 8200),
    ("kubernetes-node-api", "10.0.2.11", 6443),
    ("proxmox-management", "192.168.2.10", 8006),
    ("runner-host-management", "10.213.1.6", 22),
    ("private-farm01-host", "192.168.1.62", 22),
    ("private-tonka01-host", "192.168.2.22", 22),
    ("private-storage-database", "192.168.2.134", 5432),
    ("link-local-metadata", "169.254.169.254", 80),
    ("ipv6-ula", "fd00::1", 443),
)

unexpected = []
for label, host, port in targets:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
    except OSError as exc:
        if family == socket.AF_INET6 and exc.errno in {
            errno.EAFNOSUPPORT,
            errno.EPROTONOSUPPORT,
        }:
            print(
                f"denied_target={label} endpoint={host}:{port} "
                f"result=unsupported errno={exc.errno} expected=ipv6-disabled"
            )
            continue
        raise
    sock.settimeout(2.0)
    try:
        sock.connect((host, port))
    except TimeoutError:
        if family != socket.AF_INET:
            unexpected.append(f"{label} returned an unexpected IPv6 timeout")
        else:
            print(
                f"denied_target={label} endpoint={host}:{port} "
                "result=timeout expected=host-firewall-drop"
            )
    except OSError as exc:
        expected_ipv6_errors = {
            errno.EACCES,
            errno.EHOSTUNREACH,
            errno.ENETUNREACH,
            errno.EPERM,
        }
        if family == socket.AF_INET6 and exc.errno in expected_ipv6_errors:
            print(
                f"denied_target={label} endpoint={host}:{port} "
                f"result=unreachable errno={exc.errno} expected=ipv6-no-route-or-drop"
            )
        else:
            unexpected.append(f"{label} returned unexpected errno {exc.errno}")
    else:
        unexpected.append(f"{label} connected unexpectedly")
    finally:
        sock.close()

if unexpected:
    raise SystemExit("forbidden private probe behavior differed: " + ", ".join(unexpected))
PY
  echo "private_kubernetes_openbao_proxmox_network_denial=verified"
}

probe_https() {
  local label=$1
  local url=$2
  local expected_pattern=$3
  local status
  status=$(curl -q --silent --show-error --noproxy '*' \
    --proto '=https' --proto-redir '=https' --tlsv1.2 \
    --connect-timeout 10 --max-time 30 --output /dev/null \
    --write-out '%{http_code}' "${url}") || fail "approved HTTPS probe failed: ${label}"
  [[ ${status} =~ ${expected_pattern} ]] || fail "approved HTTPS probe ${label} returned HTTP ${status}"
  printf 'approved_https_egress=%s status=%s\n' "${label}" "${status}"
}

assert_approved_public_egress_and_inner_docker() {
  local forgejo_url=${GITHUB_SERVER_URL:-}
  [[ ${forgejo_url} == "${approved_forgejo_url}" ]] || fail "Forgejo server URL differs"

  python3 -I - "${forgejo_url}" <<'PY'
import ipaddress
import socket
import sys
import urllib.parse

hosts = (
    urllib.parse.urlparse(sys.argv[1]).hostname,
    "registry-1.docker.io",
    "snapshot.ubuntu.com",
    "time.cloudflare.com",
)
for host in hosts:
    if not host:
        raise SystemExit("approved endpoint has no hostname")
    addresses = {item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    if not addresses:
        raise SystemExit(f"DNS returned no address for {host}")
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise SystemExit(f"DNS returned non-public address for {host}: {address}")
    print(f"approved_dns_resolution={host} address_count={len(addresses)}")
PY

  python3 -I <<'PY'
import socket

packet = b"\x1b" + (47 * b"\0")
last_error = None
for family, socktype, proto, _, sockaddr in socket.getaddrinfo(
    "time.cloudflare.com", 123, type=socket.SOCK_DGRAM
):
    sock = socket.socket(family, socktype, proto)
    sock.settimeout(5.0)
    try:
        sock.sendto(packet, sockaddr)
        response, _ = sock.recvfrom(512)
        if len(response) < 48 or response[0] & 0x7 not in (4, 5) or not 1 <= response[1] <= 15:
            raise OSError("invalid NTP server response")
        print(f"approved_ntp_egress=time.cloudflare.com response_bytes={len(response)}")
        break
    except OSError as exc:
        last_error = exc
    finally:
        sock.close()
else:
    raise SystemExit(f"approved NTP probe failed: {type(last_error).__name__}")
PY

  probe_https forgejo "${forgejo_url}/api/v1/version" '^(200|401|403)$'
  probe_https anonymous-docker-registry 'https://registry-1.docker.io/v2/' '^(200|401)$'
  probe_https pinned-ubuntu-snapshot "${package_probe_url}" '^200$'

  docker pull "${diagnostic_image}"
  docker image inspect "${diagnostic_image}" \
    --format '{{join .RepoDigests "\n"}}' | grep -E "@${diagnostic_image_digest}$" >/dev/null || \
    fail "inner Docker did not retain the exact pulled image digest"
  docker run --rm --privileged --cgroupns=host \
    --volume /sys/fs/cgroup:/sys/fs/cgroup:rw \
    --entrypoint /bin/sh "${diagnostic_image}" -ec '
      test -r /proc/1/uid_map
      test -r /sys/fs/cgroup/cgroup.controllers
      test ! -S /run/forgejo-docker/docker.sock
      test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token
    '
  echo "inner_docker_privileged_cgroup_probe=verified"
}

write_sentinels() {
  local evidence="${GITHUB_RUN_ID:-unknown}:${GITHUB_RUN_ATTEMPT:-unknown}:${SERVICERADAR_RUNNER_GUEST_ID}"
  [[ ${GITHUB_WORKSPACE:-} == "${workspace_root}/"* ]] || \
    fail "workspace boundary differs before sentinel creation"
  [[ -d ${GITHUB_WORKSPACE} && ! -L ${GITHUB_WORKSPACE} ]] || \
    fail "workspace directory is not a real directory"
  printf '%s\n' "${evidence}" >"${GITHUB_WORKSPACE}/${workspace_sentinel}"
  chmod 0600 "${GITHUB_WORKSPACE}/${workspace_sentinel}"

  local path
  for path in \
    "/root/${sentinel_name}" \
    "/run/forgejo-public-runner/${sentinel_name}" \
    "/tmp/${sentinel_name}" \
    "/var/tmp/${sentinel_name}"; do
    printf '%s\n' "${evidence}" >"${path}"
    chmod 0600 "${path}"
  done

  docker volume create "${sentinel_name}" >/dev/null
  docker run --rm --volume "${sentinel_name}:/sentinel" \
    --entrypoint /bin/sh "${diagnostic_image}" -ec \
    'printf %s "$1" >/sentinel/evidence; chmod 0600 /sentinel/evidence' \
    sentinel-writer "${evidence}"
  nohup bash -c "exec -a ${sentinel_name} sleep 1800" </dev/null >/dev/null 2>&1 &
  sync
  printf 'sentinel_written_for_guest=%s\n' "${SERVICERADAR_RUNNER_GUEST_ID}"
}

run_diagnostic() {
  local scenario=$1
  case ${scenario} in
    success|forced-failure|timeout|hold-for-cancel|hold-for-runner-crash|hold-for-host-restart) ;;
    *) fail "unsupported scenario: ${scenario}" ;;
  esac

  assert_exact_boundary
  assert_no_ambient_credentials
  assert_clean_start
  assert_private_network_denial
  assert_approved_public_egress_and_inner_docker
  write_sentinels

  case ${scenario} in
    success)
      echo "terminal_scenario=success"
      ;;
    forced-failure)
      echo "terminal_scenario=forced-failure expected_exit=42" >&2
      exit 42
      ;;
    timeout)
      echo "terminal_scenario=timeout waiting_for_workflow_timeout"
      sleep 1800
      fail "timeout scenario was not terminated by the workflow timeout"
      ;;
    hold-for-cancel|hold-for-runner-crash|hold-for-host-restart)
      echo "terminal_scenario=${scenario} operator_hook_ready=true"
      sleep 1800
      fail "operator-controlled scenario was not interrupted before its safety timeout"
      ;;
  esac
}

verify_clean() {
  local previous_guest=$1
  [[ ${previous_guest} =~ ^serviceradar-public-job-[0-9]+-[0-9a-f]{8}$ ]] || \
    fail "previous guest evidence is required and malformed"
  assert_exact_boundary
  assert_no_ambient_credentials
  assert_clean_start "${previous_guest}"
  assert_private_network_denial
  echo "post_terminal_cleanup_and_replacement_guest=verified"
}

usage() {
  cat >&2 <<'EOF'
usage:
  public_runner_diagnostic.sh run <success|forced-failure|timeout|hold-for-cancel|hold-for-runner-crash|hold-for-host-restart>
  public_runner_diagnostic.sh verify-clean <previous-guest-id>
EOF
  exit 2
}

case ${1:-} in
  run)
    [[ $# -eq 2 ]] || usage
    run_diagnostic "$2"
    ;;
  verify-clean)
    [[ $# -eq 2 ]] || usage
    verify_clean "$2"
    ;;
  *) usage ;;
esac
