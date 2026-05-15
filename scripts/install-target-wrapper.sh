#!/usr/bin/env bash
set -euo pipefail

TARGET_USER="${1:-$(id -un)}"
WRAPPER="/usr/local/bin/pb-target-exec"
SUDOERS_NAME="goalbench-${TARGET_USER//[^a-zA-Z0-9_-]/_}"
SUDOERS_PATH="/etc/sudoers.d/$SUDOERS_NAME"

usage() {
  cat <<'EOF'
Usage:
  scripts/install-target-wrapper.sh [user]

Installs /usr/local/bin/pb-target-exec and grants the user passwordless sudo
for that wrapper only. This avoids adding the benchmark user to the docker
group while still letting Codex probe ProgramBench target containers.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

sudo install -o root -g root -m 0755 scripts/pb-target-exec "$WRAPPER"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
printf '%s ALL=(root) NOPASSWD: %s *\n' "$TARGET_USER" "$WRAPPER" > "$tmp"
sudo visudo -cf "$tmp" >/dev/null
sudo install -o root -g root -m 0440 "$tmp" "$SUDOERS_PATH"
sudo visudo -cf "$SUDOERS_PATH" >/dev/null

set +e
sudo -n "$WRAPPER" __pb-wrapper-check true >/tmp/pb-target-wrapper-install.out 2>/tmp/pb-target-wrapper-install.err
status=$?
set -e

if [[ "$status" -ne 126 ]]; then
  echo "wrapper install did not verify cleanly" >&2
  cat /tmp/pb-target-wrapper-install.err >&2
  exit 1
fi

echo "Installed $WRAPPER"
echo "Installed sudoers rule $SUDOERS_PATH"
