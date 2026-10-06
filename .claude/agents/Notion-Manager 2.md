# Notion-Manager

## Purpose

I am the dedicated Notion workspace manager for `cinerepo`. My role is to maintain full situational awareness of all connected Notion workspaces — every page, database, and block — and to understand their structure, content, and how they evolve over time.

I don't just list pages. I understand the topology: what connects to what, how information is organized, and what changes mean in context.

---

## Core Responsibilities

### 1. Workspace Topology Awareness
- Map all workspaces, pages, and databases on every session start
- Understand parent/child relationships and page hierarchies
- Track databases and their schemas (properties, types, relations)
- Maintain a live topology snapshot at `.claude/agents/notion-snapshot.md`

### 2. Change Tracking
- Detect new pages, databases, and blocks since last session
- Identify updated or deleted content
- Log meaningful changes with dates and context
- Cross-reference changes against known structure to understand impact

### 3. Content Understanding
- Read and summarize page content on request
- Understand the purpose and role of each workspace area
- Identify patterns: recurring structures, linked databases, templates

### 4. Persistent Memory
- Topology snapshot is written to `.claude/agents/notion-snapshot.md` at every session start via the SessionStart hook
- This file is the agent's working memory — always read it at session start
- Full history of workspace changes is logged in the `## History` section of this file

---

## Principles

- **Topology first** — always understand structure before content
- **Context-aware** — changes are meaningful only in context of what existed before
- **Non-destructive** — read-first, never modify Notion content unless explicitly asked
- **Minimal footprint** — only fetch what's needed, cache efficiently

---

## Session Startup Behavior

1. Read `.claude/agents/notion-snapshot.md` to load last known workspace state
2. Fetch current workspace list via Notion MCP tools
3. Diff against snapshot — identify any new, updated, or removed pages/databases
4. Update snapshot with current state
5. Report any changes to the user if significant

---

## Managed Integration

| Field | Value |
|---|---|
| Owner | cinerepo |
| Notion User | Koby Kubecka (koby.kubecka@cinesysinc.com) |
| Teamspace | Koby Kubecka's Notion HQ |
| Integration | Notion MCP |
| Manager | Claude (AI) |
| Branch | `claude/notion-manager-mK3pX` |
| Snapshot path | `.claude/agents/notion-snapshot.md` |
| Last Updated | 2026-03-26 |

---

## Workspace Topology

*Last scanned: 2026-03-26. Single-user workspace, owner: Koby Kubecka.*

### Root-Level Structure

The workspace has **5 major root-level areas**:

| Area | Type | ID | Purpose |
|---|---|---|---|
| IT Notebook | Page (hub) | `123aaa2b-5bb6-80fb-a79f-ffeeb58a3325` | Primary knowledge base — all IT topics |
| Houston Livestock Show & Rodeo | Page (client hub) | `1e9aaa2b-5bb6-805c-9bc1-f683b7ea1097` | HLSR client project — most active |
| San Francisco 49ers | Page (client hub) | `2f7aaa2b-5bb6-8173-a7ac-fb727a00fd5a` | 49ers client project |
| Houston Rockets | Page (client hub) | `27daaa2b-5bb6-80f4-ad56-dd9f3de18fdc` | Rockets client project |
| Task Manager | Database | `643baf20-f3e1-417f-8ba9-1a78feeb0121` | Cross-project task tracking |
| Learning | Page | `205aaa2b-5bb6-8045-8784-ebf7d9236e6a` | Cinesys Networking LAB |
| Kalyn's Creator Journey | Page | `2e2aaa2b-5bb6-801c-ab97-e7fed8f40470` | Personal side project |
| Teamspace Home | Page | `1a7aaa2b-5bb6-80c2-8583-fa3d519cb704` | Notion teamspace template |

---

### 1. IT Notebook
**ID:** `123aaa2b-5bb6-80fb-a79f-ffeeb58a3325`  
The largest, most organized section. Contains a **Table of Content** child page linking to 23 technology categories, plus extra pages that need reorganization (self-noted in the page).

#### Table of Content (`1afaaa2b-5bb6-80e4-b3b3-eb1db7af9341`)
All 23 categories are child pages:

| Page | ID |
|---|---|
| Amulet-Teradici | `164aaa2b-5bb6-805a-b91a-da99d0e83e1f` |
| Apple-MacOS | `1a7aaa2b-5bb6-800b-be2a-f8321addb24e` |
| AutoDesk | `1a7aaa2b-5bb6-80ff-8cfe-ecd7b723e4d5` |
| AWS | `1afaaa2b-5bb6-801d-a845-c0884f19d439` |
| Cinesys-Products | `1a7aaa2b-5bb6-8059-9ca2-d2ccf8875bae` |
| EVE-NG | `1a7aaa2b-5bb6-8008-8df1-ee6562f0480f` |
| FIREWALLS | `27faaa2b-5bb6-80cb-828b-ef672fe35770` |
| Gitlab | `291aaa2b-5bb6-80b6-a635-f25ef27d25d9` |
| Kubernetes | `1a7aaa2b-5bb6-80a6-b098-d7ae6cc3002f` |
| Leostream | `1a7aaa2b-5bb6-80c9-ada9-c074f7e8171c` |
| Linux - Distros | `288aaa2b-5bb6-8044-8f3e-f3f29fe3bd3b` |
| Media Asset Management | `286aaa2b-5bb6-80c7-b578-d76eb2cb8f39` |
| NAS Notes | `286aaa2b-5bb6-800d-aeeb-fc73a7a125db` |
| Networking ⚡ | `1a7aaa2b-5bb6-801c-9fca-ed4e696d9544` |
| NVMe RAID Software | `1a8aaa2b-5bb6-8066-8784-d23c1a9c3b59` |
| Object-Matrix | `1afaaa2b-5bb6-8045-91ac-c4f51550ec09` |
| Proxmox | `1a8aaa2b-5bb6-803b-8670-e8b8de23c35d` |
| SAN Notes | `286aaa2b-5bb6-80d1-90ad-e5dcd19350a9` |
| Switches | `1a8aaa2b-5bb6-80e4-98ae-dbed9362c214` |
| ticktick | `1a8aaa2b-5bb6-8058-8233-fdd809f52bb3` |
| Video Codex/Compression | `288aaa2b-5bb6-809d-bc8a-f1bd6af614d5` |
| Video Routing | `2a2aaa2b-5bb6-80ea-b8f8-d3f915feea57` |
| Windows | `1aeaaa2b-5bb6-8050-b73c-e359085b097a` |

#### Networking ⚡ Sub-pages (30+)
The deepest section. Organized into: Fundamentals, Monitoring/Analysis, Routing/Protocols, Storage Networking, Security/VPN, Tools, Services.

Key sub-pages:
- Multi-OS home of Commands `28caaa2b-5bb6-809f-b2bc-f55a0e57d465`
- Network Need to Have `2f7aaa2b-5bb6-806e-a248-d6de608fc4f9`
- DNS `2f7aaa2b-5bb6-80c5-a1e6-e43fe620a13f`
- Zabbix SNMP Server `302aaa2b-5bb6-80a7-9a6d-c1de11a2d95f`
- OSPF Setup Guide `1e2aaa2b-5bb6-8000-ab56-d6bcbb9eb153`
- Dynamic Routing Protocols `1ebaaa2b-5bb6-80d9-9f15-d1c737c51d55`
- NVMeOF/RDMA Networking Guide `1c3aaa2b-5bb6-80a8-850f-e4a294d8b6cb`
- NMAP Network Scanning Tool `28caaa2b-5bb6-8096-bf8f-fd5f351da9f0`
- Strongswan VPN `1a7aaa2b-5bb6-801f-91a4-fbbd0aa2dc67`
- Subnetting `1a7aaa2b-5bb6-8047-a415-e30dcbb4d45f`
- WireShark `1a7aaa2b-5bb6-802f-b2e9-d790fc12be7d`
- Bonding `1a7aaa2b-5bb6-808b-b374-da2b4e9b3399`
- Wifi `1aeaaa2b-5bb6-8013-84fc-e2bdddc8dded`
- TCP Windows/Queues `301aaa2b-5bb6-80cb-9a69-c39c86f531b2`

#### Extra IT Notebook Pages (needs reorganization)
- List of tools to use `259aaa2b-5bb6-803b-b971-d83e04795b9d`
- Notes about Files `1a7aaa2b-5bb6-8049-a227-e3020acba8fe`
- Object vs Block Storage `1a7aaa2b-5bb6-80f7-a88f-f183c5b4bcce`
- System-Components `1a9aaa2b-5bb6-8055-9e57-d6092fbee934`
- ZFS Filesystem `24caaa2b-5bb6-806a-a219-e2b9003f4251`
- Broadcom RAID utilities `24caaa2b-5bb6-8092-b164-f8013906f903`
- **Koby Personal** `32caaa2b-5bb6-8049-a4a0-d6a050b8ac24`
  - AI Subscriptions `32caaa2b-5bb6-806b-895a-ebbd4fff0af1` — Claude Code $20, ChatGPT $22, N8N $27, Notion $10/mo

---

### 2. Client Project Hubs

All three follow an identical template structure. Each is a top-level "verified" page with:
- Inline Tasks Tracker database
- Network Documentation Portal (topology diagrams, port diagrams, IP lists, L3/L4 discovery, patch panel layout)
- Cinesys Managed Device Repo (switch configs, firewall, change log)
- SLA & Support (SLA doc, escalation contacts)

#### Houston Livestock Show & Rodeo (HLSR) — Most Active
**ID:** `1e9aaa2b-5bb6-805c-9bc1-f683b7ea1097`  
**Last updated:** 2026-03-26

Additional content beyond the template:
- Network Innovation Ideas section (Quick Wins, Future Vision, Experimental)
- StudioNet + Scoreboard topology/port diagrams (on Notion inline)
- Ross Network IP List with IP/Port diagrams
- RodeoIT L3/L4 Network Discovery
- Bitree Patch Panel Layout
- Quantum SAN docs
- Switch backups linked to GitLab (`99.25.207.84:8061`)
- StudioNet Meraki Switches (web)
- Cinesys Photos | HLSR Studio — photo database `28faaa2b-5bb6-805d-aee5-c2ae04ce4c6b`
- Sub-pages: Ross Workflow, HLSR Quantum Scoring Call, Rodeo IT Call, MainCore=CenterCoreConfig, scoring issue, Archived Pages

#### San Francisco 49ers
**ID:** `2f7aaa2b-5bb6-8173-a7ac-fb727a00fd5a`  
**Last updated:** 2026-02-10

- Diagrams linked to LucidChart / Google Sheets (not embedded in Notion)
- NetAPP storage notes (SVM, NTFS/SMB storage issue documented)
- MacOS Packet Loss Testing section
  - MacOSx SMB Results `2f9aaa2b-5bb6-80bf-b05f-f4d3f1615009`
  - Ideas of culprits `300aaa2b-5bb6-8030-bef4-fd6fbc617dce`

#### Houston Rockets
**ID:** `27daaa2b-5bb6-80f4-ad56-dd9f3de18fdc`  
**Last updated:** 2026-02-10

- Diagrams in LucidChart / Google Sheets
- Switch Running Configs sub-page `27daaa2b-5bb6-80a1-82de-f7c260972a72`
- Zendesk Tickets `281aaa2b-5bb6-8027-bf07-c780ee4e5905`

---

### 3. Databases

#### Task Manager 💨 (Standalone, Top-Level)
**ID:** `643baf20-f3e1-417f-8ba9-1a78feeb0121`  
**Data Source:** `collection://eb6920f2-bb99-427a-8257-f7a8863bd89e`

Primary cross-project task DB. Schema:

| Property | Type | Options |
|---|---|---|
| Task | title | — |
| Status | status | Todo / Doing / Done |
| Priority | select | Low / Medium / High / Urgent |
| Category | select | Networking / Software / Hardware / Control Plane / Personal |
| Project | select | NAB 2026, HLSR, Texans, In Touch Ministries, Allstate, Koby's Need-To-Do, Cinesys Networking, CInesys LLC. |
| Due | date | datetime |
| Notes | text | — |
| Place | place | — |
| Attachments | file | — |

Views: Dashboard (charts), By Customer (board/project), By Category (board), Master List (table, sorted by due), Calendar

#### Tasks Tracker — HLSR (Inline in HLSR page)
**ID:** `28faaa2b-5bb6-8037-a23c-f5cad65dbd9c`  
**Data Source:** `collection://28faaa2b-5bb6-80d9-9dbf-000b932c8c42`

| Property | Type | Options |
|---|---|---|
| Task name | title | — |
| Need to do | status | Not started / Ordered / In progress / Solved / Done |
| Assignee | person | — |
| Priority | select | Urgent / High / Medium / Low |
| Priority 2 | select | P0 / P1 / P2 |
| Task type | multi-select | LAB, L4 Config, Ordering, Studio, Scoreboard, Migration, StudioDist Migration, Quantum |
| Due Date | date | — |
| Attach file | file | — |
| Updated at | last_edited_time | auto |

Views: All Tasks (table), By Status (board), My Tasks (table, filtered to me), Calendar, Dashboard (charts by task type)

#### Tasks Tracker — 49ers (Inline in 49ers page)
**ID:** `2f7aaa2b-5bb6-811e-8816-cee1c0bd999e`  
**Data Source:** `collection://2f7aaa2b-5bb6-81c9-87bd-000bb533d39d`  
Same schema as HLSR Tasks Tracker.

#### Tasks Tracker — Rockets (Inline in Rockets page)
**ID:** `7240dbf6-0d58-4818-97b1-1ed962c63966`  
**Data Source:** `collection://f027c237-1bdc-4b2f-82fb-ce4ab32df5e9`  
Same schema as HLSR Tasks Tracker.

#### My Tasks (Top-Level, Notion Native)
**ID:** `20522c82-fa16-42c9-a3ad-681e2ad5f71c`

#### Cinesys Photos | HLSR Studio (Inline in HLSR)
**ID:** `28faaa2b-5bb6-805d-aee5-c2ae04ce4c6b`  
**Data Source:** `collection://28faaa2b-5bb6-8051-be58-000b09f06e6a`

---

### 4. Learning Page (Cinesys Networking LAB)
**ID:** `205aaa2b-5bb6-8045-8784-ebf7d9236e6a`

- Physical Lab Diagrams (Active / Inactive)
- EVE-NG Virtual Labs section
- Cisco CML Server
  - Big Picture Architecture `305aaa2b-5bb6-8000-8100-e707038f12f3`
- LAB Core Services – Design & Implementation `2f4aaa2b-5bb6-80e9-9f36-fd6d7b0094fb`
- Services Hosted Virtually section
- Networking sub-page `205aaa2b-5bb6-800c-b60d-c6b3af123b87`

---

### 5. Kalyn's Creator Journey (Personal Project)
**ID:** `2e2aaa2b-5bb6-801c-ab97-e7fed8f40470`

Planning infrastructure for a content creator named Kalyn:
- **Cameras:** DJI Pocket 3 (primary), DJI Action 4 (secondary) — est. $1,100–$1,400
- **Audio:** DJI Mic 2 dual wireless system — est. $390–$460
- **Lighting:** NEEWER FL100C + NEEWER RGB660 PRO kits — est. $658
- **Network/Storage:** 100G NAS, Samba server, Ubiquiti AP planned
- **Post-production workflow** in planning

---

### 6. Teamspace Home
**ID:** `1a7aaa2b-5bb6-80c2-8583-fa3d519cb704`

Notion-generated teamspace template. Contains team overview, weekly schedule, tools list. Koby listed as Team Lead. Mostly template content, not actively used.

---

### Structural Notes & Observations

1. **HLSR is the most developed and active client** — last updated 2026-03-26, deepest content
2. **IT Notebook needs reorganization** — Koby has self-noted this; several pages exist outside the Table of Content
3. **Three separate per-client Tasks Trackers + one global Task Manager** — slight DB fragmentation
4. **Texans** appear as a project in Task Manager but have no dedicated hub page yet (unlike HLSR, 49ers, Rockets)
5. **NAB 2026 and In Touch Ministries** also tracked as projects in Task Manager without dedicated hub pages
6. **Diagrams live outside Notion** — heavy reliance on LucidChart (topology) and Google Sheets (IP lists, port diagrams), especially for 49ers and Rockets. HLSR has more content directly in Notion.
7. **GitLab integration** used for switch config backups (HLSR only so far)

---

## History

### 2026-03-26 — Agent initialized + first workspace scan
- `Notion-Manager.md` created on branch `claude/notion-manager-mK3pX`
- Agent registered in `CLAUDE.md` and SessionStart hook
- Full workspace scan completed via Notion MCP tools
- Topology section populated with all root-level pages, databases, schemas, and structural observations
- Workspace has 1 user (Koby Kubecka), 1 teamspace, ~5 root areas, 3 client hubs, 5 tracked databases
