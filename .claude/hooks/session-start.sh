#!/bin/bash
set -euo pipefail

AGENTS_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/agents"
mkdir -p "$AGENTS_DIR"

REPO="cinerepo/claude"

echo "[session-start] Discovering agent branches..."

BRANCHES=$(gh api "repos/${REPO}/branches" --jq '.[].name' 2>/dev/null || true)

if [ -z "$BRANCHES" ]; then
  echo "[session-start] WARNING: Could not fetch branches — check gh auth status"
  exit 1
fi

# Process each claude/ branch
while IFS= read -r branch; do
  [[ "$branch" != claude/* ]] && continue

  # List root-level .md files, skip README.md and CLAUDE.md
  FILES=$(gh api "repos/${REPO}/contents/?ref=${branch}" \
    --jq '.[] | select(.type == "file") | select(.name | endswith(".md")) | select(.name | IN("README.md","CLAUDE.md") | not) | .name' \
    2>/dev/null || true)

  if [ -z "$FILES" ]; then
    continue
  fi

  while IFS= read -r filename; do
    dest="${AGENTS_DIR}/${filename}"
    gh api "repos/${REPO}/contents/${filename}?ref=${branch}" \
      --jq '.content' 2>/dev/null \
      | base64 --decode > "$dest" \
      && echo "[session-start] Loaded ${filename} (from ${branch})" \
      || echo "[session-start] WARNING: Failed to fetch ${filename} from ${branch}"
  done <<< "$FILES"

done <<< "$BRANCHES"

echo "[session-start] Building repo snapshot..."

SNAPSHOT_FILE="${AGENTS_DIR}/repo-snapshot.md"
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M UTC")

{
  echo "# Repo Snapshot — ${REPO}"
  echo "Generated: ${TIMESTAMP}"
  echo ""
  echo "## Branches"
  echo ""

  while IFS= read -r branch; do
    INFO=$(gh api "repos/${REPO}/commits?sha=${branch}&per_page=1" \
      --jq '.[0] | (.sha[:7]) + " " + (.commit.message | split("\n")[0][:60])' 2>/dev/null || echo "unknown")
    echo "- \`${branch}\` — ${INFO}"
  done <<< "$BRANCHES"

  echo ""
  echo "## Recent Commits (main)"
  echo ""

  gh api "repos/${REPO}/commits?per_page=5" \
    --jq '.[] | "- `" + .sha[:7] + "` " + (.commit.message | split("\n")[0][:72])' 2>/dev/null \
    || echo "- Unable to fetch commits"

} > "$SNAPSHOT_FILE"

echo "[session-start] Repo snapshot written to ${SNAPSHOT_FILE}"
echo "[session-start] Agent docs ready at ${AGENTS_DIR}"
