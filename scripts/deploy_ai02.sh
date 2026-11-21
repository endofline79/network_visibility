#!/usr/bin/env bash
# Safe, repeatable rollout script for AI-02 (192.168.5.230).
#
# Preserves .env, state/, and running logs/api containers. Tags current images
# as *:rollback-pre-<sha> before building so any service can be rolled back
# immediately without rebuilding.
#
# Usage (on AI-02 inside /home/klab/codex/Visibility):
#   ./scripts/deploy_ai02.sh                    # pull, build & recreate app services
#   ./scripts/deploy_ai02.sh --no-pull console  # rebuild & recreate console only
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIVE_COMPOSE="${LIVE_COMPOSE:-/home/klab/.local/share/visibility/presentation-deploy/compose.live.yaml}"
DO_PULL=1
SERVICES=()

for arg in "$@"; do
  case "$arg" in
    --no-pull) DO_PULL=0 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *) SERVICES+=("$arg") ;;
  esac
done

if [ "${#SERVICES[@]}" -eq 0 ]; then
  SERVICES=(telemetry filterlog-relay flows alerter console)
fi

cd "$REPO_DIR"

if [ ! -e .env ]; then
  echo "ERROR: $REPO_DIR/.env is missing; refusing to deploy." >&2
  exit 1
fi

if [ "$DO_PULL" -eq 1 ]; then
  if [ ! -d .git ]; then
    echo "ERROR: $REPO_DIR is not a git checkout (use --no-pull or convert to git first)." >&2
    exit 1
  fi
  if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: working tree has local changes; commit or stash before pulling." >&2
    git status --short >&2
    exit 1
  fi
fi

BEFORE_SHA="local"
if [ -d .git ]; then
  BEFORE_SHA="$(git rev-parse --short HEAD)"
fi
ROLLBACK_TAG="rollback-pre-${BEFORE_SHA}-$(date -u +%Y%m%dT%H%M%SZ)"

tag_rollback() {
  local image="$1"
  local repo="${image%%:*}"
  if docker image inspect "$image" >/dev/null 2>&1; then
    docker tag "$image" "${repo}:${ROLLBACK_TAG}"
    echo "Tagged rollback image: ${repo}:${ROLLBACK_TAG}"
  fi
}

if [ "$DO_PULL" -eq 1 ]; then
  echo "=== Pulling origin/main (ff-only) ==="
  git pull --ff-only
fi

echo "=== Validating Compose configuration ==="
docker compose config --quiet

CORE_SERVICES=()
WANT_CONSOLE=0
for svc in "${SERVICES[@]}"; do
  case "$svc" in
    console)
      WANT_CONSOLE=1
      tag_rollback "visibility-console:0.5.1"
      ;;
    telemetry)
      CORE_SERVICES+=("telemetry")
      tag_rollback "visibility-telemetry:0.1.0"
      ;;
    filterlog-relay)
      CORE_SERVICES+=("filterlog-relay")
      tag_rollback "visibility-filterlog-relay:0.1.0"
      ;;
    flows)
      CORE_SERVICES+=("flows")
      tag_rollback "visibility-flows:0.1.0"
      ;;
    alerter)
      CORE_SERVICES+=("alerter")
      tag_rollback "visibility-alerter:0.1.0"
      ;;
    *)
      echo "ERROR: unknown service '$svc' (allowed: telemetry filterlog-relay flows alerter console)" >&2
      exit 1
      ;;
  esac
done

if [ "${#CORE_SERVICES[@]}" -gt 0 ]; then
  echo "=== Building core services: ${CORE_SERVICES[*]} ==="
  docker compose build "${CORE_SERVICES[@]}"
fi

if [ "$WANT_CONSOLE" -eq 1 ]; then
  echo "=== Building visibility-console:0.5.1 ==="
  docker build -t visibility-console:0.5.1 ./presentation
fi

if [ "${#CORE_SERVICES[@]}" -gt 0 ]; then
  echo "=== Recreating core services (--no-deps; logs/api untouched) ==="
  docker compose up -d --no-deps --force-recreate "${CORE_SERVICES[@]}"
fi

if [ "$WANT_CONSOLE" -eq 1 ]; then
  if [ ! -f "$LIVE_COMPOSE" ]; then
    echo "ERROR: live console compose file not found at $LIVE_COMPOSE" >&2
    exit 1
  fi
  echo "=== Recreating presentation console ==="
  docker compose -f "$LIVE_COMPOSE" up -d --no-deps --pull never --force-recreate console
fi

echo "=== Container status ==="
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}" | grep -E "^(NAMES|visibility-)"
echo "Rollback tag for this deploy: ${ROLLBACK_TAG}"
