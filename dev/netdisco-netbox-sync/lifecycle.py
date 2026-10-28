"""
lifecycle.py — NetBox device staleness reconciler.

Separate from sync.py/discover.py on purpose (observation vs. classification, see
CLAUDE.md/the plan this was built from): those two pipelines only ever set
discovery_source/last_discovered on every push - they don't know and shouldn't decide
whether a device is stale. This script is the only thing that reads last_discovered
back out of NetBox, computes age, and decides discovery_state.

Talks to NetBox's REST API directly - NOT through Diode. Diode has no delete/lifecycle
concept (it's an ingestion/upsert pipeline only, confirmed against the SDK - no entity-
delete operation exposed anywhere in it), and separating credentials here is deliberate:
the observation pipelines' Diode identity should never imply write access to device
status/custom fields beyond what ingestion itself already does.

Never deletes anything. At most, flags devices as decommission_candidate/mia and prints
a summary - an actual removal is a human decision made directly in NetBox.

Run on its own schedule (daily suggested - this isn't time-sensitive the way discovery
is):
    .venv/bin/python lifecycle.py
    .venv/bin/python lifecycle.py --dry-run
"""
import argparse
import sys
from datetime import datetime, timezone

import httpx

from config import load_config

# ---------------------------------------------------------------------------
# discovery_state values, in order - see the age table in the plan this was built from.
# "protected" is manual-only (a human sets it directly in NetBox) and is never touched by
# this script, same "human-locked" principle discover.py already uses for managed/ignore.
# ---------------------------------------------------------------------------
_STATES = ("active", "stale", "review", "decommission_candidate", "mia")
_PROTECTED = "protected"

_CHOICE_SET_NAME = "discovery_state_choices"

_CUSTOM_FIELDS = [
    {
        "name": "discovery_source",
        "label": "Discovery Source",
        "type": "text",
        "object_types": ["dcim.device"],
        "description": "Which discovery pipeline last observed this device (e.g. netdisco).",
    },
    {
        "name": "first_discovered",
        "label": "First Discovered",
        "type": "datetime",
        "object_types": ["dcim.device"],
        "description": "When lifecycle.py first saw this device with a last_discovered value.",
    },
    {
        "name": "last_discovered",
        "label": "Last Discovered",
        "type": "datetime",
        "object_types": ["dcim.device"],
        "description": "Most recent time a discovery pipeline (sync.py/discover.py) observed this device.",
    },
    {
        "name": "discovery_state",
        "label": "Discovery State",
        "type": "select",
        "object_types": ["dcim.device"],
        "description": "Staleness state computed by lifecycle.py from last_discovered. "
                        "Set to 'protected' to exclude a device from this reconciler entirely.",
        # NetBox's CustomField.choice_set is a FK to a separate CustomFieldChoiceSet object
        # (POST /api/extras/custom-field-choice-sets/), not an inline {"extra_choices": [...]}
        # dict - confirmed live, the inline form 400s with "Related object not found using
        # the provided attributes". ensure_custom_fields() creates/looks up that object first
        # and fills in the real ID here before POSTing this field.
        "choice_set": None,
    },
]


class NetBoxClient:
    def __init__(self, url: str, token: str):
        self._base = url.rstrip("/")
        # NetBox v2 API tokens (users/models/tokens.py's own get_auth_header_prefix())
        # use "Bearer <prefix><key>.<secret>", not the classic v1 "Token <value>" scheme -
        # confirmed against real NetBox source, not assumed. The full value NetBox
        # displayed once at token creation (including any prefix and the "." in it) is
        # what belongs in NETBOX_TOKEN, not just a bare key.
        self._http = httpx.Client(
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30,
        )

    def close(self):
        self._http.close()

    def ensure_custom_fields(self) -> None:
        """Idempotent: create any of the 4 custom fields that don't already exist.

        Deliberately not relying on Diode to have created these - confirmed live against
        the real lab NetBox that Diode does NOT auto-create custom field *definitions*
        (an ingest with custom_fields set succeeds with no error even when the field
        doesn't exist yet - the value is just silently dropped). Safe to call on every run.

        Always actually creates missing fields, even under --dry-run: this is schema
        provisioning, not a device data change, and skipping it makes --dry-run actively
        misleading rather than safe - confirmed live: with a field genuinely missing,
        NetBox's own API silently drops the unrecognized cf_<name> filter param instead of
        erroring, so get_managed_devices() would silently return every device in NetBox
        instead of just netdisco-sourced ones, and a "would update 0" dry-run result would
        look clean while actually being computed over the wrong device set entirely.
        """
        resp = self._http.get(f"{self._base}/api/extras/custom-fields/", params={"limit": 0})
        resp.raise_for_status()
        existing = {cf["name"] for cf in resp.json()["results"]}

        for cf in _CUSTOM_FIELDS:
            if cf["name"] in existing:
                continue
            payload = cf
            if cf["name"] == "discovery_state":
                payload = dict(cf, choice_set=self._ensure_choice_set())
            print(f"  custom field {cf['name']!r} missing - creating it")
            resp = self._http.post(f"{self._base}/api/extras/custom-fields/", json=payload)
            if resp.status_code not in (200, 201):
                print(f"    WARN: could not create {cf['name']!r}: "
                      f"{resp.status_code} {resp.text}")

    def _ensure_choice_set(self) -> int:
        """Idempotent: return the id of the discovery_state CustomFieldChoiceSet,
        creating it first if it doesn't exist yet."""
        resp = self._http.get(
            f"{self._base}/api/extras/custom-field-choice-sets/",
            params={"name": _CHOICE_SET_NAME},
        )
        resp.raise_for_status()
        results = resp.json()["results"]
        if results:
            return results[0]["id"]

        resp = self._http.post(
            f"{self._base}/api/extras/custom-field-choice-sets/",
            json={
                "name": _CHOICE_SET_NAME,
                "extra_choices": [[s, s] for s in _STATES] + [[_PROTECTED, _PROTECTED]],
            },
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def get_managed_devices(self) -> list[dict]:
        """Every device with discovery_source=netdisco, i.e. everything the discovery
        pipelines have ever pushed - NetBox's real REST API convention for filtering on
        a custom field value is cf_<name>=<value>."""
        devices = []
        url = f"{self._base}/api/dcim/devices/"
        params = {"cf_discovery_source": "netdisco", "limit": 200}
        while url:
            resp = self._http.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            devices.extend(data["results"])
            url = data.get("next")
            params = None  # "next" is already a full URL with its own query string
        return devices

    def patch_device(self, device_id: int, custom_fields: dict, status: str | None = None) -> None:
        payload = {"custom_fields": custom_fields}
        if status:
            payload["status"] = status
        resp = self._http.patch(f"{self._base}/api/dcim/devices/{device_id}/", json=payload)
        resp.raise_for_status()

    def find_device(self, name: str, site: str | None = None, tenant: str | None = None) -> dict | None:
        """Look up a device by name, disambiguating by site/tenant (NetBox's own Device
        uniqueness key) if more than one comes back. Returns None if nothing matches -
        the caller decides what that means (not yet reconciled by Diode's async
        pipeline, or genuinely doesn't exist). Used to backfill netbox_device_id for
        assets promoted before this existed, and to resolve it on demand for the webui's
        direct-edit path."""
        resp = self._http.get(f"{self._base}/api/dcim/devices/", params={"name": name, "limit": 50})
        resp.raise_for_status()
        results = resp.json()["results"]
        if not results:
            return None
        if len(results) == 1:
            return results[0]
        for dev in results:
            dev_site = (dev.get("site") or {}).get("name")
            dev_tenant = (dev.get("tenant") or {}).get("name")
            if (site is None or dev_site == site) and (tenant is None or dev_tenant == tenant):
                return dev
        return results[0]  # ambiguous and none matched site/tenant - best effort

    def _resolve_id(self, endpoint: str, name: str) -> int | None:
        resp = self._http.get(f"{self._base}/api/{endpoint}/", params={"name": name, "limit": 1})
        resp.raise_for_status()
        results = resp.json()["results"]
        return results[0]["id"] if results else None

    def update_device_fields(self, device_id: int, *, name: str | None = None,
                              role: str | None = None, site: str | None = None,
                              tenant: str | None = None, location: str | None = None) -> dict:
        """Direct PATCH to an existing device by ID - bypasses Diode's create-or-match
        entirely. This is the only safe way to change name/site/tenant on an
        already-managed device without creating a duplicate: those three together are
        NetBox's own Device uniqueness key, so a Diode re-push with a different value
        for any of them can't find the existing device by natural key and creates a new
        one instead of updating in place (confirmed live - this is exactly what a stale
        queued Diode request did in production when a device's site changed upstream).

        role/site are required NetBox fields - passing an unresolvable name raises
        ValueError rather than sending a payload NetBox would reject anyway. tenant/
        location are optional on Device - an unresolvable name for either clears the
        field (sets it to null) rather than failing, matching how leaving them unset
        already behaves elsewhere in this tool.
        """
        payload: dict = {}
        if name is not None:
            payload["name"] = name
        if role is not None:
            role_id = self._resolve_id("dcim/device-roles", role)
            if role_id is None:
                raise ValueError(f"NetBox device role not found: {role!r}")
            payload["role"] = role_id
        if site is not None:
            site_id = self._resolve_id("dcim/sites", site)
            if site_id is None:
                raise ValueError(f"NetBox site not found: {site!r}")
            payload["site"] = site_id
        if tenant is not None:
            # An empty string means "clear this field" (see webapp.py's edit route) -
            # skip the lookup entirely rather than querying name="", which NetBox's
            # filterset silently drops as "no filter" and returns some other, arbitrary
            # tenant instead of correctly matching nothing (confirmed live).
            payload["tenant"] = self._resolve_id("tenancy/tenants", tenant) if tenant else None
        if location is not None:
            payload["location"] = self._resolve_id("dcim/locations", location) if location else None
        resp = self._http.patch(f"{self._base}/api/dcim/devices/{device_id}/", json=payload)
        resp.raise_for_status()
        return resp.json()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _compute_state(age_days: float, config) -> str:
    if age_days < config.lifecycle_active_days:
        return "active"
    if age_days < config.lifecycle_stale_days:
        return "stale"
    if age_days < config.lifecycle_review_days:
        return "review"
    if age_days < config.lifecycle_decommission_days:
        return "decommission_candidate"
    return "mia"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="Report what would change without actually PATCHing NetBox")
    args = parser.parse_args()

    config = load_config()
    if not config.netbox_url or not config.netbox_token:
        print("NETBOX_URL and NETBOX_TOKEN must both be set (see .env.example) - "
              "lifecycle.py talks to NetBox's own REST API directly, not through Diode.",
              file=sys.stderr)
        sys.exit(1)

    nb = NetBoxClient(config.netbox_url, config.netbox_token)
    try:
        print("[lifecycle] ensuring custom fields exist...")
        nb.ensure_custom_fields()

        print("[lifecycle] fetching devices with discovery_source=netdisco...")
        devices = nb.get_managed_devices()
        print(f"  {len(devices)} device(s) found\n")

        now = datetime.now(timezone.utc)
        counts = {s: 0 for s in _STATES}
        counts[_PROTECTED] = 0
        decommission_candidates = []
        changed = 0

        for dev in devices:
            cf = dev.get("custom_fields") or {}
            current_state = cf.get("discovery_state")

            if current_state == _PROTECTED:
                counts[_PROTECTED] += 1
                continue

            last_discovered = _parse_dt(cf.get("last_discovered"))
            if last_discovered is None:
                # Pushed with discovery_source but no last_discovered somehow - skip
                # rather than guess an age.
                continue

            age_days = (now - last_discovered).total_seconds() / 86400
            new_state = _compute_state(age_days, config)
            counts[new_state] += 1

            updates = {}
            if not cf.get("first_discovered"):
                updates["first_discovered"] = cf["last_discovered"]
            if current_state != new_state:
                updates["discovery_state"] = new_state
                print(f"  {dev['name']}: {current_state or '(none)'} -> {new_state} "
                      f"(last seen {age_days:.1f}d ago)")

            # NetBox's own native status field, only touched at the two "device is
            # genuinely gone" ends of the scale - everything else leaves status alone,
            # a stale-but-plausibly-just-quiet device shouldn't flip to offline early.
            nb_status = dev.get("status", {}).get("value")
            status = None
            if new_state in ("decommission_candidate", "mia"):
                if nb_status == "active":
                    status = "offline"
            elif nb_status == "offline":
                # Auto-heal symmetry: a fresh last_discovered is direct evidence the
                # device is reachable again, so restore the status this reconciler itself
                # set to offline - bug found live, confirmed against real data: discovery_state
                # correctly healed mia -> active on rediscovery, but native status stayed
                # stuck on "offline" forever since nothing ever set it back. A human who
                # wants a device to stay offline despite fresh discovery data should use
                # discovery_state=protected (skipped entirely, above) rather than relying on
                # this reconciler leaving a manually-set offline alone - it can't tell the two
                # apart, and the whole point of this field is to track discovery reality.
                status = "active"
            if new_state == "decommission_candidate":
                decommission_candidates.append(dev["name"])

            if updates or status:
                changed += 1
                if not args.dry_run:
                    nb.patch_device(dev["id"], custom_fields=updates, status=status)

        print(f"\n[lifecycle] {'would update' if args.dry_run else 'updated'} "
              f"{changed} device(s)")
        print("\nSTATE SUMMARY")
        print("-" * 30)
        for s in _STATES:
            print(f"  {s:<24} {counts[s]}")
        print(f"  {_PROTECTED:<24} {counts[_PROTECTED]}")

        if decommission_candidates:
            print(f"\nDECOMMISSION CANDIDATES ({len(decommission_candidates)}) - "
                  f"review, don't auto-delete:")
            for name in decommission_candidates:
                print(f"    {name}")
    finally:
        nb.close()


if __name__ == "__main__":
    main()
