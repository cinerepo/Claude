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
    netbox_name: Optional[str] = None
    promoted_at: Optional[str] = None
    last_evaluated: Optional[str] = None
    ignore_reason: Optional[str] = None


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
    netbox_name         TEXT,
    promoted_at         TEXT,
    last_evaluated      TEXT,
    ignore_reason       TEXT
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

    def upsert(self, asset: ObservedAsset):
        """Insert or update an observed asset. Never overwrites classification set by a human."""
        existing = self.get_by_mac(asset.mac)

        # Protect human-set states from being overwritten by the classifier:
        #   managed     → always protected (set by 'promote' command)
        #   ignore      → only protected when ignore_reason is set (set by 'ignore' command)
        #                 auto-ignores from the consumer vendor rule have no ignore_reason
        #                 and can be re-evaluated when the vendor list changes
        is_human_locked = (
            existing and (
                existing.classification == "managed" or
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


def _row_to_asset(row: sqlite3.Row) -> ObservedAsset:
    return ObservedAsset(**{k: row[k] for k in row.keys()})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
