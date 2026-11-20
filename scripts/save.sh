#!/usr/bin/env bash
# Commit data/ and push, merging data/state.json if another run saved first.
# Usage: scripts/save.sh "commit message" backfill|nightly [cursor-key]
set -euo pipefail
msg="$1"; owner="$2"; cursor="${3:-}"
git config user.name "records-harvester"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
ours="$(mktemp)"
cp data/state.json "$ours"
git add data
git diff --cached --quiet && { echo "nothing to save"; exit 0; }
git commit -q -m "$msg"
for attempt in 1 2 3 4 5; do
  git fetch -q origin main
  if ! git rebase -q origin/main; then
    conflicts="$(git diff --name-only --diff-filter=U)"
    if [ "$conflicts" != "data/state.json" ]; then
      echo "unexpected conflicts: $conflicts"; git rebase --abort; exit 1
    fi
    theirs="$(mktemp)"
    git show origin/main:data/state.json > "$theirs"
    python -m harvester.merge_state "$theirs" "$ours" --owner "$owner" ${cursor:+--cursor "$cursor"} > data/state.json
    git add data/state.json
    GIT_EDITOR=true git rebase --continue
  fi
  if git push -q origin HEAD:main; then echo "saved on attempt $attempt"; exit 0; fi
  sleep $((attempt * 10))
done
echo "could not push after 5 attempts"; exit 1
