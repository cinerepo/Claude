# Claude Personal Assistant — cinerepo

## Agent Registry

At the start of every session, read all agent docs listed below. They define the roles and tools available to you as a personal assistant.

| Agent | Branch | File | Role |
|---|---|---|---------|
| Github-Manager | `claude/github-repo-management-nppJe` | `Github-Manager.md` | Repo governance, branch strategy, PR/issue management |
| Version-History | `claude/analyze-repo-changes-gJ7w4` | `Version-History.md` | Cross-branch change tracking and repo analysis |

Agent docs are cached locally at `.claude/agents/` — read them from there each session.

---

## Session Startup Behavior

1. Read `.claude/agents/Github-Manager.md` to load repo governance context
2. Read `.claude/agents/Version-History.md` to load version tracking context
3. Use these agents whenever the user asks about GitHub activity, repo changes, or project status

---

## Repository

- **Owner:** cinerepo
- **Repo:** claude
- **Restricted to:** `cinerepo/claude` only
