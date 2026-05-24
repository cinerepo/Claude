# Agent Capabilities Reference

What Claude agents in this repo can do — and which agent does what.

---

## Registered Agents

| Agent | Branch | What It Does |
|---|---|---|
| Github-Manager | `claude/github-repo-management-nppJe` | Branch strategy, PR/issue management, repo governance |
| Version-History | `claude/analyze-repo-changes-gJ7w4` | Cross-branch change tracking, daily repo snapshots |
| Notion-Manager | `claude/notion-manager-mK3pX` | Notion workspace topology, change tracking, persistent memory |
| Network-Health-Agent | `claude/network-health-agent` | Device discovery, client DB, port scanning, internet/gateway health |
| Wifi-Security-Agent | `claude/network-security-monitoring` | Threat detection, ARP spoofing, DNS hijack, deauth monitoring |
| Peloton-Agent | `claude/Peloton-Agent` | Storage deal knowledge base (OpenDrives, Cisco, stakeholders) |
| Pit Boss GX700 Assistant | `claude/pitboss-gx700` | Pellet grill cooking profiles, internal temps, timing guides |
| Agent-Showcase | `claude/agent-showcase-watch-folders-Bf99R` | Demonstrates agent patterns: watch folders, data-driven generation, routing |

---

## What Claude Agents Can Do

### Memory & Context
- Read `.md` files at session start to restore working context
- Maintain persistent state in JSON or `.md` files on agent branches
- Track history with dated entries in their definition file

### Watch & React
- Monitor designated folders for new/changed `.md` files
- Process incoming files based on type or auto-detected intent
- Write outputs to designated output folders

### Data-Driven Generation
- Load reference `.md` files from a data folder as grounding context
- Fill templates with extracted data
- Generate reports, summaries, routing decisions based on real data

### Tool Integration
- GitHub MCP: read/write issues, PRs, branches, files
- Notion MCP: read/write pages, databases, properties
- Slack MCP: read channels, send messages
- Bash: run scripts, scan networks, query systems

### Routing & Delegation
- Identify which agent should handle a task
- Generate the exact instruction for that agent
- Chain agents together (one agent's output becomes another's input)

### Scheduled Operations
- Run daily/periodic jobs via Claude Code's schedule system
- Auto-update their definition files with dated history entries
- Push changes back to their branch after each run

---

## Agent Design Patterns

### Pattern 1: Watch + Generate
Agent monitors a folder → reads new files → generates output using templates + context

**Used by:** Agent-Showcase

### Pattern 2: Persistent Memory
Agent writes state to a JSON or `.md` file on every run → reads it at session start

**Used by:** Network-Health-Agent (`clients.json`), Wifi-Security-Agent (`baseline.json`), Notion-Manager (`notion-snapshot.md`), Version-History (`repo-snapshot.md`)

### Pattern 3: Scheduled Sweep
Agent runs on a schedule → fetches current state → diffs against last known state → logs changes

**Used by:** Version-History (daily), Notion-Manager (session start)

### Pattern 4: Knowledge Base + Q&A
Agent ingests a set of source documents → answers questions about that domain

**Used by:** Peloton-Agent (deal docs), Pit Boss GX700 (grill specs), Agent-Showcase (data folder)

### Pattern 5: Tool-Backed Action
Agent reads a task → uses MCP tools to take a real action (create branch, update Notion page, send Slack message)

**Used by:** Github-Manager, Notion-Manager

---

*This file is the meta-reference for Agent-Showcase. When routing or Q&A tasks ask about agent capabilities, load this file.*
