from __future__ import annotations

import json
import os
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4


DEFAULT_DB = Path(__file__).parent / os.environ.get("GIPHYWALL_DB_FILE", "giphywall.db")
LOGIN_IDENTIFIER_COLUMN: Optional[str] = None


def _ensure_db_path(db_path: Optional[Path | str]) -> Path:
    if db_path:
        path = Path(db_path)
    else:
        path = DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    path = _ensure_db_path(db_path)
    try:
        conn = sqlite3.connect(str(path))
    except Exception:
        # fallback to in-memory DB to avoid raising for missing filesystem
        conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _get_login_identifier_column(conn: sqlite3.Connection) -> str:
    """Return whichever column the users table uses for login ids."""
    global LOGIN_IDENTIFIER_COLUMN
    if LOGIN_IDENTIFIER_COLUMN:
        return LOGIN_IDENTIFIER_COLUMN
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(users)")
        names = {row[1] for row in cur.fetchall()}
        for candidate in ("login_identifier", "external_id", "kakao_id"):
            if candidate in names:
                LOGIN_IDENTIFIER_COLUMN = candidate
                return LOGIN_IDENTIFIER_COLUMN
    except Exception:
        pass
    LOGIN_IDENTIFIER_COLUMN = "login_identifier"
    return LOGIN_IDENTIFIER_COLUMN


def init_db(db_path: Optional[Path | str] = None) -> None:
    """Create tables if they don't exist."""
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.executescript(
            """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            login_identifier TEXT UNIQUE,
            username TEXT,
            display_name TEXT,
            profile_url TEXT,
            email TEXT,
            created_at TEXT,
            last_login TEXT
        );

        CREATE TABLE IF NOT EXISTS giphies (
            id INTEGER PRIMARY KEY,
            uuid TEXT UNIQUE,
            giphy_id TEXT,
            giphy_url TEXT,
            thumbnail_url TEXT,
            image_path TEXT,
            title TEXT,
            tags TEXT,
            uploaded_by INTEGER,
            created_at TEXT,
            FOREIGN KEY(uploaded_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY,
            giphy_uuid TEXT,
            comment_text TEXT,
            ai_generated INTEGER DEFAULT 1,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS friend_requests (
            id INTEGER PRIMARY KEY,
            requester_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT,
            responded_at TEXT,
            FOREIGN KEY(requester_id) REFERENCES users(id),
            FOREIGN KEY(receiver_id) REFERENCES users(id)
        );
        """
        )
        conn.commit()
    except Exception:
        logging.exception("init_db failed; continuing with best-effort")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def create_user(
    login_identifier: Optional[str] = None,
    username: Optional[str] = None,
    display_name: Optional[str] = None,
    profile_url: Optional[str] = None,
    email: Optional[str] = None,
    db_path: Optional[Path | str] = None,
) -> int:
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        created = _now_iso()
        identifier = login_identifier or username or email or f"local:{uuid4().hex}"
        try:
            identifier_col = _get_login_identifier_column(conn)
            cur.execute(
                f"""
            INSERT INTO users ({identifier_col}, username, display_name, profile_url, email, created_at, last_login)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (identifier, username, display_name, profile_url, email, created, created),
            )
            conn.commit()
            user_id = cur.lastrowid
        except sqlite3.IntegrityError:
            # user already exists; return existing id
            identifier_col = _get_login_identifier_column(conn)
            cur.execute(f"SELECT id FROM users WHERE {identifier_col} = ?", (identifier,))
            row = cur.fetchone()
            user_id = int(row["id"]) if row and "id" in row.keys() else 0
    except Exception:
        logging.exception("create_user failed")
        user_id = 0
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return user_id


def get_user_by_login_identifier(login_identifier: str, db_path: Optional[Path | str] = None) -> Optional[Dict[str, Any]]:
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        column = _get_login_identifier_column(conn)
        cur.execute(f"SELECT * FROM users WHERE {column} = ?", (login_identifier,))
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception:
        logging.exception("get_user_by_login_identifier failed")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_user_by_external_id(external_id: str, db_path: Optional[Path | str] = None) -> Optional[Dict[str, Any]]:
    """Back-compat shim for legacy callers expecting the old name."""
    return get_user_by_login_identifier(external_id, db_path=db_path)


def get_user_by_username(username: str, db_path: Optional[Path | str] = None) -> Optional[Dict[str, Any]]:
    try:
        if not username:
            return None
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception:
        logging.exception("get_user_by_username failed")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_user_by_email(email: str, db_path: Optional[Path | str] = None) -> Optional[Dict[str, Any]]:
    try:
        if not email:
            return None
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception:
        logging.exception("get_user_by_email failed")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def find_user_by_identifier(identifier: str, db_path: Optional[Path | str] = None) -> Optional[Dict[str, Any]]:
    """Lookup a user by username, email, or display name (case-insensitive)."""
    query = (identifier or "").strip()
    if not query:
        return None
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM users
            WHERE lower(coalesce(username, '')) = lower(?)
               OR lower(coalesce(email, '')) = lower(?)
               OR lower(coalesce(display_name, '')) = lower(?)
            ORDER BY id ASC
            LIMIT 1
            """,
            (query, query, query),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception:
        logging.exception("find_user_by_identifier failed")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

def get_user_by_id(user_id: int, db_path: Optional[Path | str] = None) -> Optional[Dict[str, Any]]:
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception:
        logging.exception("get_user_by_id failed")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def add_giphy(
    uuid: str,
    giphy_id: str,
    giphy_url: str,
    thumbnail_url: str,
    image_path: Optional[str] = None,
    title: Optional[str] = None,
    tags: Optional[List[str]] = None,
    uploaded_by: Optional[int] = None,
    db_path: Optional[Path | str] = None,
) -> int:
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        created = _now_iso()
        tags_json = json.dumps(tags or [])
        cur.execute(
            """
        INSERT OR REPLACE INTO giphies (uuid, giphy_id, giphy_url, thumbnail_url, image_path, title, tags, uploaded_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uuid, giphy_id, giphy_url, thumbnail_url, image_path, title, tags_json, uploaded_by, created),
        )
        conn.commit()
        last = cur.lastrowid
    except Exception:
        logging.exception("add_giphy failed")
        last = 0
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return last


def list_giphies(db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM giphies ORDER BY id DESC")
        rows = cur.fetchall()
        results: List[Dict[str, Any]] = []
        for r in rows:
            row = dict(r)
            try:
                row["tags"] = json.loads(row.get("tags") or "[]")
            except Exception:
                row["tags"] = []
            results.append(row)
        return results
    except Exception:
        logging.exception("list_giphies failed")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass

def list_giphies_for_user(user_id: Optional[int], db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    """Return giphies uploaded by a specific user."""
    if user_id is None:
        return []
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM giphies WHERE uploaded_by = ? ORDER BY id DESC",
            (user_id,),
        )
        rows = cur.fetchall()
        results: List[Dict[str, Any]] = []
        for r in rows:
            row = dict(r)
            try:
                row["tags"] = json.loads(row.get("tags") or "[]")
            except Exception:
                row["tags"] = []
            results.append(row)
        return results
    except Exception:
        logging.exception("list_giphies_for_user failed")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def delete_giphy_by_uuid(uuid: str, db_path: Optional[Path | str] = None) -> None:
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM giphies WHERE uuid = ?", (uuid,))
        conn.commit()
    except Exception:
        logging.exception("delete_giphy_by_uuid failed")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def add_comment(giphy_uuid: str, comment_text: str, ai_generated: bool = True, db_path: Optional[Path | str] = None) -> int:
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        created = _now_iso()
        cur.execute(
            "INSERT INTO comments (giphy_uuid, comment_text, ai_generated, created_at) VALUES (?, ?, ?, ?)",
            (giphy_uuid, comment_text, 1 if ai_generated else 0, created),
        )
        conn.commit()
        last = cur.lastrowid
    except Exception:
        logging.exception("add_comment failed")
        last = 0
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return last


def get_comments_for_giphy(giphy_uuid: str, db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM comments WHERE giphy_uuid = ? ORDER BY id ASC", (giphy_uuid,))
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logging.exception("get_comments_for_giphy failed")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def generate_doge_comment(content: str) -> str:
    """Lightweight doge-style comment generator.

    This is a simple fallback generator. If you integrate an external AI
    (OpenAI, etc.) you can replace this function to call that service.
    """
    words = [w for w in re_split_words(content) if len(w) > 2]
    picks = (words + ["wow", "such", "much", "very"])[:6]
    parts = [f"{p} {words[0] if words else 'wow'}" if p in ("such", "much", "very") else p for p in picks]
    # simple join, keep it short
    return " ".join(parts)


def re_split_words(text: str) -> List[str]:
    return [t.lower() for t in __import__("re").split(r"\W+", text) if t]


def create_friend_request(requester_id: int, receiver_id: int, db_path: Optional[Path | str] = None) -> Tuple[bool, str]:
    """Create a friend request or accept if the other user already asked."""
    if not requester_id or not receiver_id:
        return False, "Such invalid fren info."
    if requester_id == receiver_id:
        return False, "Cannot request own fren-ness, wow."
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        created = _now_iso()

        cur.execute("SELECT * FROM users WHERE id = ?", (receiver_id,))
        if not cur.fetchone():
            return False, "No fren found there, much sad."

        cur.execute(
            """
            SELECT * FROM friend_requests
            WHERE (requester_id = ? AND receiver_id = ?)
               OR (requester_id = ? AND receiver_id = ?)
            ORDER BY id DESC
            """,
            (requester_id, receiver_id, receiver_id, requester_id),
        )
        existing = cur.fetchone()
        if existing:
            status = existing["status"]
            if status == "accepted":
                return False, "Already frens. Much wow."
            if status == "pending":
                if existing["requester_id"] == requester_id:
                    return False, "Friend req already zoomed."
                else:
                    cur.execute(
                        "UPDATE friend_requests SET status = ?, responded_at = ? WHERE id = ?",
                        ("accepted", _now_iso(), existing["id"]),
                    )
                    conn.commit()
                    return True, "Auto accept! Fren energy mutual."

        cur.execute(
            """
            INSERT INTO friend_requests (requester_id, receiver_id, status, created_at)
            VALUES (?, ?, 'pending', ?)
            """,
            (requester_id, receiver_id, created),
        )
        conn.commit()
        return True, "Friend req launched. Very wow."
    except Exception:
        logging.exception("create_friend_request failed")
        return False, "Friend req broken rn. Much sorry."
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_pending_friend_requests(user_id: int, db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT fr.*, u.username AS requester_username, u.email AS requester_email
            FROM friend_requests fr
            JOIN users u ON u.id = fr.requester_id
            WHERE fr.receiver_id = ? AND fr.status = 'pending'
            ORDER BY fr.created_at ASC, fr.id ASC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logging.exception("list_pending_friend_requests failed")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def respond_to_friend_request(request_id: int, receiver_id: int, accept: bool, db_path: Optional[Path | str] = None) -> Tuple[bool, str]:
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM friend_requests WHERE id = ?", (request_id,))
        req = cur.fetchone()
        if not req or req["receiver_id"] != receiver_id:
            return False, "No such fren ping."
        if req["status"] != "pending":
            return False, "Request already handled wow."

        new_status = "accepted" if accept else "declined"
        cur.execute(
            "UPDATE friend_requests SET status = ?, responded_at = ? WHERE id = ?",
            (new_status, _now_iso(), request_id),
        )
        conn.commit()
        return True, "Fren request updated. Much decision."
    except Exception:
        logging.exception("respond_to_friend_request failed")
        return False, "Cannot update fren req atm."
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_sent_friend_requests(user_id: int, db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT fr.*, u.username AS receiver_username, u.email AS receiver_email
            FROM friend_requests fr
            JOIN users u ON u.id = fr.receiver_id
            WHERE fr.requester_id = ? AND fr.status = 'pending'
            ORDER BY fr.created_at DESC, fr.id DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logging.exception("list_sent_friend_requests failed")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_friends(user_id: int, db_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    try:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT u.* FROM users u
            WHERE u.id IN (
                SELECT receiver_id FROM friend_requests
                WHERE requester_id = ? AND status = 'accepted'
                UNION
                SELECT requester_id FROM friend_requests
                WHERE receiver_id = ? AND status = 'accepted'
            )
            ORDER BY COALESCE(u.username, u.email, u.{_get_login_identifier_column(conn)})
            """,
            (user_id, user_id),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logging.exception("list_friends failed")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass
