"""
SQLite staging table for observed network assets.
All discovery data lands here before anything touches NetBox.
"""
import sqlite3
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ObservedAsset:
    mac: str
    ip: Optional[str] = None
    vlan: Optional[str] = None
    switch: Optional[str] = None
    port: Optional[str] = None
    vendor: Optional[str] = None
    hostname: Optional[str] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    days_stable: Optional[float] = None
    classification: str = "unclassified"
    classification_reason: Optional[str] = None
    netbox_device_id: Optional[int] = None
    netbox_site: Optional[str] = None
    netbox_role: Optional[str] = None
    # Stored (not recomputed) at promotion time, same as netbox_site/netbox_role above -
    # a later heartbeat re-ingest (see discover.py's is_human_locked handling) reuses these
    # exact stored values rather than recomputing from rules.yaml fresh. Deliberate: NetBox's
    # own Device uniqueness is (name, site, tenant) together - if rules.yaml's tenant mapping
    # for this VLAN ever changes after promotion, recomputing fresh at heartbeat time would
    # silently change this device's natural key and create a duplicate, the same bug class
    # already fixed once for infrastructure devices (see transformer.py's own comment).
    netbox_tenant: Optional[str] = None
    netbox_location: Optional[str] = None
    # The switch/port last recorded here as this device's known location - purely local
    # bookkeeping, NOT pushed to NetBox as a Cable object (Diode doesn't support Cable
    # ingestion yet, confirmed live - see discover.py's own comment for the full story).
    # Named tracked_* rather than netbox_* specifically because it isn't a NetBox object -
    # that would be a misleading name for what's actually just our own audit trail.
    # Distinct from switch/port above, which already refresh to the latest Netdisco
    # observation on every run regardless of classification. Comparing the two against
    # each other is how a port move gets detected and logged to port_history.
    tracked_switch: Optional[str] = None
    tracked_port: Optional[str] = None
    netbox_name: Optional[str] = None
    promoted_at: Optional[str] = None
    last_evaluated: Optional[str] = None
    ignore_reason: Optional[str] = None


_TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, _TS_FORMAT)
    except ValueError:
        return None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS observed_assets (
    mac                 TEXT PRIMARY KEY,
    ip                  TEXT,
    vlan                TEXT,
    switch              TEXT,
    port                TEXT,
    vendor              TEXT,
    hostname            TEXT,
    first_seen          TEXT,
    last_seen           TEXT,
    days_stable         REAL,
    classification      TEXT DEFAULT 'unclassified',
    classification_reason TEXT,
    netbox_device_id    INTEGER,
    netbox_site         TEXT,
    netbox_role         TEXT,
    netbox_tenant       TEXT,
    netbox_location     TEXT,
    tracked_switch      TEXT,
    tracked_port        TEXT,
    netbox_name         TEXT,
    promoted_at         TEXT,
    last_evaluated      TEXT,
    ignore_reason       TEXT
);

CREATE TABLE IF NOT EXISTS port_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mac             TEXT NOT NULL,
    netbox_name     TEXT,
    old_switch      TEXT,
    old_port        TEXT,
    new_switch      TEXT,
    new_port        TEXT,
    changed_at      TEXT NOT NULL,
    acknowledged    INTEGER NOT NULL DEFAULT 0,
    acknowledged_at TEXT
);
"""


class StagingDB:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # CREATE TABLE IF NOT EXISTS is a no-op against an already-existing DB file from
        # before these columns existed - SQLite has no native ADD COLUMN IF NOT EXISTS,
        # so this is the standard idempotent idiom (attempt the add, ignore "already exists").
        for col in ("netbox_tenant", "netbox_location"):
            try:
                self._conn.execute(f"ALTER TABLE observed_assets ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e):
                    raise
        # Renamed from netbox_cabled_switch/port (misleading - never was a NetBox object,
        # see ObservedAsset's own comment). RENAME COLUMN handles a DB that has the OLD
        # name, moving real data over intact.
        #
        # Real bug found live in production: RENAME COLUMN's "no such column" error looks
        # IDENTICAL for two different situations - "already renamed, nothing to do" and
        # "never had either name at all because this DB predates the whole feature" - so
        # this loop alone can't tell them apart and was silently doing nothing for the
        # second case. Production's real observed_assets.db went straight from the
        # pre-feature schema to today's code, skipping the intermediate netbox_cabled_*
        # stage that only ever existed in lab testing - so RENAME COLUMN always failed
        # "no such column" (correctly ignored, but for the wrong reason) and the column
        # was never actually added, until the first promote's set_cabled_port() call hit
        # a genuine "no such column: tracked_switch" - the asset had already been pushed
        # to NetBox and marked managed locally by that point, so promote "worked" from the
        # user's perspective while the request itself 500'd.
        #
        # Fix: always follow the rename attempt with a plain ADD COLUMN IF NOT EXISTS
        # (same idiom as netbox_tenant/netbox_location above) - covers every case: renamed
        # already (ADD COLUMN then no-ops on "duplicate column name"), fresh DB created
        # with the new name by _SCHEMA above (same no-op), or - the case that was missing -
        # a DB that never had either name, where this is the only thing that actually adds
        # the column.
        for old, new in (("netbox_cabled_switch", "tracked_switch"), ("netbox_cabled_port", "tracked_port")):
            try:
                self._conn.execute(f"ALTER TABLE observed_assets RENAME COLUMN {old} TO {new}")
            except sqlite3.OperationalError as e:
                if "no such column" not in str(e) and "duplicate column name" not in str(e):
                    raise
        for col in ("tracked_switch", "tracked_port"):
            try:
                self._conn.execute(f"ALTER TABLE observed_assets ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e):
                    raise
        try:
            self._conn.execute("ALTER TABLE port_history ADD COLUMN acknowledged INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise
        try:
            self._conn.execute("ALTER TABLE port_history ADD COLUMN acknowledged_at TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise
        self._conn.commit()

    def upsert(self, asset: ObservedAsset):
        """Insert or update an observed asset. Never overwrites classification set by a human."""
        existing = self.get_by_mac(asset.mac)

        # Never let a stale node observation overwrite a fresher one. A MAC can
        # show up in multiple node records at once (trunk ports, aged-out CAM
        # entries on other switches) and the loop that calls upsert() has no
        # guaranteed ordering — without this guard, whichever record happens to
        # be processed last wins, silently reverting vlan/switch/port to a
        # stale value even on a locked/managed row.
        if existing:
            new_ts, old_ts = _parse_ts(asset.last_seen), _parse_ts(existing.last_seen)
            if new_ts and old_ts and new_ts < old_ts:
                return

        # Protect confirmed states from being overwritten by the classifier:
        #   managed     → only protected once netbox_name is set, i.e. it actually
        #                 reached NetBox (via 'promote' or auto-promote). A "managed"
        #                 row with no netbox_name never got there and should be
        #                 re-classified/retried on the next run.
        #   ignore      → only protected when ignore_reason is set (set by 'ignore' command)
        #                 auto-ignores from the consumer vendor rule have no ignore_reason
        #                 and can be re-evaluated when the vendor list changes
        is_human_locked = (
            existing and (
                (existing.classification == "managed" and existing.netbox_name) or
                (existing.classification == "ignore" and existing.ignore_reason)
            )
        )
        if is_human_locked:
            # Only update observation timestamps and current location
            self._conn.execute("""
                UPDATE observed_assets
                SET ip=COALESCE(?, ip), last_seen=?, days_stable=?, switch=?, port=?, vlan=?
                WHERE mac=?
            """, (asset.ip, asset.last_seen, asset.days_stable,
                  asset.switch, asset.port, asset.vlan, asset.mac))
        elif existing and not is_human_locked:
            # Update everything except human-set classification/reason
            self._conn.execute("""
                UPDATE observed_assets
                SET ip=COALESCE(?, ip), vlan=?, switch=?, port=?, vendor=?,
                    hostname=?, last_seen=?, days_stable=?,
                    classification=?, classification_reason=?, last_evaluated=?
                WHERE mac=?
            """, (asset.ip, asset.vlan, asset.switch, asset.port, asset.vendor,
                  asset.hostname, asset.last_seen, asset.days_stable,
                  asset.classification, asset.classification_reason,
                  asset.last_evaluated, asset.mac))
        else:
            self._conn.execute("""
                INSERT INTO observed_assets
                (mac, ip, vlan, switch, port, vendor, hostname, first_seen, last_seen,
                 days_stable, classification, classification_reason, last_evaluated)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (asset.mac, asset.ip, asset.vlan, asset.switch, asset.port,
                  asset.vendor, asset.hostname, asset.first_seen, asset.last_seen,
                  asset.days_stable, asset.classification, asset.classification_reason,
                  asset.last_evaluated))
        self._conn.commit()

    def get_by_mac(self, mac: str) -> Optional[ObservedAsset]:
        row = self._conn.execute(
            "SELECT * FROM observed_assets WHERE mac=?", (mac,)
        ).fetchone()
        return _row_to_asset(row) if row else None

    def get_by_ip(self, ip: str) -> Optional[ObservedAsset]:
        row = self._conn.execute(
            "SELECT * FROM observed_assets WHERE ip=?", (ip,)
        ).fetchone()
        return _row_to_asset(row) if row else None

    def set_classification(self, mac: str, classification: str,
                           reason: str, **kwargs):
        """Manually override classification (used by CLI promote/ignore commands)."""
        self._conn.execute("""
            UPDATE observed_assets
            SET classification=?, classification_reason=?, last_evaluated=?
            WHERE mac=?
        """, (classification, reason, _now(), mac))
        for col, val in kwargs.items():
            self._conn.execute(
                f"UPDATE observed_assets SET {col}=? WHERE mac=?", (val, mac)
            )
        self._conn.commit()

    def update_netbox_fields(self, mac: str, **kwargs) -> None:
        """Update netbox_* columns only - unlike set_classification(), does not touch
        classification/classification_reason/last_evaluated. Used both for the heartbeat's
        opportunistic netbox_device_id backfill (a device-ID lookup succeeding isn't a
        reclassification event) and for the webui's direct-edit path (updating the stored
        fields to match a NetBox PATCH that already succeeded, so the next heartbeat's
        Diode re-push stays consistent with what's actually in NetBox instead of reverting
        to the pre-edit values)."""
        for col, val in kwargs.items():
            self._conn.execute(
                f"UPDATE observed_assets SET {col}=? WHERE mac=?", (val, mac)
            )
        self._conn.commit()

    def list_all(self) -> list[ObservedAsset]:
        rows = self._conn.execute(
            "SELECT * FROM observed_assets ORDER BY classification, vlan, last_seen DESC"
        ).fetchall()
        return [_row_to_asset(r) for r in rows]

    def list_by_classification(self, classification: str) -> list[ObservedAsset]:
        rows = self._conn.execute(
            "SELECT * FROM observed_assets WHERE classification=? ORDER BY last_seen DESC",
            (classification,)
        ).fetchall()
        return [_row_to_asset(r) for r in rows]

    def summary(self) -> dict[str, int]:
        rows = self._conn.execute("""
            SELECT classification, COUNT(*) as cnt
            FROM observed_assets GROUP BY classification
        """).fetchall()
        return {r["classification"]: r["cnt"] for r in rows}

    def prune_expired(self, prune_days: int) -> list[ObservedAsset]:
        """Archive unclassified/candidate assets not re-observed in prune_days.

        Only touches the two 'still in limbo' states. 'managed' (promoted to
        NetBox), 'ignore' (human or auto), and 'promotion_failed' (a real
        infra device that just had a transient push error) are never
        auto-archived here — those need an explicit human decision
        (unpromote/ignore) or get retried by the classifier, not silent
        removal. This is specifically for transient noise (e.g. a MAC seen
        only because of a temporary bridged/test cable) that would otherwise
        accumulate in the staging DB forever.

        Rows are archived (classification='archived'), never deleted — the
        record (first_seen, vlan, switch/port history) stays queryable and
        re-observation naturally reclassifies it back to unclassified/
        candidate on a future upsert() rather than starting from scratch.

        Call this after a run's upsert loop — anything re-observed in that
        same run already got last_seen bumped to now and won't be eligible.
        Returns the archived rows (full record — mac/ip/vlan/switch/port/
        vendor/hostname) so the caller can report or notify on exactly what
        was archived.
        """
        now = datetime.now()
        rows = self._conn.execute("""
            SELECT * FROM observed_assets
            WHERE classification IN ('unclassified', 'candidate')
        """).fetchall()
        expired = []
        for row in rows:
            asset = _row_to_asset(row)
            last = _parse_ts(asset.last_seen)
            if last and (now - last).total_seconds() / 86400 >= prune_days:
                expired.append(asset)
        if expired:
            reason = f"Archived - not re-observed in {prune_days}+ days"
            now_str = _now()
            self._conn.executemany(
                """UPDATE observed_assets
                   SET classification='archived', classification_reason=?, last_evaluated=?
                   WHERE mac=?""",
                [(reason, now_str, a.mac) for a in expired],
            )
            self._conn.commit()
        return expired

    def set_cabled_port(self, mac: str, switch: Optional[str], port: Optional[str]) -> None:
        """Set tracked_switch/port with no history row - used the first time a device's
        switch/port is recorded (nothing to compare against yet, so it's not a 'move')."""
        self._conn.execute("""
            UPDATE observed_assets SET tracked_switch=?, tracked_port=? WHERE mac=?
        """, (switch, port, mac))
        self._conn.commit()

    def record_port_change(self, mac: str, netbox_name: Optional[str],
                            old_switch: Optional[str], old_port: Optional[str],
                            new_switch: Optional[str], new_port: Optional[str]) -> None:
        """Insert an audit row and update the stored tracked_switch/port to the new value
        in one call - the two always change together, never independently."""
        self._conn.execute("""
            INSERT INTO port_history (mac, netbox_name, old_switch, old_port, new_switch, new_port, changed_at)
            VALUES (?,?,?,?,?,?,?)
        """, (mac, netbox_name, old_switch, old_port, new_switch, new_port, _now()))
        self._conn.execute("""
            UPDATE observed_assets SET tracked_switch=?, tracked_port=? WHERE mac=?
        """, (new_switch, new_port, mac))
        self._conn.commit()

    def list_port_history(self, limit: int = 200) -> list[dict]:
        """Full audit log, newest first - acknowledging an entry never deletes it, it's
        still here for the record. limit is just a sane page cap, not a retention policy."""
        rows = self._conn.execute("""
            SELECT * FROM port_history ORDER BY changed_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def count_unacknowledged_moves(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM port_history WHERE acknowledged = 0"
        ).fetchone()
        return row["c"]

    def acknowledge_move(self, history_id: int) -> None:
        self._conn.execute(
            "UPDATE port_history SET acknowledged=1, acknowledged_at=? WHERE id=?",
            (_now(), history_id),
        )
        self._conn.commit()

    def acknowledge_all_moves(self) -> None:
        self._conn.execute(
            "UPDATE port_history SET acknowledged=1, acknowledged_at=? WHERE acknowledged=0",
            (_now(),),
        )
        self._conn.commit()

    def stale_managed(self, stale_days: int) -> list[ObservedAsset]:
        rows = self._conn.execute("""
            SELECT * FROM observed_assets
            WHERE classification = 'managed'
            AND last_seen < datetime('now', ? || ' days')
            ORDER BY last_seen ASC
        """, (f"-{stale_days}",)).fetchall()
        return [_row_to_asset(r) for r in rows]

    def close(self):
        self._conn.close()


def days_until_prune(asset: ObservedAsset, prune_days: int) -> Optional[float]:
    """Days remaining before this asset is deleted on the next 'run' if it
    isn't re-observed before then. None if the asset isn't prune-eligible
    (wrong classification, or no last_seen yet to measure from). <= 0 means
    it's already past the threshold and will be pruned on the next run.
    """
    if asset.classification not in ("unclassified", "candidate"):
        return None
    last = _parse_ts(asset.last_seen)
    if not last:
        return None
    elapsed_days = (datetime.now() - last).total_seconds() / 86400
    return prune_days - elapsed_days


def _row_to_asset(row: sqlite3.Row) -> ObservedAsset:
    return ObservedAsset(**{k: row[k] for k in row.keys()})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
