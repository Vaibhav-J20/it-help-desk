# Local OpenSearch with Podman

This project uses rootless Podman (Apple Hypervisor provider) for local
OpenSearch development on IBM-managed Apple Silicon MacBooks.
Docker Desktop is not required or used.

## Pinned versions

| Component | Version | Provider |
|---|---|---|
| Podman client | 5.7.1 | Official Red Hat macOS arm64 installer |
| Podman VM provider | applehv (Apple Hypervisor) | Required for M1/M2/M3 |
| Podman Machine OS | podman-machine-os v5.7.1 | SHA-256: `755f2149fbd7459cd18238941fb6e9e701a2fff9c3af468f81315ccf601ac8d2` |
| OpenSearch | 2.15.0 | `opensearchproject/opensearch:2.15.0` |

## Prerequisites

Install the official signed Red Hat macOS package for Podman 5.7.1:

```text
https://github.com/containers/podman/releases/tag/v5.7.1
```

The installer requires administrator authorization (a corporate HelpNow request
may be needed on IBM-managed laptops). It places the CLI at:

```text
/opt/podman/bin/podman
```

Add it to your shell PATH:

```bash
echo 'export PATH="/opt/podman/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

## One-time setup

```bash
# Create the Podman VM and confirm it starts cleanly
scripts/podman_opensearch.sh init

# Start OpenSearch with durable host mounts
scripts/podman_opensearch.sh start

# Verify persistence — creates a test document, restarts the container,
# and confirms the document survives
scripts/podman_opensearch.sh verify

# Register the filesystem snapshot repository and create the first snapshot
scripts/podman_opensearch.sh snapshot
```

The first `init` downloads the pinned Machine OS image (~875 MiB) and inflates
a 50 GiB VM disk. Subsequent starts use the cached image.

## Architecture

```
macOS host  ──virtiofs──▶  Podman VM (applehv)  ──container──▶  OpenSearch
  └─ ~/.local/share/it-helpdesk/opensearch/
       ├── data/        ← OpenSearch index (node data)
       ├── snapshots/   ← filesystem snapshot repository
       └── logs/        ← OpenSearch log files
```

- The Podman VM uses Apple's native Hypervisor framework (`applehv`), not
  the libkrun nested-VM provider. This is mandatory for M1/M2/M3 Apple Silicon.
- The VM mounts `/Users` and `/private` into the guest via virtiofs.
- Host directories are therefore accessible to the container without copying.
- OpenSearch binds **only** to `127.0.0.1:9200`. It is not reachable from
  other machines or network interfaces.

## Persistence and recovery

The authoritative local paths on the macOS host are:

```text
~/.local/share/it-helpdesk/opensearch/data        ← OpenSearch index
~/.local/share/it-helpdesk/opensearch/snapshots   ← filesystem snapshots
~/.local/share/it-helpdesk/opensearch/logs        ← log files
```

These are **host paths**, not named Podman volumes. They survive:

- Container restart (`podman restart`)
- Container deletion (`podman rm`)
- Podman VM stop/start (`podman machine stop` / `podman machine start`)

They do **not** survive:

- macOS account deletion or home directory wipe
- Explicit `rm -rf` of the directories
- Podman VM `--reset` with the data directory inside the VM

> **Critical:** The Podman VM disk (`applehv/it-helpdesk-arm64.raw`) is the
> ephemeral compute layer. OpenSearch data must reside in the host-mounted
> `~/.local/share/it-helpdesk/opensearch/data` directory, not inside the VM
> disk. The current configuration is correct.

If the Podman VM must be recreated:

1. The host data directories are **untouched** by `podman machine rm`.
2. Run `scripts/podman_opensearch.sh init` to recreate the VM.
3. Run `scripts/podman_opensearch.sh start` to create a new container
   pointing at the same host directories.
4. OpenSearch will read the existing index from the host-mounted data dir.

If the host data directory is deleted:

1. Re-run ingestion from COS: `python -m app.ingestion.run --manifest config/corpus/ocp_sno_poc.yaml`
2. Repeat for each corpus manifest file.

## Daily commands

```bash
# Start machine and OpenSearch (idempotent — safe to run if already running)
scripts/podman_opensearch.sh start

# Stop cleanly
scripts/podman_opensearch.sh stop

# Check status
scripts/podman_opensearch.sh status

# Create a snapshot
scripts/podman_opensearch.sh snapshot

# Persistence smoke test
scripts/podman_opensearch.sh verify

# Check container logs
/opt/podman/bin/podman logs it-helpdesk-opensearch

# Machine start/stop directly
/opt/podman/bin/podman machine stop it-helpdesk
/opt/podman/bin/podman machine start it-helpdesk
```

## Application configuration

For local development, `.env` should contain:

```dotenv
OPENSEARCH_URL=http://localhost:9200
OPENSEARCH_USERNAME=
OPENSEARCH_PASSWORD=
OPENSEARCH_VERIFY_CERTS=true
```

The local container has the OpenSearch security plugin **disabled** and is
bound to loopback only. This is intentional and safe for single-developer
local development because:

- Only processes on the same machine can reach port 9200.
- The security plugin is not needed when there is no network exposure.

**A remote, shared, or OpenShift deployment must use HTTPS, credentials,
a trusted CA certificate, and `OPENSEARCH_VERIFY_CERTS=true`.**

## Security design

| Concern | Local dev (this doc) | Remote/shared deployment |
|---|---|---|
| TLS | HTTP (loopback only) | HTTPS required |
| Auth | Security plugin disabled | Username + password required |
| Cert verification | N/A | `OPENSEARCH_VERIFY_CERTS=true` required |
| Network exposure | `127.0.0.1:9200` only | Internal cluster network only |
| IBM endpoint policy | Podman install requires IT approval | IBM-managed OpenSearch service preferred |

## Snapshot recovery

To restore from a filesystem snapshot after a data-directory loss:

```bash
# 1. Start OpenSearch (empty index)
scripts/podman_opensearch.sh start

# 2. Re-register the snapshot repository
curl -X PUT 'http://127.0.0.1:9200/_snapshot/local_repo' \
  -H 'Content-Type: application/json' \
  -d '{"type":"fs","settings":{"location":"/usr/share/opensearch/snapshots","compress":true}}'

# 3. List available snapshots
curl 'http://127.0.0.1:9200/_snapshot/local_repo/_all?pretty'

# 4. Restore a snapshot by name
curl -X POST 'http://127.0.0.1:9200/_snapshot/local_repo/<snapshot-name>/_restore?wait_for_completion=true'
```

## Known issues and notes

- The Podman machine start message mentions `/var/run/docker.sock`. This is the
  Podman Docker-compatibility socket. It is not required and not used by this
  project. Docker Desktop does not need to be installed.

- The `--device rosetta` mount in the VM provides Apple Rosetta translation
  for x86_64 container images. This is handled automatically by Podman 5.7.1
  with the applehv provider.

- On macOS with virtiofs, the Podman `:U` volume flag (which chowns mount
  points to container UID) is a no-op. The script pre-sets 777 permissions on
  the host directories so OpenSearch (UID 1000) can write through virtiofs.
  This is acceptable for single-user local development.

- The libkrun provider was used in earlier (failed) Podman setup attempts.
  Those artifacts have been cleaned up. The project now uses the applehv
  provider exclusively.

## IBM endpoint security

Podman requires administrator authorization to install on IBM-managed macOS
laptops. Confirm with IBM IT / HelpNow before installing on a new device.
The official installer is a Red Hat-signed and Apple-notarized macOS package.
Homebrew is not used.
