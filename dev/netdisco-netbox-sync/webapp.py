"""
webapp.py — web UI over the discover/sync/lifecycle pipelines.

Deliberately a thin layer: every route calls straight into the same functions
the CLIs (discover.py/sync.py/lifecycle.py) already use (StagingDB, _promote_asset,
load_rules, NetBoxClient, ...) rather than re-deriving any logic here.

Runs in-cluster as the netdisco-netbox-sync-webui Deployment (see
playbooks/sync-tool.yml) - 1 replica only, the shared SQLite staging DB on the same
PVC the sync/discover/lifecycle CronJobs use is single-writer.

Run with:
    uvicorn webapp:app --host 0.0.0.0 --port 8090
"""
import asyncio
import secrets
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

import datetime
import os
import shutil
from urllib.parse import urlencode

import httpx
import yaml

from config import load_config
from classifier import load_rules
from staging import StagingDB
from netboxlabs.diode.sdk import DiodeClient
from netdisco_client import NetdiscoClient
import discover as discover_mod
import lifecycle as lifecycle_mod

config = load_config()

app = FastAPI(title="netdisco-netbox-sync")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
# Cache-busting query param for /static/* links in base.html - the browser has no
# Cache-Control header to go on for these (StaticFiles only sends ETag/Last-Modified), so a
# plain refresh can silently serve a stale cached CSS/JS file after an edit. A plain
# function, not a value computed once at import time - static files (CSS/JS) get edited
# without a server restart, so this needs to re-stat the directory on every request to
# actually reflect the newest edit, not just whatever mtime existed at startup.
def _static_version() -> str:
    return str(int(max(
        (os.path.getmtime(os.path.join("static", f)) for f in os.listdir("static")), default=0,
    )))


templates.env.globals["static_version"] = _static_version

_security = HTTPBasic()


def require_auth(credentials: HTTPBasicCredentials = Depends(_security)) -> str:
    """HTTP Basic Auth gate — applied per-route via Depends(), not global middleware,
    so every page/action explicitly opts in (and so FastAPI's own /docs, if ever
    enabled, wouldn't accidentally bypass it - explicit is safer than a middleware
    that's easy to forget to apply to a newly added route).

    WEBUI_USER/WEBUI_PASSWORD must both be set - refusing to silently run with no
    auth at all is deliberate, since this UI can promote devices and rewrite
    rules.yaml. secrets.compare_digest avoids a timing side-channel on the check.
    """
    if not config.webui_user or not config.webui_password:
        raise RuntimeError(
            "WEBUI_USER and WEBUI_PASSWORD must both be set in .env before "
            "starting webapp.py - see .env.example."
        )
    user_ok = secrets.compare_digest(credentials.username, config.webui_user)
    pass_ok = secrets.compare_digest(credentials.password, config.webui_password)
    if not (user_ok and pass_ok):
        raise StarletteHTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ---------------------------------------------------------------------------
# Run Now: subprocess runner shared by discover/sync/lifecycle "Run Now" buttons.
# In-memory only (no persistence across a restart) - fine for a single-operator
# local tool where a run either just happened or didn't.
# ---------------------------------------------------------------------------
_RUNS: dict[str, dict] = {}
_MAX_RUNS = 20  # oldest evicted once exceeded - nothing ever cleared this before,
                # meaning every run's full output sat in memory forever for the life of
                # the process. Fine for a dev session, not fine for a long-running pod.


async def _stream_subprocess(run_id: str, script: str, *args: str) -> None:
    run = _RUNS[run_id]
    proc = await asyncio.create_subprocess_exec(
        sys.executable, script, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(Path(__file__).parent),
    )
    run["proc"] = proc
    assert proc.stdout is not None
    async for line in proc.stdout:
        run["lines"].append(line.decode(errors="replace").rstrip("\n"))
    returncode = await proc.wait()
    run["done"] = True
    run["returncode"] = returncode
    run["lines"].append(f"\n[exit code {returncode}]")


def start_run(script: str, *args: str) -> str:
    run_id = uuid.uuid4().hex[:12]
    _RUNS[run_id] = {"script": script, "args": args, "lines": [], "done": False,
                      "returncode": None, "started": time.time(), "proc": None}
    if len(_RUNS) > _MAX_RUNS:
        oldest_id = min(_RUNS, key=lambda k: _RUNS[k]["started"])
        del _RUNS[oldest_id]
    asyncio.create_task(_stream_subprocess(run_id, script, *args))
    return run_id


def render_run_panel(request: Request, panel_id: str, run_endpoint: str,
                      run_button_label: str, run_id: Optional[str] = None):
    ctx = {
        "panel_id": panel_id, "run_endpoint": run_endpoint,
        "run_button_label": run_button_label, "run_id": run_id,
        "lines": [], "done": False, "returncode": None,
    }
    if run_id is not None:
        run = _RUNS.get(run_id)
        if run is not None:
            ctx["lines"] = run["lines"]
            ctx["done"] = run["done"]
            ctx["returncode"] = run["returncode"]
    return templates.TemplateResponse(request, "_run_panel.html", ctx)


@app.get("/runs/{run_id}/log")
def run_log(request: Request, run_id: str, run_endpoint: str, panel_id: str,
            label: str, user: str = Depends(require_auth)):
    return render_run_panel(request, panel_id, run_endpoint, label, run_id=run_id)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---------------------------------------------------------------------------
# Per-page docs ("how this works") - one static sub-page per main page,
# highlighting the same nav tab as their parent so they read as a sub-page of
# it rather than a separate section.
# ---------------------------------------------------------------------------

@app.get("/docs/discover", response_class=HTMLResponse)
def docs_discover(request: Request, user: str = Depends(require_auth)):
    return templates.TemplateResponse(request, "docs_discover.html", {
        "active": "discover", "config": config,
    })


@app.get("/docs/config", response_class=HTMLResponse)
def docs_config(request: Request, user: str = Depends(require_auth)):
    return templates.TemplateResponse(request, "docs_config.html", {
        "active": "config", "config": config,
    })


@app.get("/docs/lifecycle", response_class=HTMLResponse)
def docs_lifecycle(request: Request, user: str = Depends(require_auth)):
    return templates.TemplateResponse(request, "docs_lifecycle.html", {
        "active": "lifecycle", "config": config,
    })


# ---------------------------------------------------------------------------
# Discover (Pipeline 2) — filter table + promote/ignore/unpromote
# ---------------------------------------------------------------------------

_ACTIONABLE = ("candidate", "promotion_failed")


_ALL_CLASSIFICATIONS = ("managed", "candidate", "unclassified", "ignore", "promotion_failed", "stale", "archived")


@app.get("/", response_class=HTMLResponse)
def discover_page(request: Request,
                   classification: list[str] = Query(default=[]),
                   exclude: list[str] = Query(default=[]),
                   vlan: list[str] = Query(default=[]),
                   vendor: str = "", q: str = "", error: str = "",
                   user: str = Depends(require_auth)):
    db = StagingDB(config.staging_db)
    summary = db.summary()
    all_assets = db.list_all()
    unacknowledged_moves = db.count_unacknowledged_moves()
    db.close()

    vlans = sorted({a.vlan for a in all_assets if a.vlan}, key=lambda v: (len(v), v))
    vendors = sorted({a.vendor for a in all_assets if a.vendor})

    assets = all_assets
    if not classification:
        # Archived rows are opt-in visibility only (via the Classification filter) —
        # don't clutter the default view with devices that dropped off the network.
        assets = [a for a in assets if a.classification != "archived"]
    if classification:
        assets = [a for a in assets if a.classification in classification]
    if exclude:
        assets = [a for a in assets if a.classification not in exclude]
    if vlan:
        assets = [a for a in assets if (a.vlan or "") in vlan]
    if vendor:
        assets = [a for a in assets if a.vendor == vendor]
    if q:
        ql = q.lower()
        assets = [a for a in assets if ql in (a.mac or "").lower()
                  or ql in (a.ip or "").lower() or ql in (a.hostname or "").lower()]

    return templates.TemplateResponse(request, "discover.html", {
        "active": "discover", "error": error or None,
        "summary": summary, "total": sum(summary.values()),
        "assets": assets, "vlans": vlans, "vendors": vendors,
        "unacknowledged_moves": unacknowledged_moves,
        "all_classifications": _ALL_CLASSIFICATIONS,
        "actionable": _ACTIONABLE,
        "f_classification": classification, "f_exclude": exclude, "f_vlan": vlan,
        "f_vendor": vendor, "f_q": q,
        "panel_id": "discover", "run_endpoint": "/discover/run",
        "run_button_label": "Run Discovery Now", "run_id": None,
    })


def _redirect_to_discover(request: Request, error: Optional[str] = None) -> RedirectResponse:
    # Carry the current filters back through (same as before), plus an error message when
    # given - discover_page() picks it up and renders it as a banner instead of the action
    # just silently doing nothing when e.g. a target doesn't resolve to a real asset.
    params = [(k, v) for k, v in request.query_params.multi_items() if k != "error"]
    if error:
        params.append(("error", error))
    qs = urlencode(params, doseq=True)
    return RedirectResponse(url=f"/?{qs}" if qs else "/", status_code=303)


@app.post("/discover/promote/{target}")
def discover_promote(request: Request, target: str,
                      name: str = Form(""), role: str = Form(""),
                      site: str = Form(""), vendor: str = Form(""),
                      user: str = Depends(require_auth)):
    db = StagingDB(config.staging_db)
    rules = load_rules(config.rules_file)
    asset = discover_mod._resolve_target(db, target)
    error = None
    if not asset:
        error = f"No such asset: {target}"
    else:
        with DiodeClient(
            target=config.diode_target, app_name="netdisco-netbox-sync",
            app_version="0.1.0", client_id=config.diode_client_id,
            client_secret=config.diode_client_secret,
        ) as diode:
            ok = discover_mod._promote_asset(
                diode, db, config, rules, asset,
                name=name or None, role=role or None,
                site=site or None, vendor=vendor or None,
            )
        if not ok:
            error = f"Promote failed for {target} - see staging DB's promotion_failed reason, or the server log."
    db.close()
    return _redirect_to_discover(request, error=error)


@app.post("/discover/ignore/{target}")
def discover_ignore(request: Request, target: str, reason: str = Form("Manually ignored"),
                     user: str = Depends(require_auth)):
    db = StagingDB(config.staging_db)
    asset = discover_mod._resolve_target(db, target)
    error = None
    if asset:
        db.set_classification(asset.mac, "ignore", reason=reason, ignore_reason=reason)
    else:
        error = f"No such asset: {target}"
    db.close()
    return _redirect_to_discover(request, error=error)


@app.post("/discover/unpromote/{target}")
def discover_unpromote(request: Request, target: str,
                        reason: str = Form("Manually unpromoted"),
                        user: str = Depends(require_auth)):
    db = StagingDB(config.staging_db)
    asset = discover_mod._resolve_target(db, target)
    error = None
    if not asset:
        error = f"No such asset: {target}"
    elif asset.classification != "managed":
        error = f"{target} is not managed (current state: {asset.classification}) - nothing to unpromote."
    else:
        db.set_classification(
            asset.mac, "candidate", reason=reason,
            netbox_name=None, netbox_site=None, netbox_role=None,
            netbox_device_id=None, promoted_at=None,
        )
    db.close()
    return _redirect_to_discover(request, error=error)


@app.post("/discover/edit-managed/{target}")
def discover_edit_managed(request: Request, target: str,
                           name: str = Form(...), role: str = Form(...),
                           site: str = Form(...), tenant: str = Form(""),
                           location: str = Form(""), user: str = Depends(require_auth)):
    """Correct an already-managed asset's NetBox fields via a direct PATCH to the real
    device (by netbox_device_id), not a Diode re-push. Diode matches devices by
    (name, site, tenant) - it's the only safe way to change any of those three on a
    device that's already been promoted, since a Diode re-push with a different value
    can't find the existing device by natural key and creates a duplicate instead of
    updating in place (see lifecycle.py's NetBoxClient.update_device_fields for the
    full story - this is exactly the bug class a stale queued Diode request triggered
    in production once already).
    """
    db = StagingDB(config.staging_db)
    asset = discover_mod._resolve_target(db, target)
    error = None
    if not asset:
        error = f"No such asset: {target}"
    elif asset.classification != "managed":
        error = f"{target} is not managed (current state: {asset.classification}) - nothing to edit."
    elif not config.netbox_url or not config.netbox_token:
        error = "NETBOX_URL/NETBOX_TOKEN not set - direct NetBox edits need both."
    else:
        nb = lifecycle_mod.NetBoxClient(config.netbox_url, config.netbox_token)
        try:
            device_id = asset.netbox_device_id
            if not device_id:
                # Not backfilled by a heartbeat yet (or NETBOX_TOKEN was only just set) -
                # try once right now rather than making the operator wait for the next
                # scheduled heartbeat.
                found = nb.find_device(asset.netbox_name, site=asset.netbox_site, tenant=asset.netbox_tenant)
                device_id = found["id"] if found else None
            if not device_id:
                error = (f"{target} isn't visible in NetBox yet (Diode's write may still be "
                         f"in flight) - try again in a bit, or after the next heartbeat run.")
            else:
                # tenant/location passed through as-is, not collapsed to None with
                # `or None` - the edit form always submits full state, so an empty
                # string here means "clear this field", not "leave it alone".
                # update_device_fields already treats "" correctly (resolves to no
                # match, clears the field) - collapsing it to None here would instead
                # skip the field entirely, silently leaving NetBox's existing value in
                # place even though the operator explicitly blanked it out.
                nb.update_device_fields(
                    device_id, name=name, role=role, site=site,
                    tenant=tenant, location=location,
                )
                db.update_netbox_fields(
                    asset.mac, netbox_device_id=device_id, netbox_name=name,
                    netbox_site=site, netbox_role=role,
                    netbox_tenant=tenant or None, netbox_location=location or None,
                )
        except ValueError as e:
            error = f"Edit failed for {target}: {e}"
        except httpx.HTTPStatusError as e:
            error = f"NetBox rejected the edit for {target}: {e.response.text}"
        except httpx.HTTPError as e:
            error = f"Can't reach NetBox at {config.netbox_url}: {e}."
        finally:
            nb.close()
    db.close()
    return _redirect_to_discover(request, error=error)


@app.post("/discover/run")
async def discover_run(request: Request, user: str = Depends(require_auth)):
    run_id = start_run("discover.py", "run")
    return render_run_panel(request, "discover", "/discover/run", "Run Discovery Now", run_id)


# ---------------------------------------------------------------------------
# Port move audit log — kept off the main Discover page on purpose (see
# templates/moves.html's own note): a flat, ever-growing table there would just flood the
# page once there are dozens/hundreds of entries. Discover only shows a small "N need
# review" badge; the full log with Acknowledge lives here. Acknowledging never deletes a
# row - this stays a complete audit trail, acknowledged or not.
# ---------------------------------------------------------------------------

@app.get("/discover/moves", response_class=HTMLResponse)
def discover_moves(request: Request, user: str = Depends(require_auth)):
    db = StagingDB(config.staging_db)
    history = db.list_port_history()
    db.close()
    return templates.TemplateResponse(request, "moves.html", {
        "active": "discover", "history": history,
    })


@app.post("/discover/moves/{history_id}/acknowledge")
def discover_acknowledge_move(request: Request, history_id: int, user: str = Depends(require_auth)):
    db = StagingDB(config.staging_db)
    db.acknowledge_move(history_id)
    db.close()
    return RedirectResponse(url="/discover/moves", status_code=303)


@app.post("/discover/moves/acknowledge-all")
def discover_acknowledge_all_moves(request: Request, user: str = Depends(require_auth)):
    db = StagingDB(config.staging_db)
    db.acknowledge_all_moves()
    db.close()
    return RedirectResponse(url="/discover/moves", status_code=303)


# ---------------------------------------------------------------------------
# Config editor — rules.yaml (vlan_policy + device_overrides)
#
# Every write is validated before it touches the real file: build the updated
# dict, write it to a .tmp file, round-trip it through classifier.load_rules()
# (the exact same parser sync.py/discover.py use), and only on success replace
# the real file (keeping a timestamped .bak of what was there before). An edit
# that would break parsing never touches rules.yaml at all.
#
# Note: yaml.safe_dump does not preserve the hand-written comments in the
# current rules.yaml - saving through this UI will strip them. Acceptable
# trade-off for now (the web UI becomes the documentation going forward);
# switch to ruamel.yaml for round-trip comment preservation if that's missed.
# ---------------------------------------------------------------------------

def _load_raw_rules() -> dict:
    with open(config.rules_file) as f:
        return yaml.safe_load(f) or {}


def _save_raw_rules(raw: dict) -> Optional[str]:
    """Validate-then-atomically-replace. Returns an error string on failure
    (rules.yaml untouched), or None on success."""
    tmp_path = config.rules_file + ".tmp"
    with open(tmp_path, "w") as f:
        yaml.safe_dump(raw, f, sort_keys=False, default_flow_style=False, allow_unicode=True)
    try:
        load_rules(tmp_path)
    except Exception as e:
        os.remove(tmp_path)
        return str(e)
    backup_path = f"{config.rules_file}.bak-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(config.rules_file, backup_path)
    os.replace(tmp_path, config.rules_file)
    return None


def _fetch_netdisco_inventory() -> tuple[list, Optional[str]]:
    """Live query of every device Netdisco currently has in inventory (the same
    get_all_devices() sync.py itself uses) - best-effort, same as the Lifecycle page's
    NetBox fetch: this needs Netdisco reachable, Discover/Config's own data never did
    before, so a connection failure here degrades to an error message, not a crash.
    """
    try:
        nd = NetdiscoClient(config)
        nd.login()
        devices = nd.get_all_devices()
        nd.close()
    except httpx.HTTPError as e:
        return [], (f"Can't reach Netdisco at {config.netdisco_url}: {e}. Check the "
                     f"netdisco-netbox-sync-config ConfigMap's resolved NETDISCO_URL and "
                     f"that Netdisco's host is up.")
    return devices, None


def _render_config_page(request: Request, error: Optional[str] = None):
    raw = _load_raw_rules()
    vlan_policy = raw.get("vlan_policy") or {}
    device_overrides = raw.get("device_overrides") or {}
    vlans_sorted = sorted(vlan_policy.items(), key=lambda kv: (len(kv[0]), kv[0]))

    inventory, inventory_error = _fetch_netdisco_inventory()
    inventory_rows = sorted(
        (
            {
                "name": d.display_name, "ip": d.ip, "vendor": d.vendor or "—",
                "model": d.model or "—", "overridden": d.display_name in device_overrides,
                "site": (device_overrides.get(d.display_name) or {}).get("site") or "",
                "tenant": (device_overrides.get(d.display_name) or {}).get("tenant") or "",
                "location": (device_overrides.get(d.display_name) or {}).get("location") or "",
                "role": (device_overrides.get(d.display_name) or {}).get("role") or "",
            }
            for d in inventory
        ),
        key=lambda r: r["name"],
    )

    subnets = sorted(raw.get("ip_inventory_subnets") or [])

    return templates.TemplateResponse(request, "config.html", {
        "active": "config", "error": error,
        "vlans": vlans_sorted, "device_overrides": sorted(device_overrides.items()),
        "inventory": inventory_rows, "inventory_error": inventory_error,
        "subnets": subnets,
        "panel_id": "config", "run_endpoint": "/sync/run",
        "run_button_label": "Run Sync Now", "run_id": None,
    })


@app.get("/config", response_class=HTMLResponse)
def config_page(request: Request, user: str = Depends(require_auth)):
    return _render_config_page(request)


@app.post("/config/vlan")
def config_save_vlan(
    request: Request, vid: str = Form(...), intent: str = Form(...),
    default_role: str = Form(""), default_site: str = Form(""),
    default_tenant: str = Form(""), default_location: str = Form(""),
    description: str = Form(""), user: str = Depends(require_auth),
):
    raw = _load_raw_rules()
    raw.setdefault("vlan_policy", {})
    entry = {"intent": intent}
    if default_role: entry["default_role"] = default_role
    if default_site: entry["default_site"] = default_site
    if default_tenant: entry["default_tenant"] = default_tenant
    if default_location: entry["default_location"] = default_location
    if description: entry["description"] = description
    raw["vlan_policy"][str(vid)] = entry
    error = _save_raw_rules(raw)
    return _render_config_page(request, error=error)


@app.post("/config/vlan/{vid}/delete")
def config_delete_vlan(request: Request, vid: str, user: str = Depends(require_auth)):
    raw = _load_raw_rules()
    (raw.get("vlan_policy") or {}).pop(vid, None)
    error = _save_raw_rules(raw)
    return _render_config_page(request, error=error)


@app.post("/config/device-override")
def config_save_device_override(
    request: Request, name: str = Form(...), site: str = Form(""),
    tenant: str = Form(""), location: str = Form(""), role: str = Form(""),
    user: str = Depends(require_auth),
):
    raw = _load_raw_rules()
    raw.setdefault("device_overrides", {})
    entry = {}
    if site: entry["site"] = site
    if tenant: entry["tenant"] = tenant
    if location: entry["location"] = location
    if role: entry["role"] = role
    raw["device_overrides"][name] = entry
    error = _save_raw_rules(raw)
    return _render_config_page(request, error=error)


@app.post("/config/device-override/{name}/delete")
def config_delete_device_override(request: Request, name: str, user: str = Depends(require_auth)):
    raw = _load_raw_rules()
    (raw.get("device_overrides") or {}).pop(name, None)
    error = _save_raw_rules(raw)
    return _render_config_page(request, error=error)


@app.post("/config/subnet")
def config_add_subnet(request: Request, subnet: str = Form(...), user: str = Depends(require_auth)):
    raw = _load_raw_rules()
    subnets = raw.setdefault("ip_inventory_subnets", [])
    subnet = subnet.strip()
    if subnet and subnet not in subnets:
        subnets.append(subnet)
    error = _save_raw_rules(raw)
    return _render_config_page(request, error=error)


@app.post("/config/subnet/delete")
def config_delete_subnet(request: Request, subnet: str = Form(...), user: str = Depends(require_auth)):
    # Subnet as a form field, not a URL path segment - CIDR strings contain "/"
    # (e.g. "10.20.0.0/18"), which doesn't survive as a path parameter cleanly.
    raw = _load_raw_rules()
    subnets = raw.get("ip_inventory_subnets") or []
    raw["ip_inventory_subnets"] = [s for s in subnets if s != subnet]
    error = _save_raw_rules(raw)
    return _render_config_page(request, error=error)


@app.post("/sync/run")
async def sync_run(request: Request, user: str = Depends(require_auth)):
    run_id = start_run("sync.py")
    return render_run_panel(request, "config", "/sync/run", "Run Sync Now", run_id)


# ---------------------------------------------------------------------------
# Lifecycle — staleness view. Read-only: reuses lifecycle.py's own NetBoxClient
# and _compute_state() so "what state is this right now" is computed with the
# exact same logic the reconciler itself uses, freshly on every page load -
# this is a live dry-run view, not just whatever discovery_state NetBox last
# had written to it. Nothing on this page ever PATCHes NetBox except the
# "Run Lifecycle Reconciler Now" button, which shells out to lifecycle.py
# itself (same as the other two Run Now buttons).
# ---------------------------------------------------------------------------

@app.get("/lifecycle", response_class=HTMLResponse)
def lifecycle_page(request: Request, user: str = Depends(require_auth)):
    error = None
    rows = []
    if not config.netbox_url or not config.netbox_token:
        error = "NETBOX_URL/NETBOX_TOKEN not set - lifecycle.py's NetBoxClient needs both."
    else:
        devices = []
        nb = lifecycle_mod.NetBoxClient(config.netbox_url, config.netbox_token)
        try:
            devices = nb.get_managed_devices()
        except httpx.HTTPError as e:
            # Discover/Config don't need live network access (SQLite + YAML only) - this
            # page does, since it computes state live from NetBox on every load, so degrade
            # to an error banner instead of a raw 500. In-cluster, NETBOX_URL should be
            # netbox.netbox.svc.cluster.local - a failure here more likely means NetBox's
            # pod/Service is down, or the NETBOX_TOKEN Secret is stale, not a LAN/VPN issue.
            error = f"Can't reach NetBox at {config.netbox_url}: {e}."
        finally:
            nb.close()
        now = datetime.datetime.now(datetime.timezone.utc)
        for dev in devices:
            cf = dev.get("custom_fields") or {}
            stored_state = cf.get("discovery_state")
            last_discovered = lifecycle_mod._parse_dt(cf.get("last_discovered"))
            age_days = (now - last_discovered).total_seconds() / 86400 if last_discovered else None
            computed_state = (
                lifecycle_mod._PROTECTED if stored_state == lifecycle_mod._PROTECTED
                else lifecycle_mod._compute_state(age_days, config) if age_days is not None
                else None
            )
            rows.append({
                "name": dev["name"],
                "status": dev.get("status", {}).get("value") or "unknown",
                "stored_state": stored_state or "none",
                "computed_state": computed_state or "none",
                "pending": computed_state is not None and computed_state != stored_state,
                "first_discovered": cf.get("first_discovered"),
                "last_discovered": cf.get("last_discovered"),
                "age_days": f"{age_days:.1f}" if age_days is not None else "—",
            })
        rows.sort(key=lambda r: (r["age_days"] == "—", -(float(r["age_days"]) if r["age_days"] != "—" else 0)))

    return templates.TemplateResponse(request, "lifecycle.html", {
        "active": "lifecycle", "error": error, "rows": rows,
        "panel_id": "lifecycle", "run_endpoint": "/lifecycle/run",
        "run_button_label": "Run Lifecycle Reconciler Now", "run_id": None,
    })


@app.post("/lifecycle/run")
async def lifecycle_run(request: Request, user: str = Depends(require_auth)):
    run_id = start_run("lifecycle.py")
    return render_run_panel(request, "lifecycle", "/lifecycle/run",
                             "Run Lifecycle Reconciler Now", run_id)
