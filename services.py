import os
from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras

_schema_ready = False


def _get_conn():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL no configurada")
    return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)


def _ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    provider TEXT DEFAULT 'microsoft',
                    role TEXT DEFAULT 'user',
                    microsoft_auth JSONB
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reservations (
                    reservation_id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    user_email TEXT,
                    event_id TEXT,
                    web_link TEXT,
                    title TEXT,
                    description TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    timezone TEXT,
                    location TEXT,
                    attendees JSONB DEFAULT '[]',
                    status TEXT DEFAULT 'created',
                    created_at TEXT,
                    updated_at TEXT,
                    cancelled_at TEXT,
                    cancellation_reason TEXT
                )
            """)
        conn.commit()
        _schema_ready = True
    finally:
        conn.close()


def _to_user(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    if d.get("microsoft_auth") is None:
        d["microsoft_auth"] = {}
    return d


def _to_reservation(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["start"] = d.pop("start_time", None)
    d["end"] = d.pop("end_time", None)
    if d.get("attendees") is None:
        d["attendees"] = []
    return d


def get_user_by_email(email: str) -> dict | None:
    _ensure_schema()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
            return _to_user(cur.fetchone())
    finally:
        conn.close()


def get_user_by_id(user_id) -> dict | None:
    _ensure_schema()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (int(user_id),))
            return _to_user(cur.fetchone())
    finally:
        conn.close()


def create_user(name: str, email: str, provider: str = "microsoft", role: str = "user") -> dict:
    _ensure_schema()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (name, email, provider, role) VALUES (%s, %s, %s, %s) RETURNING *",
                (name, email, provider, role),
            )
            user = _to_user(cur.fetchone())
        conn.commit()
        return user
    finally:
        conn.close()


def get_or_create_user(name: str, email: str, provider: str = "microsoft") -> dict:
    existing = get_user_by_email(email)
    if existing:
        return existing
    role = "admin" if email.lower() == "diego.perez@keyinstitute.edu.sv" else "user"
    return create_user(name=name, email=email, provider=provider, role=role)


def update_user(user_id, updates: dict[str, Any]) -> dict | None:
    if not updates:
        return get_user_by_id(user_id)
    _ensure_schema()
    conn = _get_conn()
    try:
        set_parts = []
        values = []
        for key, val in updates.items():
            set_parts.append(f"{key} = %s")
            values.append(psycopg2.extras.Json(val) if isinstance(val, (dict, list)) else val)
        values.append(int(user_id))
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE users SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                values,
            )
            user = _to_user(cur.fetchone())
        conn.commit()
        return user
    finally:
        conn.close()


def update_user_microsoft_tokens(
    user_id,
    *,
    access_token: str,
    refresh_token: str | None,
    expires_at: str,
    scope: str,
) -> dict | None:
    user = get_user_by_id(user_id)
    if not user:
        return None
    existing_auth = user.get("microsoft_auth") or {}
    microsoft_auth = {**existing_auth, "access_token": access_token, "expires_at": expires_at, "scope": scope}
    if refresh_token:
        microsoft_auth["refresh_token"] = refresh_token
    return update_user(user_id, {"microsoft_auth": microsoft_auth})


def save_reservation_record(reservation_data: dict[str, Any]) -> dict:
    _ensure_schema()
    timestamp = datetime.now(timezone.utc).isoformat()
    rid = str(reservation_data["reservation_id"])
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reservations (
                    reservation_id, user_id, user_email, event_id, web_link,
                    title, description, start_time, end_time, timezone,
                    location, attendees, status, created_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (reservation_id) DO UPDATE SET
                    event_id = EXCLUDED.event_id,
                    web_link = EXCLUDED.web_link,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    start_time = EXCLUDED.start_time,
                    end_time = EXCLUDED.end_time,
                    timezone = EXCLUDED.timezone,
                    location = EXCLUDED.location,
                    attendees = EXCLUDED.attendees,
                    status = EXCLUDED.status,
                    updated_at = %s
                RETURNING *
                """,
                (
                    rid,
                    reservation_data.get("user_id"),
                    reservation_data.get("user_email"),
                    reservation_data.get("event_id"),
                    reservation_data.get("web_link"),
                    reservation_data.get("title"),
                    reservation_data.get("description"),
                    reservation_data.get("start"),
                    reservation_data.get("end"),
                    reservation_data.get("timezone"),
                    reservation_data.get("location"),
                    psycopg2.extras.Json(reservation_data.get("attendees") or []),
                    reservation_data.get("status", "created"),
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row = _to_reservation(cur.fetchone())
        conn.commit()
        return row
    finally:
        conn.close()


def update_reservation_record(reservation_id: str, updates: dict[str, Any]) -> dict | None:
    _ensure_schema()
    timestamp = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        allowed = {"status", "cancelled_at", "cancellation_reason"}
        set_parts = ["updated_at = %s"]
        values = [timestamp]
        for key in allowed:
            if key in updates:
                set_parts.append(f"{key} = %s")
                values.append(updates[key])
        values.append(reservation_id)
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE reservations SET {', '.join(set_parts)} WHERE reservation_id = %s RETURNING *",
                values,
            )
            row = _to_reservation(cur.fetchone())
        conn.commit()
        return row
    finally:
        conn.close()


def get_user_reservation_record(user_id, reservation_id: str) -> dict | None:
    _ensure_schema()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM reservations WHERE reservation_id = %s AND user_id = %s",
                (reservation_id, int(user_id)),
            )
            return _to_reservation(cur.fetchone())
    finally:
        conn.close()


def list_user_reservation_records(user_id) -> list[dict]:
    _ensure_schema()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM reservations WHERE user_id = %s ORDER BY created_at DESC",
                (int(user_id),),
            )
            return [_to_reservation(row) for row in cur.fetchall()]
    finally:
        conn.close()
