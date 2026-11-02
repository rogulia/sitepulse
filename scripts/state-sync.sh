#!/usr/bin/env bash
# Persist SitePulse state in the `state` branch of the calling repository.
#
#   state-sync.sh pull
#   state-sync.sh push <file> [<file> ...]
#
# The branch always holds one parentless commit with state/<file>. `push` only
# replaces the named files, so workflows for different checks do not overwrite
# each other, and it retries when another run updated the branch meanwhile.
set -euo pipefail

BRANCH="${SITEPULSE_STATE_BRANCH:-state}"
STATE_DIR="${SITEPULSE_STATE_DIR:?SITEPULSE_STATE_DIR is required}"
REMOTE="${SITEPULSE_STATE_REMOTE:-origin}"

pull() {
  mkdir -p "$STATE_DIR"
  if git fetch --quiet "$REMOTE" "$BRANCH" 2>/dev/null; then
    git archive FETCH_HEAD state | tar -x -C "$(dirname "$STATE_DIR")"
  fi
}

push() {
  local attempt base tree commit index
  index="$(mktemp -u)"
  trap 'rm -f "$index"' RETURN

  for attempt in 1 2 3 4 5; do
    base=""
    if git fetch --quiet "$REMOTE" "$BRANCH" 2>/dev/null; then
      base="$(git rev-parse FETCH_HEAD)"
    fi

    rm -f "$index"
    if [ -n "$base" ]; then
      GIT_INDEX_FILE="$index" git read-tree "$base"
    else
      GIT_INDEX_FILE="$index" git read-tree --empty
    fi

    local file blob
    for file in "$@"; do
      [ -f "$STATE_DIR/$file" ] || continue
      blob="$(git hash-object -w "$STATE_DIR/$file")"
      GIT_INDEX_FILE="$index" git update-index --add --cacheinfo "100644,$blob,state/$file"
    done
    tree="$(GIT_INDEX_FILE="$index" git write-tree)"

    if [ -n "$base" ] && [ "$(git rev-parse "$base^{tree}")" = "$tree" ]; then
      return 0
    fi

    commit="$(git -c user.name=sitepulse -c user.email=sitepulse@users.noreply.github.com \
      commit-tree "$tree" -m "Update SitePulse state")"
    if git push --quiet --force-with-lease="refs/heads/$BRANCH:$base" \
      "$REMOTE" "$commit:refs/heads/$BRANCH"; then
      return 0
    fi
    echo "state push attempt $attempt failed, retrying" >&2
    sleep $((attempt * 2))
  done
  echo "could not push state after 5 attempts" >&2
  return 1
}

case "${1:-}" in
  pull) pull ;;
  push) shift; push "$@" ;;
  *) echo "usage: $0 pull | push <file>..." >&2; exit 2 ;;
esac
