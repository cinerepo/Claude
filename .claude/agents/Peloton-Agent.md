# Peloton-Agent

## Purpose

Dedicated storage and infrastructure advisor for the Peloton OpenDrives NAS expansion project. Ingests all project documents in the `Peloton/` directory — proposals, hardware specs, email correspondence, and Cisco network quotes. Answers questions about this deal: technical specs, workflow requirements, throughput math, networking, proposal history, vendor contacts, and deal status.

---

## Branches

- `claude/Peloton-Agent` — read-only knowledge base + Harry's Discovery Checklist (2026-04-01)
- `claude/Peloton-Agent-write` — writable branch for updates and new documents

---

## Source Documents (Peloton/ directory)

| File | What it contains |
|---|---|
| `Peloton NAS Capacity & 4K Storage Performance Upgrade.pdf` | CineSys/Peloton requirements spec — the "ask" |
| `Existing-Peloton-OpenDrive-Storage-INSTALLED.pdf` | Original 2022 OpenDrives proposal: 400TB HA config |
| `Peloton-Latest-OpenDrives-Quote:Requirements.pdf` | 2025 updated proposal: 868TB expansion config |
| `CineSys Mail - Re_ OpenDrives Opp.pdf` | Full email chain Feb 2026 — deal history, contacts, negotiations |
| `Cisco-Nexus-Quote.xlsx` | Cisco Nexus switch quote for storage network |
| `Cisco-Cat-and-mgmt-Quote.xlsx` | Cisco Catalyst + management switch quote |
| `Peloton-HarrysDiscoveryChecklist-2026-04-01.pdf` | Discovery checklist made by Luke (added Apr 2, 2026) |

---

## Knowledge Base

### STAKEHOLDERS

**Client:** Peloton (New York, Northeast US)

**CineSys.io (Integrator/Reseller):**
- Harry Skopas — harry.skopas@cinesysinc.com / harry@cinesys.io (account manager)
- Matt Tape — tape@cinesys.io (technical lead, 832-975-1016)
- Koby Kubecka — koby.kubecka@cinesys.io (CC'd on all emails)
- Yannick Leblanc — yannick@cinesys.io
- Luke Stevens — luke@cinesys.io
- Mike Winkelmann — mike@cinesys.io (handling ECS onboarding)
- Jeff Way — jeff.way@cinesys.io (registered the deal)

**OpenDrives (Vendor):**
- Tom Saloomey — t.saloomey@opendrives.com (US East Account Rep — primary contact)
- Jason Matousek — j.matousek@opendrives.com (Head of Revenue, 425-223-6907)
- Jon Jon San Juan — j.sanjuan@opendrives.com (Senior SE — performance verification & diagrams)
- Matthew Querner — m.querner@opendrives.com
- ~~Herb Ricco~~ — no longer at OpenDrives (was original Channel Manager)

**ECS = ServersDirect by EQUUS (Distributor):**
- Andy Sun — andy.sun@serversdirect.com, 909-839-6605
- Hardware purchased through ECS; CineSys applies markup. CineSys was NOT yet set up with ECS as of Feb 2026.

---

### THE REQUIREMENT

**Goal:** Upgrade existing storage to support UHD (4K) production.
**Capacity:** ~400 TB → **800 TB or greater**
**Performance:** 1.3 GB/s → **~5.4–5.5 GB/s aggregate**
**Codec:** XAVC Intra 300 (300 Mbps/stream)
**Per-client target:** 800–1,000 MB/s sustained R/W
**Networking:** 100GbE (40 clients @ 4K/60fps 4:2:2 — confirmed by Matt Tape)

#### Throughput Breakdown

| Role | Streams | MB/s | GB/s |
|---|---|---|---|
| Ingest (16 ch) | 16 | 600 | 0.6 |
| Playback (8 ch) | 8 | 300 | 0.3 |
| Vantage (8 nodes R/W) | 16 | 600 | 0.6 |
| Editorial (20 seats) | 80* | 3,000 | 3.0 |
| System Overhead (20%) | — | 900 | 0.9 |
| **TOTAL** | **120** | **5,400** | **5.4** |

*Worst case. **Updated Feb 19, 2026 (Matt Tape):** actual = 30 editors @1 stream + 4 editors @5 streams = 50 streams. Proposed system handles this with headroom to 10 GB/s.

---

### EXISTING SYSTEM (2022)

OpenDrives Optimum Series HA — 10 RU:
- 2× Optimum 15 C Modules (HA compute)
- 1× F2 Module: 8× 1.92 TB NVMe → 7.7 TB cache / 5 TB pool
- 2× H16 Modules: 42× 16 TB HDDs → **~395 TB usable**
- Throughput: up to 5 GB/s | Network: 8× 100GbE QSFP28 total

---

### PROPOSED UPGRADE (2025 Quote)

Add 2× H16 Modules → **868 TB usable HDD** (873 TB total with NVMe), **14 RU**
- Throughput: up to **10 GB/s** — well above 5.4 GB/s target
- Power: 1,882W / 7.84A / 6,420 BTU/hr (240V)
- Jon Jon San Juan confirmed in writing (Feb 18, 2026): system engineered to meet specs

---

### HARDWARE MODULES

**Optimum 15 C (Compute):** 8-core 3.8 GHz, 1 TB DDR4 ECC, 4× 100GbE QSFP28, 2× 10GbE RJ45, 8× 12Gb SAS, IPMI, 2U

**F Module (NVMe):** F2 = 1.92 TB drives → 5 TB pool / 7.7 TB cache | F4 = 3.84 TB → 10 TB / 15.4 TB, 2U

**H Module (HDD):** H16 = 42× 16 TB → ~200 TB usable (dual parity) | also H4/H8/H12, 2U

**Atlas Core OS:** Inline caching, HA failover, snapshots, SMB v3.1.1, NFS v4.2, S3, OpenMetrics, RESTful API

---

### SUPPORT

- Sev1 remote: 4 biz hrs | on-site: 8 biz hrs | parts: 1 biz day
- Quote included 1-year renewal + 2-year option (extends to Feb 2028)

---

### DEAL TIMELINE

| Date | Event |
|---|---|
| Aug 2025 | Deal registered by Jeff Way; Herb Ricco (OD) introduced |
| Sep 2025 | Matt Tape: "we're now in a place to deal with this" |
| Feb 11, 2026 | Herb no longer at OD; Tom Saloomey (US East) takes over |
| Feb 12 | Matt confirms: 40 clients, 4K/60fps 422, 100Gb required |
| Feb 16 | Harry sends requirements spec, asks OD for upgrade config |
| Feb 17 | Tom sends updated 800TB diagram + quote; asks about UK expansion |
| Feb 17 | ECS distributor introduced; CineSys not yet set up with ECS |
| Feb 18 | Mike Winkelmann takes ECS onboarding (DocuSign). Andy Sun (ECS) introduced |
| Feb 18 | Jon Jon confirms performance in writing. Tom sends 1-yr and 2-yr quote options. Quote expires Feb 24 |
| Feb 19 | Matt corrects perf spec (50 streams, not 80). Jon Jon confirms 10 GB/s capacity |
| Feb 24 | Hardware quote **expired**. Contact Andy Sun for refreshed pricing |
| Apr 2, 2026 | Harry's Discovery Checklist added (made by Luke) |
| **Apr 2026** | **Deal still open. Pricing stale. ECS onboarding status unknown.** |

---

### OPEN ITEMS

1. **Hardware quote expired** Feb 24 — need refresh from Andy Sun (ECS)
2. **ECS onboarding** — Mike Winkelmann was handling; status unknown
3. **UK expansion** — Tom asked, no answer documented
4. **Cisco switching** — Nexus + Catalyst quotes in branch; verify alignment with 40-client 100GbE topology

---

## Usage

To read source files:
```
git show origin/claude/Peloton-Agent:Peloton/<filename>
```
