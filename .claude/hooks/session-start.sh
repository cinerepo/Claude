#!/bin/bash
set -euo pipefail

AGENTS_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/agents"
mkdir -p "$AGENTS_DIR"

REPO="cinerepo/claude"

echo "[session-start] Fetching agent docs..."

# Helper: fetch a file from a specific branch using gh CLI (handles auth)
fetch_file() {
  local branch="$1"
  local path="$2"
  local dest="$3"
  local filename
  filename=$(basename "$dest")

  gh api "repos/${REPO}/contents/${path}?ref=${branch}" \
    --jq '.content' 2>/dev/null \
    | base64 --decode > "$dest" \
    && echo "[session-start] ${filename} loaded" \
    || echo "[session-start] WARNING: Failed to fetch ${filename}"
}

fetch_file "claude/github-repo-management-nppJe" "Github-Manager.md" "${AGENTS_DIR}/Github-Manager.md"
fetch_file "claude/analyze-repo-changes-gJ7w4"  "Version-History.md" "${AGENTS_DIR}/Version-History.md"
fetch_file "claude/notion-manager-mK3pX"         "Notion-Manager.md"  "${AGENTS_DIR}/Notion-Manager.md"

echo "[session-start] Building repo snapshot for Version-History..."

SNAPSHOT_FILE="${AGENTS_DIR}/repo-snapshot.md"
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M UTC")

{
  echo "# Repo Snapshot — ${REPO}"
  echo "Generated: ${TIMESTAMP}"
  echo ""
  echo "## Branches"
  echo ""

  BRANCHES=$(gh api "repos/${REPO}/branches" --jq '.[].name' 2>/dev/null || true)
  if [ -n "$BRANCHES" ]; then
    while IFS= read -r branch; do
      INFO=$(gh api "repos/${REPO}/commits?sha=${branch}&per_page=1" \
        --jq '.[0] | (.sha[:7]) + " " + (.commit.message | split("\n")[0][:60])' 2>/dev/null || echo "unknown")
      echo "- \`${branch}\` — ${INFO}"
    done <<< "$BRANCHES"
  else
    echo "- Unable to fetch branches"
  fi

  echo ""
  echo "## Recent Commits (main)"
  echo ""

  gh api "repos/${REPO}/commits?per_page=5" \
    --jq '.[] | "- `" + .sha[:7] + "` " + (.commit.message | split("\n")[0][:72])' 2>/dev/null \
    || echo "- Unable to fetch commits"

} > "$SNAPSHOT_FILE"

echo "[session-start] Repo snapshot written to ${SNAPSHOT_FILE}"
echo "[session-start] Agent docs ready at ${AGENTS_DIR}"
