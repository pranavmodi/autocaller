#!/usr/bin/env bash
# Launch a Codex implementation run for one listening-system packet.
# Usage: run_packet.sh <packet.md> <workdir> [extra codex args...]
set -euo pipefail

PACKET="$1"; WORKDIR="$2"; shift 2
LOGDIR="$(dirname "$PACKET")/logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(basename "$PACKET" .md).$(date +%Y%m%d-%H%M%S).log"

echo "packet=$PACKET workdir=$WORKDIR log=$LOG"
codex exec \
  -s workspace-write \
  -c 'sandbox_workspace_write.network_access=true' \
  -C "$WORKDIR" \
  --add-dir /home/pranav/possibleos/docs/product \
  --skip-git-repo-check \
  --color never \
  "$@" \
  - < "$PACKET" 2>&1 | tee "$LOG"
echo "done: $LOG"
