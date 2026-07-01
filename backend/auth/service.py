from __future__ import annotations

import base64
import hashlib
import secrets
import sqlite3
import string
import threading
import time
from pathlib import Path

import backend.config as cfg


class AuthService:
    def __init__(self, db_path: str | Path = cfg.AUTH_DB_PATH) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                visible_password TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(email) REFERENCES users(email) ON DELETE CASCADE
            );
            """
        )
        self._migrate()
        self._db.commit()

    def ensure_bootstrap_admin(self) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) FROM users").fetchone()
            if row and row[0] > 0:
                return None
        email = cfg.AUTH_BOOTSTRAP_EMAIL
        password = self.create_user(email, is_admin=True)["password"]
        return f"{email}:{password}"

    def create_user(self, email: str, is_admin: bool = False) -> dict:
        normalized = self._normalize_email(email)
        password = self.generate_password()
        salt, password_hash = self._hash_password(password)
        now = time.time()
        with self._lock:
            self._db.execute(
                """
                INSERT INTO users (email, password_hash, salt, is_admin, created_at, visible_password)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (normalized, password_hash, salt, 1 if is_admin else 0, now, password),
            )
            self._db.commit()
        return {
            "email": normalized,
            "password": password,
            "is_admin": is_admin,
            "created_at": now,
        }

    def list_users(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT email, is_admin, created_at, visible_password FROM users ORDER BY created_at"
            ).fetchall()
        return [
            {"email": row[0], "is_admin": bool(row[1]), "created_at": row[2], "password": row[3]}
            for row in rows
        ]

    def set_user_password(self, email: str, password: str | None = None) -> dict:
        normalized = self._normalize_email(email)
        next_password = self._normalize_password(password) if password else self.generate_password()
        salt, password_hash = self._hash_password(next_password)
        with self._lock:
            cursor = self._db.execute(
                """
                UPDATE users
                SET password_hash = ?, salt = ?, visible_password = ?
                WHERE email = ?
                """,
                (password_hash, salt, next_password, normalized),
            )
            if cursor.rowcount == 0:
                raise ValueError("User not found")
            self._db.commit()
            row = self._db.execute(
                "SELECT email, is_admin, created_at, visible_password FROM users WHERE email = ?",
                (normalized,),
            ).fetchone()
        return {
            "email": row[0],
            "is_admin": bool(row[1]),
            "created_at": row[2],
            "password": row[3],
        }

    def delete_user(self, email: str) -> None:
        normalized = self._normalize_email(email)
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE email = ?", (normalized,))
            self._db.execute("DELETE FROM users WHERE email = ?", (normalized,))
            self._db.commit()

    def login(self, email: str, password: str) -> dict | None:
        normalized = self._normalize_email(email)
        with self._lock:
            row = self._db.execute(
                "SELECT password_hash, salt, is_admin FROM users WHERE email = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        expected_hash, salt, is_admin = row
        if not secrets.compare_digest(expected_hash, self._hash_password(password, salt=salt)[1]):
            return None
        token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(token)
        now = time.time()
        expires_at = now + cfg.AUTH_SESSION_SECONDS
        with self._lock:
            self._db.execute(
                "INSERT INTO sessions (token_hash, email, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token_hash, normalized, expires_at, now),
            )
            self._db.commit()
        return {
            "token": token,
            "user": {"email": normalized, "is_admin": bool(is_admin)},
            "expires_at": expires_at,
        }

    def user_for_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        token_hash = self._hash_token(token)
        now = time.time()
        with self._lock:
            row = self._db.execute(
                """
                SELECT users.email, users.is_admin, sessions.expires_at
                FROM sessions
                JOIN users ON users.email = sessions.email
                WHERE sessions.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            if row[2] < now:
                self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                self._db.commit()
                return None
        return {"email": row[0], "is_admin": bool(row[1]), "expires_at": row[2]}

    def close(self) -> None:
        self._db.close()

    def _migrate(self) -> None:
        columns = {
            row[1]
            for row in self._db.execute("PRAGMA table_info(users)").fetchall()
        }
        if "visible_password" not in columns:
            self._db.execute("ALTER TABLE users ADD COLUMN visible_password TEXT")

    @staticmethod
    def generate_password(length: int = 14) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def _normalize_email(self, email: str) -> str:
        normalized = str(email or "").strip().lower()
        if "@" not in normalized or len(normalized) > 254:
            raise ValueError("Valid email required")
        return normalized

    def _hash_password(self, password: str, salt: str | None = None) -> tuple[str, str]:
        password = self._normalize_password(password)
        salt = salt or base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            200_000,
        )
        return salt, base64.b64encode(digest).decode("ascii")

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _normalize_password(self, password: str | None) -> str:
        normalized = str(password or "").strip()
        if len(normalized) < 8 or len(normalized) > 128:
            raise ValueError("Password must be 8-128 characters")
        return normalized
