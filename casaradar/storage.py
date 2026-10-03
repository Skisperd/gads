"""Persistência em SQLite: anúncios vistos, histórico de preços e assinaturas para dedup."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    search_name TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    transaction_type TEXT,
    price INTEGER,
    property_type TEXT,
    typology TEXT,
    rooms INTEGER,
    area_m2 REAL,
    location TEXT,
    image_url TEXT,
    published_at TEXT,
    fingerprint TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    notified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_listings_fp ON listings(fingerprint);
CREATE INDEX IF NOT EXISTS idx_listings_search ON listings(search_name, last_seen);
CREATE TABLE IF NOT EXISTS price_history (
    key TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    price INTEGER
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class UpsertResult:
    listing: Listing
    is_new: bool
    old_price: int | None
    duplicate_of: list[str]  # keys de outros sites com a mesma assinatura


class Storage:
    def __init__(self, path: str | Path):
        p = Path(path)
        if str(p) != ":memory:":
            p.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(p))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def upsert(self, listing: Listing, search_name: str) -> UpsertResult:
        now = _now()
        row = self.conn.execute("SELECT price FROM listings WHERE key = ?", (listing.key,)).fetchone()
        dupes = [
            r["key"]
            for r in self.conn.execute(
                "SELECT key FROM listings WHERE fingerprint = ? AND source != ?",
                (listing.fingerprint, listing.source),
            )
        ]
        if row is None:
            self.conn.execute(
                """INSERT INTO listings (key, source, source_id, search_name, url, title, transaction_type, price,
                   property_type, typology, rooms, area_m2, location, image_url, published_at, fingerprint,
                   first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    listing.key, listing.source, listing.source_id, search_name, listing.url, listing.title,
                    listing.transaction, listing.price, listing.property_type, listing.typology, listing.rooms,
                    listing.area_m2, listing.location, listing.image_url, listing.published_at,
                    listing.fingerprint, now, now,
                ),
            )
            self.conn.execute("INSERT INTO price_history (key, seen_at, price) VALUES (?,?,?)", (listing.key, now, listing.price))
            self.conn.commit()
            return UpsertResult(listing, True, None, dupes)

        old_price = row["price"]
        self.conn.execute(
            """UPDATE listings SET last_seen = ?, price = ?, title = ?, area_m2 = COALESCE(?, area_m2),
               typology = COALESCE(?, typology), rooms = COALESCE(?, rooms), location = COALESCE(?, location),
               image_url = COALESCE(?, image_url), fingerprint = ? WHERE key = ?""",
            (
                now, listing.price, listing.title, listing.area_m2, listing.typology, listing.rooms,
                listing.location, listing.image_url, listing.fingerprint, listing.key,
            ),
        )
        if listing.price is not None and listing.price != old_price:
            self.conn.execute("INSERT INTO price_history (key, seen_at, price) VALUES (?,?,?)", (listing.key, now, listing.price))
        self.conn.commit()
        return UpsertResult(listing, False, old_price, dupes)

    def mark_notified(self, keys: list[str]) -> None:
        if not keys:
            return
        self.conn.executemany("UPDATE listings SET notified = 1 WHERE key = ?", [(k,) for k in keys])
        self.conn.commit()

    def recent(self, search_name: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        if search_name:
            return self.conn.execute(
                "SELECT * FROM listings WHERE search_name = ? ORDER BY first_seen DESC LIMIT ?", (search_name, limit)
            ).fetchall()
        return self.conn.execute("SELECT * FROM listings ORDER BY first_seen DESC LIMIT ?", (limit,)).fetchall()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
