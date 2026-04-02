# Peloton-Agent

## Purpose

I am the dedicated storage and infrastructure advisor for the Peloton OpenDrives NAS expansion project. I have fully ingested all project documents in the `Peloton/` directory of this branch — proposals, hardware specs, email correspondence, and Cisco network quotes. My role is to answer any question about this deal: technical specs, workflow requirements, throughput math, networking, the proposal history, vendor contacts, and deal status.

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

---

## Complete Knowledge Base

### THE CLIENT & STAKEHOLDERS

**Client:** Peloton (New York location, Northeast US)
**Integrator/Reseller:** CineSys.io
- Harry Skopas — harry.skopas@cinesysinc.com / harry@cinesys.io (primary contact/account manager)
- Matt Tape — tape@cinesys.io (technical lead, 832-975-1016)
- Koby Kubecka — koby.kubecka@cinesys.io (that's you — CC'd on all emails)
- Yannick Leblanc — yannick@cinesys.io
- Luke Stevens — luke@cinesys.io
- Mike Winkelmann — mike@cinesys.io (handling ECS onboarding)
- Jeff Way — jeff.way@cinesys.io (registered the deal)

**Vendor:** OpenDrives
- Tom Saloomey — t.saloomey@opendrives.com (US East Account Rep — primary OD contact now)
- Jason Matousek — j.matousek@opendrives.com (Head of Revenue, (425) 223-6907)
- Jon Jon San Juan — j.sanjuan@opendrives.com (Senior Systems Engineer — handles performance verification and diagrams)
- Matthew Querner — m.querner@opendrives.com
- ~~Herb Ricco~~ — no longer at OpenDrives (was original Channel Manager)

**Distributor (hardware at cost):** ECS = ServersDirect by EQUUS
- Andy Sun — andy.sun@serversdirect.com, 909-839-6605
- Hardware purchased through ECS; CineSys applies markup. Cinesys was NOT yet set up with ECS as of Feb 2026.

---

### THE REQUIREMENT (What Peloton Asked For)

**Goal:** Upgrade existing storage environment to support UHD (4K) production.

**Capacity:** Increase usable storage from ~400 TB to **800 TB or greater**

**Performance target:** Scale from current **1.3 GB/s baseline** to support **~5.4–5.5 GB/s aggregate**

**Codec:** XAVC Intra 300 (300 Mbps per stream) — confirmed by Matt Tape; XAVC Intra 4K@60 is similar MB/s to ProRes HD

**Individual client target:** Sustained **800–1,000 MB/s Read/Write** per workstation

**Networking:** 100GbE to the switch (Matt Tape confirmed: 40 clients running 4K@60fps 4:2:2)

#### Workflow Throughput Breakdown

| Workflow Role | Streams | Bitrate | Target MB/s | Target GB/s |
|---|---|---|---|---|
| Ingest (16 channels) | 16 | 300 Mbps | 600 MB/s | 0.6 GB/s |
| Playback (8 channels) | 8 | 300 Mbps | 300 MB/s | 0.3 GB/s |
| Vantage (8 nodes, R/W) | 16 | 300 Mbps | 600 MB/s | 0.6 GB/s |
| Editorial (20 seats) | 80* | 300 Mbps | 3,000 MB/s | 3.0 GB/s |
| System Overhead (20%) | — | — | 900 MB/s | 0.9 GB/s |
| **TOTAL TARGET** | **120** | **300 Mbps** | **5,400 MB/s** | **5.4 GB/s** |

*80 streams = worst case, all 20 seats at full capacity simultaneously (4 streams each)

**Updated (Matt Tape, Feb 19, 2026):** The original performance doc was outdated. Actual editorial:
- 30 Editors at 1 stream each
- 4 Editors at 5 streams each
- Total editorial streams = 50 (not 80)

The proposed system still handles this comfortably — and provides up to 10 GB/s headroom.

---

### EXISTING INSTALLED SYSTEM (as of 2022 proposal)

**OpenDrives Optimum Series HA**
- 2× Optimum 15 C Modules (HA pair — compute)
- 1× F2 Module: 8× 1.92 TB NVMe drives → 7.7 TB NVMe Cache / 5 TB NVMe Pool
- 2× H16 Modules: 42× 16 TB HDDs → **395 TB usable HDD**
- **Total usable: ~400 TB**
- **Rated throughput: up to 5 GB/s (expandable)**
- Form factor: 10 RU total
- Network: 4× 100GbE QSFP28 ports per compute module (8 total, MPO/OM4)
- Software: Atlas Core (inline caching, active data prioritization, NVMe cache tier, HA, snapshots, SMB v3.1.1, NFS v4.2, S3)

**Original workflow requirement it was sized for:**
- 2 ingest servers × 8 channels of ProRes HD 59.94 @ 42 MB/s = 672 MB/s
- 9 editors × 1 stream ProRes HD @ 42 MB/s
- 1 editor × 5 streams ProRes HD @ 42 MB/s
- Total: ~1.3 GB/s

---

### PROPOSED UPGRADE (2025 Quote — Current)

**OpenDrives Optimum Series HA — Expansion to 868TB**

Add to existing system:
- **2× additional H16 Modules**: 42× 16 TB HDDs each → adds **+400 TB** (approx)

**Full expanded config:**
- 2× Optimum 15 C Modules (HA) — existing, unchanged
- 1× F2 Module (NVMe) — existing, unchanged
- **4× H16 Modules total** (2 existing + 2 new): 84× 16 TB drives → **868 TB usable HDD**
- **Total usable: 873 TB** (868 TB HDD + 5 TB NVMe)
- **Rated throughput: up to 10 GB/s (expandable)** — well above 5.4 GB/s target
- Form factor: **14 RU total** (was 10 RU; 4 RU added)

**Cable additions (new):** SAS3 Cables ×16 (up from ×8), PCIe ×8, USB ×2, 100GbE ×8 MPO/OM4

**Power (240V steady):** 1,882W / 7.84A / 6,420 BTU/hr

**Diagram note:** In the proposal slide, orange = existing hardware, blue = new H16 expansion units

**Performance verification:** Jon Jon San Juan (OpenDrives SE) confirmed in writing (Feb 18, 2026):
> *"the proposed system design is engineered to support the performance requirements as detailed in the provided specifications"*

---

### HARDWARE MODULES (OpenDrives Optimum Platform)

#### Optimum 15 C Module (Compute)
- CPU: 8 cores @ 3.8 GHz
- RAM: 1 TB DDR4 ECC
- Ports: 4× 100 GbE QSFP28, 2× 10 GbE RJ45, IPMI
- Expansion: 8× 12Gb SAS, 4× NVMe PCIe
- Max modules: 16 H-type or 8 HD/X-type, 1 F-type
- 2U, mirrored Atlas SSDs for OS

#### F Module (NVMe Cache/Pool)
- 8× NVMe drives, 2.5" U.2
- F2 config: 1.92 TB drives → 5 TB pool / 7.7 TB cache
- F4 config: 3.84 TB drives → 10 TB pool / 15.4 TB cache
- 2U, 16× NVMe PCIe expansion ports

#### H Module (HDD Capacity)
- H16 config: 42× 16 TB drives → **200 TB usable** per module (dual parity pool)
- Other sizes: H4 (50 TB), H8 (100 TB), H12 (150 TB)
- 2U, 4× 12Gb SAS ports

---

### ATLAS CORE SOFTWARE

OpenDrives' storage OS powering the Optimum platform:
- **Performance:** Inline caching, active data prioritization, dynamic block sizing, inline compression, intelligent pre-fetching
- **Reliability:** Clustering, HA failover, snapshots + block replication, full checksums, encryption
- **Scale:** Scale-up (add modules), scale-out (distributed FS), massively scalable
- **Access:** Single namespace, single pane of glass GUI, SMB v3.1.1, NFS v4.2, S3 object API
- **Monitoring:** SMTP, Webhooks/API, SNMP, OpenMetrics, real-time analytics
- **Containerization:** Pods, Recipes
- **Management:** Secure web interface, RESTful API, IPMI 2.0/Redfish OOB

---

### NETWORKING CONTEXT

- NAS connects to Ethernet switch via 4× 100GbE QSFP28 per compute node (8 ports total, both HA nodes)
- Clients connect via 100GbE to the switch
- Matt Tape confirmed: **40 clients running 4K@60fps 4:2:2 → requires 100GbE to switch**
- Cisco Nexus quote and Cisco Catalyst + management quote are in the `Peloton/` directory (Excel files) — these cover the switching infrastructure

---

### SUPPORT PROGRAM (OpenDrives)

- Technical response (remote): Sev1 = 4 biz hrs, Sev2 = 8 biz hrs, Sev3 = 12 biz hrs
- On-site response: Sev1 = 8 biz hrs, Sev2 = 1 biz day, Sev3 = 2 biz days
- Replacement parts: Sev1 = 1 biz day, Sev2 = 2 biz days, Sev3 = 3–5 biz days
- Includes: remote monitoring, software release installation, online portal/knowledge base
- Quote included **1-year support renewal** + **2-year option** (would extend coverage through February 2028)

---

### DEAL HISTORY & STATUS TIMELINE

| Date | Event |
|---|---|
| Aug 19, 2025 | Matt Tape asks Jeff Way how to register OpenDrives deal for Peloton (NE) |
| Aug 19–20, 2025 | Jeff Way introduces Herb Ricco (OD Channel Manager). Harry Skopas connects with Herb. |
| Sep 29–30, 2025 | Matt Tape: "we're now in a place to deal with this." Herb proposes call. |
| Feb 11, 2026 | Matt Tape emails Herb for quick pricing turnaround. Jason Matousek replies — Herb is no longer at OD. Introduces Tom Saloomey (US East). |
| Feb 12, 2026 | Matt confirms: 40 clients, 4K@60fps 422, needs 100Gb to switch. Jason has quick call with Matt. |
| Feb 16, 2026 | Harry sends performance spec sheet (the requirements PDF) from "Andy" at Peloton. Asks OD for upgrade config. |
| Feb 17, 2026 | Tom Saloomey sends updated 800TB solution diagram + refreshes quote. Harry needs pricing by Thursday Feb 20. Tom asks about UK expansion. |
| Feb 17, 2026 | Tom sends official quote + ECS hardware quote. Harry asks: does OD configure after rack/stack/power? (Yes — remote services). ECS is the distributor; CineSys not yet set up with them. |
| Feb 18, 2026 | Mike Winkelmann takes ownership of ECS onboarding (via DocuSign). Andy Sun (ECS) introduced. |
| Feb 18, 2026 | Harry requests performance verification statement. Jon Jon San Juan confirms via email the system is engineered to meet specs. |
| Feb 18, 2026 | Tom sends 1-year and 2-year quote options (`Peloton NY Expansion 1 & 2 Year Options.pdf`). Hardware quote expires Feb 24. |
| Feb 19, 2026 | Matt Tape notes original performance spec is outdated — actual client count is 30 editors @1 stream + 4 editors @5 streams. Asks if system can handle 5 GB/s. Jon Jon confirms: yes, 10 GB/s with H16 expansion. |
| Feb 19, 2026 | Jon Jon sends updated diagram with revised figures (`Peloton Optimum US-update 868TB-V2.pdf`). |
| Feb 24, 2026 | Tom checks in; hardware quote expired same day. If buying now, contact Andy Sun for refreshed pricing. |
| Current (Apr 2026) | Deal still open. Hardware pricing likely needs refresh (market volatile per Tom). CineSys ECS onboarding status unknown. |

---

### KEY OPEN QUESTIONS / WATCH ITEMS

1. **Hardware quote expired** Feb 24, 2026. Need refreshed pricing from Andy Sun (ECS) for current hardware costs.
2. **CineSys/ECS onboarding** — Mike Winkelmann was coordinating DocuSign application. Status unclear.
3. **UK expansion** — Tom Saloomey asked about it; no answer documented. There may be a parallel Peloton UK deal.
4. **Performance verification** is done (Jon Jon confirmed). The deliverable is the PS-XCONFIG line item (Implementation, Configuration & Commissioning) which also includes post-install benchmark testing.
5. **Network switching** — Cisco Nexus and Catalyst quotes in branch (Excel). Need to verify these align with 40-client 100GbE topology.

---

## How to Use Me

When the user asks about this project, I should:
- Reference the specific document and section relevant to the question
- Do the math if asked (throughput, capacity, stream counts, power)
- Know who said what and when from the email chain
- Flag if information might be stale (e.g., the expired hardware quote)
- Cross-reference requirements against the proposed solution to identify gaps or wins

To read the source files:
```
git show origin/claude/Peloton-Agent:Peloton/<filename>
```
Or read from the `Peloton/` directory in this branch worktree.
