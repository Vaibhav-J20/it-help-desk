#!/usr/bin/env bash
# scripts/podman_opensearch.sh
#
# Manages a rootless Podman machine and OpenSearch 2.15.0 container for local
# development on an IBM-managed macOS work laptop.
#
# Usage:
#   scripts/podman_opensearch.sh init      — create machine (one-time)
#   scripts/podman_opensearch.sh start     — start OpenSearch
#   scripts/podman_opensearch.sh status    — show machine and container state
#   scripts/podman_opensearch.sh verify    — persistence smoke test
#   scripts/podman_opensearch.sh snapshot  — register repo and create snapshot
#   scripts/podman_opensearch.sh stop      — stop container and machine cleanly
#
# Pinned versions:
#   Podman client:    5.7.1  (official Red Hat macOS arm64 installer)
#   Podman VM image:  podman-machine-os v5.7.1 applehv arm64
#                     SHA-256: 755f2149fbd7459cd18238941fb6e9e701a2fff9c3af468f81315ccf601ac8d2
#   OpenSearch:       opensearchproject/opensearch:2.15.0
#
# IBM MDM / endpoint-security note:
#   Podman is NOT yet confirmed as an approved application on IBM-managed macOS
#   laptops.  Before running this script on a corporate device, open a HelpNow
#   ticket to confirm that Podman Desktop / Podman CLI is on the approved
#   software catalog.  Do NOT bypass MDM controls to install it.
#   This script is provided for use only after that approval is confirmed.
#
# Security note:
#   The container binds ONLY to 127.0.0.1:9200 and disables the OpenSearch
#   security plugin. This is intentional for loopback-only local development.
#   Remote, shared, and OpenShift deployments MUST use HTTPS, credentials, and
#   a trusted CA. Set OPENSEARCH_URL, OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD,
#   and OPENSEARCH_VERIFY_CERTS=true in .env for those environments.

set -euo pipefail

MACHINE_NAME="it-helpdesk"
CONTAINER_NAME="it-helpdesk-opensearch"
IMAGE="opensearchproject/opensearch:2.15.0"

# Pinned machine-OS image for reproducible creation. The applehv provider is
# required for Apple Silicon (M1/M2/M3) with the Apple Hypervisor framework.
MACHINE_IMAGE="https://github.com/podman-container-tools/podman-machine-os/releases/download/v5.7.1/podman-machine.aarch64.applehv.raw.zst"

BASE_DIR="${IT_HELPDESK_OPENSEARCH_HOME:-$HOME/.local/share/it-helpdesk/opensearch}"
DATA_DIR="$BASE_DIR/data"
SNAPSHOT_DIR="$BASE_DIR/snapshots"
LOG_DIR="$BASE_DIR/logs"

# Default to loopback-only HTTP for local dev (security plugin disabled).
# The env var is honoured so callers using a remote cluster can override.
URL="${OPENSEARCH_URL:-http://127.0.0.1:9200}"

# The official macOS installer places the CLI at /opt/podman/bin/podman but
# does not modify PATH. Add it if necessary.
if ! command -v podman >/dev/null 2>&1 && [ -x /opt/podman/bin/podman ]; then
  PATH="/opt/podman/bin:$PATH"
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

require_podman() {
  command -v podman >/dev/null || {
    echo "ERROR: Podman is not installed or not in PATH." >&2
    echo "Install the official signed Red Hat macOS package from:" >&2
    echo "  https://github.com/containers/podman/releases" >&2
    exit 1
  }
}

ensure_directories() {
  mkdir -p "$DATA_DIR" "$SNAPSHOT_DIR" "$LOG_DIR"
  # On macOS with the applehv provider, virtiofs passes the macOS owner UID
  # through to the guest unchanged, so the container process can write to
  # these directories as the same effective owner.
  # 700 (owner rwx, no group or other access) is the narrowest permission
  # that still allows the container to write.  No group or world write access
  # is needed on a single-user developer laptop.
  chmod 700 "$DATA_DIR" "$SNAPSHOT_DIR" "$LOG_DIR" 2>/dev/null || true
}

machine_running() {
  # Returns 0 (true) only when the machine exists AND is in running state.
  podman machine inspect "$MACHINE_NAME" 2>/dev/null \
    | grep -q '"State": "running"'
}

ensure_machine() {
  if ! podman machine inspect "$MACHINE_NAME" >/dev/null 2>&1; then
    echo "Creating Podman machine '$MACHINE_NAME' (this downloads ~875 MiB)..."
    podman machine init \
      --cpus 4 \
      --memory 8192 \
      --disk-size 50 \
      --image "$MACHINE_IMAGE" \
      "$MACHINE_NAME"
  fi

  if ! machine_running; then
    echo "Starting Podman machine '$MACHINE_NAME'..."
    # Do NOT suppress stdout/stderr here — start errors must be visible.
    podman machine start "$MACHINE_NAME"
  fi

  # Confirm the machine is actually running after start attempt.
  if ! machine_running; then
    echo "ERROR: Machine '$MACHINE_NAME' failed to reach running state." >&2
    podman machine inspect "$MACHINE_NAME" >&2
    exit 1
  fi

  echo "Machine '$MACHINE_NAME' is running."
}

wait_for_opensearch() {
  local attempt max_attempts=60   # 60 × 2 s = 120 s total
  echo -n "Waiting for OpenSearch to become healthy"
  for attempt in $(seq 1 $max_attempts); do
    if curl --silent --fail --max-time 3 "$URL/_cluster/health" >/dev/null 2>&1; then
      echo " ready (attempt $attempt)"
      return 0
    fi
    echo -n "."
    sleep 2
  done
  echo ""
  echo "ERROR: OpenSearch did not become healthy within $((max_attempts * 2))s." >&2
  echo "Inspect logs with: podman logs $CONTAINER_NAME" >&2
  return 1
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

start_opensearch() {
  ensure_directories
  ensure_machine

  if podman container exists "$CONTAINER_NAME"; then
    local running
    running="$(podman inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || echo false)"
    if [ "$running" != "true" ]; then
      echo "Restarting stopped container '$CONTAINER_NAME'..."
      podman start "$CONTAINER_NAME"
    else
      echo "Container '$CONTAINER_NAME' is already running."
    fi
  else
    echo "Starting OpenSearch container '$CONTAINER_NAME'..."
    # UID/GID note: OpenSearch runs as UID 1000 inside the container.
    # On macOS + applehv (virtiofs), the virtiofs uid-map causes the container
    # process to write as the macOS owner UID.  The host directories are
    # pre-created with 700 (owner rwx) by ensure_directories, which is
    # sufficient.  The ":U" podman flag is a no-op for virtiofs mounts and
    # is intentionally omitted.
    podman run --detach --name "$CONTAINER_NAME" \
      --publish 127.0.0.1:9200:9200 \
      --env "discovery.type=single-node" \
      --env "DISABLE_SECURITY_PLUGIN=true" \
      --env "OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g" \
      --env "path.repo=/usr/share/opensearch/snapshots" \
      --volume "$DATA_DIR:/usr/share/opensearch/data" \
      --volume "$SNAPSHOT_DIR:/usr/share/opensearch/snapshots" \
      --volume "$LOG_DIR:/usr/share/opensearch/logs" \
      "$IMAGE"
  fi

  wait_for_opensearch
  echo "OpenSearch is healthy at $URL"
}

status() {
  require_podman
  echo "=== Podman machines ==="
  podman machine list
  echo ""
  echo "=== Container state ==="
  podman ps -a --filter "name=$CONTAINER_NAME"
  echo ""
  echo "=== OpenSearch cluster health ==="
  curl --silent --max-time 5 "$URL/_cluster/health?pretty" 2>/dev/null || \
    echo "(OpenSearch is not reachable at $URL)"
}

verify() {
  start_opensearch

  echo "--- Writing persistence-test document ---"
  curl --silent --show-error --fail \
    -X PUT "$URL/podman_persistence_check/_doc/persistence" \
    -H 'Content-Type: application/json' \
    -d '{"runtime":"podman","provider":"applehv","persistent":true,"version":"5.7.1"}' \
    | python3 -m json.tool

  echo "--- Restarting container ---"
  podman restart "$CONTAINER_NAME"
  wait_for_opensearch

  echo "--- Verifying document survives container restart ---"
  curl --silent --show-error --fail \
    "$URL/podman_persistence_check/_doc/persistence?pretty"
  echo ""
  echo "Container-restart persistence: PASSED"
  echo "Data directory: $DATA_DIR"
}

snapshot() {
  start_opensearch

  echo "--- Registering filesystem snapshot repository ---"
  curl --silent --show-error --fail \
    -X PUT "$URL/_snapshot/local_repo" \
    -H 'Content-Type: application/json' \
    -d '{"type":"fs","settings":{"location":"/usr/share/opensearch/snapshots","compress":true}}' \
    | python3 -m json.tool

  local snap_name="it-helpdesk-$(date +%Y%m%dT%H%M%S)"
  echo "--- Creating snapshot: $snap_name ---"
  curl --silent --show-error --fail \
    -X PUT "$URL/_snapshot/local_repo/${snap_name}?wait_for_completion=true" \
    | python3 -m json.tool

  echo ""
  echo "Snapshot files on macOS host: $SNAPSHOT_DIR"
  ls -lh "$SNAPSHOT_DIR" 2>/dev/null || echo "(directory is empty — check OpenSearch logs)"
}

stop() {
  require_podman
  if podman container exists "$CONTAINER_NAME"; then
    echo "Stopping container '$CONTAINER_NAME'..."
    podman stop "$CONTAINER_NAME"
  fi
  if podman machine inspect "$MACHINE_NAME" >/dev/null 2>&1; then
    echo "Stopping machine '$MACHINE_NAME'..."
    podman machine stop "$MACHINE_NAME"
  fi
  echo "Done."
}

usage() {
  echo "Usage: $0 {init|start|status|verify|snapshot|stop}" >&2
}

main() {
  require_podman
  case "${1:-}" in
    init)     ensure_directories; ensure_machine; podman info ;;
    start)    start_opensearch ;;
    status)   status ;;
    verify)   verify ;;
    snapshot) snapshot ;;
    stop)     stop ;;
    *)        usage; exit 2 ;;
  esac
}

main "$@"
