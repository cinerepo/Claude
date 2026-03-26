#!/bin/bash
set -euo pipefail

# Only run in remote (Claude Code web) environment
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

AGENTS_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/agents"
mkdir -p "$AGENTS_DIR"

BASE_URL="https://raw.githubusercontent.com/cinerepo/claude"

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

echo "[session-start] Agent docs ready at ${AGENTS_DIR}"
