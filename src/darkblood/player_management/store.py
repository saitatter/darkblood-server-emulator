"""Character storage: the ICharacterStore interface and its SQLite backend."""
import json
import sqlite3
import threading
import time
import weakref
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from darkblood import DATA
from darkblood.player_management.characters import ensure_inventory


class ICharacterStore(ABC):
    """Abstract interface contract for character storage backends."""

    @abstractmethod
    def characters(self, account: str) -> list:
        pass

    @abstractmethod
    def get(self, account: str, char_id: int):
        pass

    @abstractmethod
    def create(self, account: str, request: dict):
        pass

    @abstractmethod
    def delete(self, account: str, char_id: int) -> bool:
        pass

    @abstractmethod
    def save(self):
        pass


def _close_conn(conn):
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


class SqliteCharacterStore(ICharacterStore):
    """SQLite character store (data/darkblood.db); records are JSON documents per character."""

    def __init__(self, db_path=None, timer_refresher=None):
        self.db_path = Path(db_path or DATA / 'darkblood.db')
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._cache = {}  # (account, char_id) -> dict
        self._timer_refresher = timer_refresher
        self._conn = self._open_connection()
        self._finalizer = weakref.finalize(self, _close_conn, self._conn)
        self._init_db()
        if self._timer_refresher is not None:
            self.refresh_all_timers()

    def _open_connection(self):
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA busy_timeout=5000')
        return conn

    def _get_connection(self):
        """Return the persistent SQLite connection (must be called under self.lock)."""
        if self._conn is None:
            self._conn = self._open_connection()
            self._finalizer = weakref.finalize(self, _close_conn, self._conn)
        return self._conn

    def close(self):
        """Close the persistent SQLite connection."""
        with self.lock:
            conn = self._conn
            self._conn = None
            if self._finalizer is not None:
                self._finalizer.detach()
                self._finalizer = None
            _close_conn(conn)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def refresh_all_timers(self, now=None, refresher=None):
        """Reconcile persisted wall-clock timers across all characters on DB load / startup."""
        fn = refresher or self._timer_refresher
        now = time.time() if now is None else float(now)
        changed = False
        expired_deletes = []
        for account, char in self.all_characters():
            del_ts = char.get('delete_time')
            if del_ts and float(del_ts) <= now:
                expired_deletes.append((account, char['id']))
                continue
            if fn is not None and fn(char, now=now):
                changed = True
        for account, char_id in expired_deletes:
            self.delete(account, char_id)
        if changed:
            self.save()

    @property
    def path(self):
        return self.db_path

    @property
    def next_id(self) -> int:
        with self.lock:
            conn = self._get_connection()
            row = conn.execute('SELECT value FROM meta WHERE key = "next_id"').fetchone()
            return int(row['value']) if row else 1

    def all_characters(self) -> list:
        with self.lock:
            conn = self._get_connection()
            rows = conn.execute('SELECT account, id, data_json FROM characters ORDER BY id').fetchall()
            result = []
            for r in rows:
                key = (r['account'], r['id'])
                if key in self._cache:
                    result.append((r['account'], self._cache[key]))
                else:
                    char_dict = json.loads(r['data_json'])
                    self._cache[key] = char_dict
                    result.append((r['account'], char_dict))
            return result

    def _init_db(self):
        with self.lock:
            conn = self._get_connection()
            conn.execute('''
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS characters (
                    id INTEGER PRIMARY KEY,
                    account TEXT NOT NULL,
                    name TEXT NOT NULL COLLATE NOCASE,
                    char_class INTEGER NOT NULL,
                    level INTEGER NOT NULL DEFAULT 1,
                    data_json TEXT NOT NULL
                )
            ''')
            # Accounts register on first login (5386); OfflinePlayer keeps uid 1.
            conn.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    uid INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    created REAL NOT NULL
                )
            ''')
            conn.execute('INSERT OR IGNORE INTO accounts (uid, name, created) '
                         'VALUES (1, "OfflinePlayer", strftime("%s","now"))')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_char_account ON characters(account)')
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_char_name ON characters(name)')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS mailbox (
                    uid INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipient_char_id INTEGER NOT NULL,
                    sender_char_id INTEGER NOT NULL,
                    sender_name TEXT NOT NULL,
                    post_type INTEGER NOT NULL DEFAULT 0,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    gold INTEGER NOT NULL DEFAULT 0,
                    extra INTEGER NOT NULL DEFAULT 0,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    has_item INTEGER NOT NULL DEFAULT 0,
                    can_return INTEGER NOT NULL DEFAULT 1,
                    remain_days INTEGER NOT NULL DEFAULT 30,
                    send_time INTEGER NOT NULL,
                    items_json TEXT NOT NULL DEFAULT '[]',
                    is_deleted INTEGER NOT NULL DEFAULT 0
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_mail_recipient ON mailbox(recipient_char_id, is_deleted)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_mail_sender ON mailbox(sender_char_id, is_deleted)')
            row = conn.execute('SELECT value FROM meta WHERE key = "next_id"').fetchone()
            if not row:
                conn.execute('INSERT INTO meta (key, value) VALUES ("next_id", "1")')
            conn.commit()

    def _get_next_id(self, conn) -> int:
        val = int(conn.execute('SELECT value FROM meta WHERE key = "next_id"').fetchone()['value'])
        conn.execute('UPDATE meta SET value = ? WHERE key = "next_id"', (str(val + 1),))
        return val

    def account_uid(self, account: str) -> int:
        """The account's uid, registering the name on its first login."""
        with self.lock:
            conn = self._get_connection()
            conn.execute('INSERT OR IGNORE INTO accounts (name, created) VALUES (?, strftime("%s","now"))',
                         (account,))
            conn.commit()
            row = conn.execute('SELECT uid FROM accounts WHERE name = ?', (account,)).fetchone()
            return int(row['uid'])

    def accounts(self) -> list:
        with self.lock:
            conn = self._get_connection()
            return [(r['uid'], r['name']) for r in conn.execute('SELECT uid, name FROM accounts ORDER BY uid')]

    def characters(self, account: str) -> list:
        with self.lock:
            conn = self._get_connection()
            rows = conn.execute(
                'SELECT id, data_json FROM characters WHERE account = ? ORDER BY id', (account,)
            ).fetchall()
            result = []
            for r in rows:
                char_id = r['id']
                key = (account, char_id)
                if key in self._cache:
                    result.append(self._cache[key])
                else:
                    char_dict = json.loads(r['data_json'])
                    self._cache[key] = char_dict
                    result.append(char_dict)
            return result

    def get(self, account: str, char_id: int):
        with self.lock:
            key = (account, char_id)
            if key in self._cache:
                return self._cache[key]
            conn = self._get_connection()
            row = conn.execute(
                'SELECT data_json FROM characters WHERE account = ? AND id = ?', (account, char_id)
            ).fetchone()
            if row:
                char_dict = json.loads(row['data_json'])
                self._cache[key] = char_dict
                return char_dict
            return None

    def get_by_id(self, char_id: int):
        """Indexed lookup of a character across all accounts by char_id. Returns (account, char) or (None, None)."""
        with self.lock:
            for (acc, cid), cached in self._cache.items():
                if cid == char_id:
                    return acc, cached
            conn = self._get_connection()
            row = conn.execute(
                'SELECT account, id, data_json FROM characters WHERE id = ?', (char_id,)
            ).fetchone()
            if not row:
                return None, None
            key = (row['account'], row['id'])
            char_dict = json.loads(row['data_json'])
            self._cache[key] = char_dict
            return row['account'], char_dict

    def get_by_name(self, name: str):
        """Case-insensitive indexed lookup by character name. Returns (account, char) or (None, None)."""
        if not name:
            return None, None
        target = name.lower()
        with self.lock:
            for (acc, _), cached in self._cache.items():
                if (cached.get('name') or '').lower() == target:
                    return acc, cached
            conn = self._get_connection()
            row = conn.execute(
                'SELECT account, id, data_json FROM characters WHERE name = ?', (name,)
            ).fetchone()
            if not row:
                return None, None
            key = (row['account'], row['id'])
            if key in self._cache:
                return row['account'], self._cache[key]
            char_dict = json.loads(row['data_json'])
            self._cache[key] = char_dict
            return row['account'], char_dict

    def create(self, account: str, request: dict):
        with self.lock:
            conn = self._get_connection()
            name = request['name'].strip()
            if conn.execute('SELECT id FROM characters WHERE name = ?', (name,)).fetchone():
                return None
            char_id = self._get_next_id(conn)
            char = dict(request, id=char_id, name=name, level=1, tutorial_cleared=False)
            ensure_inventory(char)
            conn.execute(
                'INSERT INTO characters (id, account, name, char_class, level, data_json) VALUES (?, ?, ?, ?, ?, ?)',
                (char_id, account, name, char.get('char_class', 1), char.get('level', 1), json.dumps(char))
            )
            conn.commit()
            self._cache[(account, char_id)] = char
            return char

    def delete(self, account: str, char_id: int) -> bool:
        with self.lock:
            conn = self._get_connection()
            self._cache.pop((account, char_id), None)
            cur = conn.execute('DELETE FROM characters WHERE account = ? AND id = ?', (account, char_id))
            conn.commit()
            return cur.rowcount > 0

    def save_char(self, account: str, char_id: int):
        """Persist a single cached character to SQLite without rewriting unrelated characters."""
        with self.lock:
            char = self._cache.get((account, char_id))
            if char is None:
                return
            conn = self._get_connection()
            conn.execute(
                'UPDATE characters SET name = ?, char_class = ?, level = ?, data_json = ? '
                'WHERE account = ? AND id = ?',
                (char['name'], char.get('char_class', 1), char.get('level', 1),
                 json.dumps(char), account, char_id),
            )
            conn.commit()

    def rename_character(self, account: str, char: dict, new_name: str) -> bool:
        """Persist a unique name before updating the live character record."""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    'UPDATE characters SET name = ?, data_json = ? WHERE account = ? AND id = ?',
                    (new_name, json.dumps(dict(char, name=new_name)), account, char['id']),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                return False
            if not cursor.rowcount:
                return False
            char['name'] = new_name
            return True

    def save_chars(self, pairs):
        """Atomically persist a specific set of (account, char_id) pairs in one transaction."""
        with self.lock, self._get_connection() as conn:
            for account, char_id in pairs:
                char = self._cache.get((account, char_id))
                if char is None:
                    continue
                conn.execute(
                    'UPDATE characters SET name = ?, char_class = ?, level = ?, data_json = ? '
                    'WHERE account = ? AND id = ?',
                    (char.get('name', ''), char.get('char_class', 1), char.get('level', 1),
                     json.dumps(char), account, char_id),
                )

    def save(self):
        """Persist all active cached character changes to SQLite atomically."""
        with self.lock:
            conn = self._get_connection()
            for (account, char_id), char in list(self._cache.items()):
                conn.execute(
                    'UPDATE characters SET name = ?, char_class = ?, level = ?, data_json = ? WHERE account = ? AND id = ?',
                    (char.get('name', ''), char.get('char_class', 1), char.get('level', 1),
                     json.dumps(char), account, char_id)
                )
            conn.commit()

    def update(self, account: str, char: dict):
        """Update serialized record of a character."""
        with self.lock:
            char_id = char.get('id')
            if not char_id:
                return
            self._cache[(account, char_id)] = char
            conn = self._get_connection()
            conn.execute(
                'UPDATE characters SET name = ?, char_class = ?, level = ?, data_json = ? WHERE account = ? AND id = ?',
                (char.get('name', ''), char.get('char_class', 1), char.get('level', 1),
                 json.dumps(char), account, char_id)
            )
            conn.commit()

    # Account values (cash shop balance). Read from SQLite on every call, not
    # cached, so changes made by tools/launcher/dashboard.py (a separate process)
    # reach the running server.
    def account_cash(self, account: str) -> int:
        with self.lock:
            conn = self._get_connection()
            row = conn.execute('SELECT value FROM meta WHERE key = ?', ('cash:' + account,)).fetchone()
            return int(row['value']) if row else 0

    def set_account_cash(self, account: str, amount: int) -> int:
        amount = max(0, min(int(amount), 2 ** 63 - 1))
        with self.lock:
            conn = self._get_connection()
            conn.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', ('cash:' + account, str(amount)))
            conn.commit()
        return amount

    def add_account_cash(self, account: str, delta: int) -> int:
        return self.set_account_cash(account, self.account_cash(account) + int(delta))

    # --- Mailbox / Post Persistence ---

    def get_mail_inbox(self, char_id: int) -> list:
        with self.lock:
            conn = self._get_connection()
            rows = conn.execute(
                'SELECT * FROM mailbox WHERE recipient_char_id = ? AND is_deleted = 0 ORDER BY uid DESC',
                (char_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_mail_outbox(self, char_id: int) -> list:
        with self.lock:
            conn = self._get_connection()
            rows = conn.execute(
                'SELECT * FROM mailbox WHERE sender_char_id = ? AND is_deleted = 0 ORDER BY uid DESC',
                (char_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def send_mail(self, sender_char_id: int, sender_name: str, recipient_char_id: int,
                  title: str, content: str = '', gold: int = 0, extra: int = 0,
                  items: list = None, post_type: int = 0) -> int:
        items_json = json.dumps(items or [])
        has_item = 1 if (items and len(items) > 0) or gold > 0 else 0
        send_time = int(time.time())
        with self.lock:
            conn = self._get_connection()
            cur = conn.execute('''
                INSERT INTO mailbox (
                    recipient_char_id, sender_char_id, sender_name, post_type,
                    title, content, gold, extra, is_read, has_item, can_return,
                    remain_days, send_time, items_json, is_deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 1, 30, ?, ?, 0)
            ''', (recipient_char_id, sender_char_id, sender_name, post_type,
                  title, content, gold, extra, has_item, send_time, items_json))
            conn.commit()
            return cur.lastrowid

    def read_mail(self, mail_uid: int) -> bool:
        with self.lock:
            conn = self._get_connection()
            cur = conn.execute('UPDATE mailbox SET is_read = 1 WHERE uid = ?', (mail_uid,))
            conn.commit()
            return cur.rowcount > 0

    def claim_mail_append(self, mail_uid: int, *, recipient_char_id: int,
                          available_slots: int) -> Optional[tuple]:
        """Claim the contents together, or return None if the items do not fit."""
        with self.lock:
            conn = self._get_connection()
            row = conn.execute(
                'SELECT gold, items_json FROM mailbox '
                'WHERE uid = ? AND recipient_char_id = ? AND is_deleted = 0',
                (mail_uid, recipient_char_id),
            ).fetchone()
            if not row:
                return 0, []
            items = json.loads(row['items_json'])
            if len(items) > available_slots:
                return None
            conn.execute('UPDATE mailbox SET gold = 0, items_json = "[]", has_item = 0 WHERE uid = ?', (mail_uid,))
            conn.commit()
            return int(row['gold']), items

    def claim_mail_gold(self, mail_uid: int) -> int:
        with self.lock:
            conn = self._get_connection()
            row = conn.execute(
                'SELECT gold, items_json FROM mailbox WHERE uid = ? AND is_deleted = 0', (mail_uid,)
            ).fetchone()
            if not row:
                return 0
            gold = int(row['gold'])
            items = json.loads(row['items_json'])
            has_item = 1 if items else 0
            conn.execute('UPDATE mailbox SET gold = 0, has_item = ? WHERE uid = ?', (has_item, mail_uid))
            conn.commit()
            return gold

    def save_mail(self, mail_uid: int) -> bool:
        with self.lock:
            conn = self._get_connection()
            cur = conn.execute(
                'UPDATE mailbox SET remain_days = 90, is_read = 1 WHERE uid = ? AND is_deleted = 0', (mail_uid,)
            )
            conn.commit()
            return cur.rowcount > 0

    def delete_mail(self, mail_uids: list) -> list:
        if not mail_uids:
            return []
        with self.lock:
            conn = self._get_connection()
            placeholders = ','.join('?' for _ in mail_uids)
            conn.execute(f'UPDATE mailbox SET is_deleted = 1 WHERE uid IN ({placeholders})', mail_uids)
            conn.commit()
            return list(mail_uids)

    def return_mail(self, mail_uid: int, recipient_char_id: int) -> bool:
        with self.lock:
            conn = self._get_connection()
            row = conn.execute(
                'SELECT recipient_char_id, sender_char_id FROM mailbox '
                'WHERE uid = ? AND recipient_char_id = ? AND is_deleted = 0 AND can_return = 1',
                (mail_uid, recipient_char_id),
            ).fetchone()
            if not row:
                return False
            rec = row['recipient_char_id']
            snd = row['sender_char_id']
            conn.execute(
                '''UPDATE mailbox SET recipient_char_id = ?, sender_char_id = ?,
                       sender_name = COALESCE((SELECT name FROM characters WHERE id = ?), sender_name),
                       post_type = 2, can_return = 0, is_read = 0
                   WHERE uid = ?''',
                (snd, rec, rec, mail_uid),
            )
            conn.commit()
            return True
