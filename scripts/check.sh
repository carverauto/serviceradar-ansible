#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

python3 tests/validate_repository.py
python3 -m py_compile \
  roles/remote_access_ssh_ca/files/serviceradar-ssh-ca-activate \
  roles/remote_access_ssh_ca/files/serviceradar-ssh-ca-metadata-digest \
  roles/remote_access_ssh_ca/files/serviceradar-ssh-ca-policy-digest \
  roles/remote_access_ssh_ca/files/serviceradar-ssh-ca-commit \
  scripts/content_digest.py \
  tests/validate_repository.py
bash -n roles/remote_access_ssh_ca/files/serviceradar-ssh-ca-rollback
python3 scripts/content_digest.py

if command -v yamllint >/dev/null 2>&1; then
  yamllint .
else
  echo "SKIP: yamllint is not installed" >&2
fi

if command -v ansible-lint >/dev/null 2>&1; then
  ansible-lint
else
  echo "SKIP: ansible-lint is not installed" >&2
fi

if command -v ansible-playbook >/dev/null 2>&1; then
  while IFS= read -r wrapper; do
    ansible-playbook --syntax-check -i 'localhost,' "${wrapper}"
  done < <(
    find . -maxdepth 1 -type f \
      \( -name 'remote-access-*.yml' -o -name 'install-*.yml' \
         -o -name 'qemu-guest-agent-*.yml' -o -name 'ping.yml' \) \
      -print | sort
  )
else
  echo "SKIP: ansible-playbook is not installed" >&2
fi

if command -v molecule >/dev/null 2>&1; then
  molecule syntax -s windows_qga_static
else
  echo "SKIP: molecule is not installed" >&2
fi
