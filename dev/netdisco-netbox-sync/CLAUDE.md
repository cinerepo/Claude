# CLAUDE.md — netdisco-netbox-sync

Discovery-driven CMDB pipeline: **Netdisco** (observed network state) → **Diode** (NetBox's ingestion gRPC service) → **NetBox** (source of truth). This is a reconciliation engine, not a raw importer — it classifies, stages, and selectively promotes assets rather than blindly mirroring everything Netdisco sees.

Read this file fully before touching code here. It exists so you don't have to re-derive the architecture, field mappings, or known gotchas from scratch every session.

## Infrastructure

| Service | Address | Notes |
|---|---|---|
| Netdisco | `http://10.1.88.114:5000` | v2.61.x, `no_auth: true` (NETDISCO_USER commented out in `.env` → login is skipped) |
| NetBox | `http://10.1.88.114:8000` | v4.5.10-Docker, admin/password |
| Diode | `grpc://10.1.88.114:8080/diode` | v1.11.0, `client_id=diode-ingest`, secret in `.env` |

All three run as Docker containers on a CineLAB Mac Pro server at `10.1.88.114`. Sync scripts run from Koby's MacBook, which has L2 access to the same network — **this means live `curl`/script runs against Netdisco only work from a machine on that LAN.**

Env vars are all in `config.py` / `.env` (see `.env.example` for the non-secret ones): `NETDISCO_URL`, `NETDISCO_USER`, `NETDISCO_PASS`, `DIODE_TARGET`, `DIODE_CLIENT_ID`, `DIODE_CLIENT_SECRET`, `DEFAULT_SITE`, `DEFAULT_ROLE`, `RULES_FILE`, `STAGING_DB`, `CONSUMER_VENDORS_FILE`, `MIN_DAYS_STABLE` (7), `STALE_DAYS` (30), `NOTIFY_DAYS` (90), `DECOMMISSION_DAYS` (180).

## The #1 debugging gotcha: two-stage staleness

**Before assuming any "NetBox data looks wrong" report is a code bug, check this first.** NetBox only reflects the last time `sync.py` ran. `sync.py` only reflects the last time Netdisco itself polled the device over SNMP. A config change on a switch has to clear *both* hops before NetBox is accurate — refreshing the NetBox page, or even refreshing the Netdisco page, does **not** trigger a re-poll.

Diagnostic order when the user reports incomplete/wrong data in NetBox:
1. Query Netdisco's own object endpoint directly, bypassing the sync entirely:
   ```
   curl -s "http://10.1.88.114:5000/api/v1/object/device/<ip>/<endpoint>" -H "Accept: application/json" | jq
   ```
   (`<endpoint>` = `ports`, `port_vlans`, `device_ips`, `vlans`, `nodes` — see field mappings below.) Check the `last_discover` timestamp in the response.
2. If Netdisco itself is missing/stale, the fix is a Netdisco-side rediscover of that device — not a code change.
3. If Netdisco has the right data but NetBox doesn't, re-run `sync.py` and check again before concluding it's a bug.
4. Only after both of those check out clean should you suspect `transformer.py`/`netdisco_client.py` logic. When in doubt, reproduce live: run the actual client + transformer functions against real Netdisco data in a `.venv/bin/python -c "..."` one-liner rather than reading code and guessing — this project's Netdisco instance is reachable from the dev machine, so there's rarely a reason not to verify against live data directly.

Note: `/api/v1/report/...` endpoints (report-style, e.g. `deviceinventory`, `ipinventory`) return **CSV without an `Accept: application/json` header** and JSON with it — always send that header. `/api/v1/object/...` endpoints (per-device object data) return JSON either way in practice, but send it anyway for consistency.

## Pipeline 1: Infrastructure Sync (`sync.py`)

Pulls SNMP-managed network devices from Netdisco → transforms → pushes to NetBox via Diode. Run with:
```
.venv/bin/python sync.py
```
No flags — it fetches `get_all_devices()` from Netdisco's `deviceinventory` report and iterates all of them. Currently syncing:
- **LabNet-Core-A** (`10.1.20.1`) — Cisco C9300 stack (IOS-XE), 93 interfaces, VLANs, SVIs
- **LabNet-Firewall-A** (`10.1.3.1`) — Fortinet FortiGate-100F, 39 interfaces
- **NVMe_Rack_Nexus** (`10.1.30.54`) — Cisco Nexus, 59 interfaces

### Data flow per device
`sync.py` calls, per device, in this order: `get_ports()`, `get_device_ips()`, `get_port_vlans()`, `get_vlans()`, `get_nodes()` — then `transformer.device_to_entities()` turns all of that into a flat list of Diode `Entity` objects, which get pushed in one `diode.ingest(entities=...)` call per device.

### Field mapping gotchas (`netdisco_client.py` / `models.py` / `transformer.py`)
- **`port.name` vs `port.descr` are swapped from what you'd guess.** `port.name` = ifAlias, the short interface label like `Te1/0/1`. `port.descr` = the long/canonical interface name like `TenGigabitEthernet1/0/1`. Neither of these is the NetBox `Interface.name` — that comes from `port.port` (Netdisco's canonical ifName key, e.g. `TenGigabitEthernet1/0/1`, used to join across all the other per-port endpoints).
- **VLAN mode (`access` vs `tagged`)** is derived from `port_vlans`, *not* from the base `/ports` endpoint's `pvid` field alone. Logic in `transformer.py`: if any `port_vlans` row for that port has `egress_tag == 1`, mode is `"tagged"` and those VLANs become `tagged_vlans`; the port's `pvid` (from `/ports`, native/untagged VLAN) becomes `untagged_vlan` regardless. If no `egress_tag=1` rows exist, mode falls back to `"access"` using `pvid`. **This logic is verified correct as of 2026-07-07** (ran live against LabNet-Core-A Te1/0/1, trunk with native VLAN 1 + tagged 21/22, resolved correctly) — don't re-litigate it without new evidence; look for two-stage staleness first (above).
- `device_ips` endpoint replaces the old `/addresses` endpoint (404s now) — use it for SVI IPs and prefix derivation.
- Legacy Cisco internal VLANs `1002-1005` are hardcoded-skipped everywhere (`_SKIP_VLANS` in `transformer.py`) — never meaningful in NetBox.
- `NetdiscoPort`/`NetdiscoPortVlan`/etc. models in `models.py` only require `ip`+`port` (or similar minimal keys) — almost everything else is `Optional`, so silent pydantic-validation drops are rare. If a row fails to parse, `netdisco_client.py` prints `WARN: could not parse <thing> on <ip>: <e>` to stdout and skips just that row — check for these if counts look short.
- `Interface.mode` must be set (`access`/`tagged`) before NetBox will accept `untagged_vlan` on that interface — an unset mode with an untagged_vlan reference gets rejected.

### Feature: connected-node MAC enrichment (added 2026-07-07)
`get_nodes()` (Netdisco's MAC-table / end-host data) is pulled per device and turned into **secondary** `MACAddress` Diode entities — `assigned_object_interface` pointing at the switch port, but *not* `primary_mac_address` (that stays the port's own MAC, set directly on the `Interface` entity). `description` = node's hostname or IP; `comments` = `vendor`/`ip`/`last_seen` packed as a string.

**Restricted to access-mode, non-uplink ports only** (`transformer.py`, `access_ports` set built during the interface loop, checked before emitting node entities). Trunk/uplink ports see every downstream MAC ever routed through them — attaching those would dump hundreds of irrelevant MACs onto one interface.

**Decision: NetBox's "Link Peers" column (Cable-based) was explicitly rejected for this data**, and should not be revisited without a real architecture change. Link Peers only reflects a `Cable` object, which is a strict 1:1 physical link between two real `Device`+`Interface` terminations (verified via Diode SDK's `Cable`/`CableTermination` field list — `a_terminations`/`b_terminations` require `GenericObject` refs to real terminations). Netdisco node data is many-MACs-per-port over time (different laptops plugged into the same jack over weeks) — structurally incompatible with a 1:1 cable. Modeling every learned MAC as a full `Device`+`Interface`+`Cable` was also rejected earlier for the same reason `discover.py` doesn't auto-promote everything: it would flood NetBox with transient device churn. `MACAddress` (many-to-one, non-primary) is the correct and only mechanism for this data.

## Pipeline 2: Host Discovery (`discover.py`)

Separate pipeline: pulls MAC-table nodes from Netdisco → stages in local SQLite (`data/observed_assets.db`) → classifies by VLAN intent + stability → lets you selectively promote to NetBox as Device objects. This is for *end hosts* (servers, workstations found via ARP/MAC table), distinct from Pipeline 1's *infrastructure devices* (switches/firewalls found via `deviceinventory`).

### CLI
```
python discover.py run                                    # pull + classify (auto-promotes infra VLANs)
python discover.py status                                 # summary counts by classification
python discover.py list-all                                # every asset, all classifications
python discover.py list-candidates                        # stable enough for review
python discover.py list-managed                            # already in NetBox
python discover.py list-unclassified                       # not stable yet
python discover.py list-stale                              # managed but gone quiet (STALE_DAYS)
python discover.py list-ignored                             # permanently ignored
python discover.py list-expiring                            # unclassified/candidate counting down to auto-prune
python discover.py promote <mac|ip> [--name X] [--role X] [--site X] [--vendor X]
python discover.py ignore <mac|ip> [--reason X]
python discover.py unpromote <mac|ip> [--reason X]         # resets managed → candidate
```

### Classification states
| State | Meaning |
|---|---|
| `unclassified` | Seen but not yet stable enough (`MIN_DAYS_STABLE`, default 7 days) |
| `ignore` | Permanently excluded — consumer device or `ignore`-intent VLAN. Two flavors: **auto-ignore** (no `ignore_reason`, re-evaluated when the vendor blocklist changes) vs **human-ignore** (has `ignore_reason`, permanent, never reclassified) |
| `candidate` | Stable, needs manual `promote` (lab/corporate VLAN intent) |
| `managed` | Pushed to NetBox — auto for `infrastructure`-intent VLANs, manual via `promote` for others. Human-locked: re-running `run` only updates timestamps, never reclassifies |
| `promotion_failed` | Infra-VLAN auto-promote attempt failed — retried on next `run` |
| `stale` | Was `managed`, not seen in `STALE_DAYS` (default 30) days |

### Auto-prune for unclassified/candidate noise (added 2026-07-07)

`cmd_run()` ends with `db.prune_expired(config.prune_days)` (`PRUNE_DAYS` env var, default **2** days). Any row still `unclassified` or `candidate` whose `last_seen` hasn't been refreshed in that window gets hard-deleted from the staging DB, with each deleted row's full record (mac/ip/vlan/switch/port/vendor/last_seen) printed to stdout as it happens.

**Deliberately scoped to only `unclassified`/`candidate`.** `managed`, `ignore` (human or auto), and `promotion_failed` are never touched by this — those need an explicit human decision (`unpromote`/`ignore`) or are already being retried by the classifier. This exists specifically for transient noise: a MAC that only showed up because of a temporary bridged/test cable (e.g. patching an access port into the wrong VLAN for a quick test) shouldn't linger in the staging DB forever once unplugged.

**Why this is safe and won't eat real devices on the first run after a long gap:** pruning happens *after* the same run's node-upsert loop, not before. Anything still actually reachable gets its `last_seen` bumped to now during that same `run` and is therefore not prune-eligible — only genuinely-vanished MACs (not returned by Netdisco's `get_nodes()` at all during that run) get deleted. That said, if `discover.py run` hasn't been executed in a while, expect a real cleanup pass the next time it runs — anything that's been sitting stale since the last run (not necessarily gone from the network, just not re-scanned) will look "DUE NOW" until that run refreshes it. Check `python discover.py list-expiring` (read-only) anytime to preview what's about to go before committing to a `run`.

`days_until_prune(asset, prune_days)` in `staging.py` is the shared countdown calculation — used by `list-candidates`, `list-unclassified`, `list-all`, and `list-expiring` so the "ticking timer" is visible everywhere, not just in one command. Returns `None` for non-prunable classifications, `<= 0` meaning "will be deleted on the next run."

**Forward-looking note:** `prune_expired()` returns the full list of deleted `ObservedAsset` records specifically so a future notifier (SMTP alert on new/removed devices — mentioned as a near-term goal) has ready-made data to consume without re-querying anything. Same reasoning applies to `cmd_run()`'s existing `counts["new"]` tracking for newly-seen devices — when building that notifier, hook in at the end of `cmd_run()` where `pruned` and the new-asset data are already assembled, rather than re-deriving state from the DB.

### VLAN policy (`rules.yaml` → `vlan_policy`)
| VLAN | Intent | Notes |
|---|---|---|
| 1 | ignore | Default VLAN — noise |
| 8 | lab | HLSR Test VLAN |
| 20 | lab | Lab House VLAN |
| 21 | lab | VXLAN test |
| 30 | infrastructure | RDMA / NVMe-oF storage network — auto-promote |
| 40 | infrastructure | Services — Proxmox, AD, DNS, Syslog — auto-promote |
| 78 | infrastructure | Management / out-of-band |
| 88 | corporate | Cinesys Corporate — no SVI, MAC-only, candidates held for manual review |
| 172 | infrastructure | RDMA NVMe-oF VLAN |

Unknown VLANs stay `unclassified` until stable, then become `candidate` automatically (not auto-ignored). `gateway_suffixes` (`.1`, `.2`) are treated as existing device SVIs, never promoted as a second device record.

### IP enrichment
`ip_inventory_subnets` in `rules.yaml` drives Netdisco's `ipinventory` report lookups (requires a `subnet` param, no wildcard). Currently configured: `10.1.0.0/18` (CineLAB lab range), `172.18.8.0/24` (HLSR Studio test lab). Cinesys Corporate (`10.1.64.0/18`) is commented out pending FortiGate ARP access. **Use /18 or /24 — avoid /8, Netdisco may time out or return excessive historical records.**

### OUI vendor lookup
`mac-vendor-lookup` package, local cache at `.venv/cache/mac-vendors.txt`. Refresh with `MacLookup().update_vendors()`. `consumer_oui_vendors.txt` is a blocklist to auto-ignore consumer gear (phones, personal laptops) — Apple is deliberately *not* in this list, since Macs here are managed infra, not personal consumer devices.

### DeviceType collision
`classifier.py`'s `_default_model()` assigns vendor-specific model names ("Proxmox VM", "Mellanox NIC", "Intel Device", etc.) instead of a generic "Unknown" — otherwise every unrecognized device collapses onto the same NetBox DeviceType slug.

## Key Files

```
sync.py                   Infrastructure sync entry point (Pipeline 1)
discover.py                Host discovery CLI (Pipeline 2)
config.py                  All env vars with defaults — start here for connection info
models.py                  Pydantic models for every Netdisco API response shape
netdisco_client.py          HTTP client — devices/ports/device_ips/port_vlans/nodes/vlans/ip_inventory
transformer.py              Netdisco → Diode entity mapping (Pipeline 1 only)
staging.py                  SQLite wrapper for observed_assets.db
classifier.py               VLAN-intent classification engine (Pipeline 2)
rules.yaml                  VLAN policy + gateway suffixes + ip_inventory_subnets
consumer_oui_vendors.txt    Vendor blocklist for auto-ignore
INSTALLATION_GUIDE.txt      Server deployment guide
data/observed_assets.db     Staging database (auto-created, Pipeline 2 only)
```

## Design decisions worth knowing before you propose changes

- **Hostname enrichment is an infrastructure decision, not a code fix.** Proxmox VMs (OUI `bc:24:11`) promote to NetBox named by IP/MAC because Netdisco has no PTR data for that range. A per-vendor API enrichment (Proxmox API lookup by MAC) was explicitly considered and rejected in favor of standing up DNS+DHCP with dynamic registration — because that fixes it for *all* future hosts, not just one hypervisor. Don't propose per-vendor naming hacks in `discover.py`; revisit only once real PTR data exists in Netdisco.
- **Link Peers rejected for connected-node data** — see Pipeline 1 section above. Don't revisit without a real architecture change (e.g., deciding to model end hosts as real Devices, which has its own rejected-for-churn history).
- **Diode ingestion is not atomically ordered within a batch.** A prior bug (`_build_entities()` in `discover.py`, fixed 2026-07-06) assumed entities in one `ingest()` call resolve FKs in order — they don't. Any entity referencing another (e.g., `IPAddress.assigned_object_interface`) must pass a **fully-specified stub** (device with role/site/device_type, interface with `type` set) or the reference silently fails to resolve / 400s. Always build a complete `device_stub`/`iface_stub` once and reuse it, matching the pattern already in `transformer.py`.
- **Original reference repos** at `/Users/kobykub/Documents/claude/local-claude/data/netbox-plugin-netdisco/` (`openapi-client-netdisco`, `netbox-plugin-netdisco`) were evaluated and explicitly **not used** — both abandoned since Dec 2021. Only consulted as field-mapping reference (`swagger.json`, `defaults.py`). Don't suggest reviving them without re-justifying against a from-scratch client.

## Pending / Next

- VLAN 88 corporate candidates (~22 devices, no SVI/IPs) awaiting manual review
- Scheduled cron for `sync.py` and `discover.py run` (not yet set up — both are still manual)
- Multi-site expansion (NRG Park) — per-site `rules.yaml` via `RULES_FILE` env var, not yet built
- Re-test the 14 auto-promoted Pipeline-2 assets against the 2026-07-06 `primary_ip4` fix end-to-end (they were reset to `candidate` via `unpromote` for retesting — check `discover.py status` for current counts before assuming this is done)
