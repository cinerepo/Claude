#!/bin/bash
set -euo pipefail

# Only run in remote (Claude Code web) environment
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

AGENTS_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/agents"
mkdir -p "$AGENTS_DIR"

BASE_URL="https://raw.githubusercontent.com/cinerepo/claude"
API_URL="https://api.github.com/repos/cinerepo/claude"

echo "[session-start] Fetching agent docs..."

# Fetch Github-Manager
curl -fsSL "${BASE_URL}/claude/github-repo-management-nppJe/Github-Manager.md" \
  -o "${AGENTS_DIR}/Github-Manager.md" && \
  echo "[session-start] Github-Manager.md loaded" || \
  echo "[session-start] WARNING: Failed to fetch Github-Manager.md"

# Fetch Version-History
curl -fsSL "${BASE_URL}/claude/analyze-repo-changes-gJ7w4/Version-History.md" \
  -o "${AGENTS_DIR}/Version-History.md" && \
  echo "[session-start] Version-History.md loaded" || \
  echo "[session-start] WARNING: Failed to fetch Version-History.md"

echo "[session-start] Building repo snapshot for Version-History..."

SNAPSHOT_FILE="${AGENTS_DIR}/repo-snapshot.md"
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M UTC")

{
  echo "# Repo Snapshot — cinerepo/claude"
  echo "Generated: ${TIMESTAMP}"
  echo ""
  echo "## Branches"
  echo ""

  # Fetch all branches and their latest commit
  BRANCHES=$(curl -fsSL "${API_URL}/branches" 2>/dev/null || echo "[]")
  if [ "$BRANCHES" != "[]" ]; then
    echo "$BRANCHES" | grep -o '"name":"[^"]*"' | sed 's/"name":"//;s/"//' | while read -r branch; do
      COMMIT=$(curl -fsSL "${API_URL}/commits?sha=${branch}&per_page=1" 2>/dev/null || echo "[]")
      SHA=$(echo "$COMMIT" | grep -o '"sha":"[^"]*"' | head -1 | sed 's/"sha":"//;s/"//' | cut -c1-7)
      MSG=$(echo "$COMMIT" | grep -o '"message":"[^"]*"' | head -1 | sed 's/"message":"//;s/"//' | cut -c1-60)
      echo "- \`${branch}\` — \`${SHA}\` ${MSG}"
    done
  else
    echo "- Unable to fetch branches"
  fi

  echo ""
  echo "## Recent Commits (main)"
  echo ""

  COMMITS=$(curl -fsSL "${API_URL}/commits?per_page=5" 2>/dev/null || echo "[]")
  if [ "$COMMITS" != "[]" ]; then
    echo "$COMMITS" | grep -o '"sha":"[^"]*"\|"message":"[^"]*"' | paste - - | \
      sed 's/"sha":"//;s/"message":"//;s/"//g' | \
      awk -F'\t' '{print "- `" substr($1,1,7) "` " substr($2,1,72)}' || \
      echo "- Unable to parse commits"
  else
    echo "- Unable to fetch commits"
  fi

} > "$SNAPSHOT_FILE"

echo "[session-start] Repo snapshot written to ${SNAPSHOT_FILE}"
echo "[session-start] Agent docs ready at ${AGENTS_DIR}"
