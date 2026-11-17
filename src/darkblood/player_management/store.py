"""Character storage: the ICharacterStore interface and its SQLite backend."""
import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from darkblood import REPO_ROOT
from darkblood.player_management.characters import DATA, ensure_inventory


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


class SqliteCharacterStore(ICharacterStore):
    """SQLite character store (data/darkblood.db); records are JSON documents per character."""

    def __init__(self, db_path=None):
        self.db_path = Path(db_path or DATA / 'darkblood.db')
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._cache = {}  # (account, char_id) -> dict
        self._init_db()

    @property
    def path(self):
        return self.db_path

    @property
    def next_id(self) -> int:
        with self.lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT value FROM meta WHERE key = "next_id"')
            row = cur.fetchone()
            return int(row['value']) if row else 1

    def all_characters(self) -> list:
        with self.lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT account, id, data_json FROM characters ORDER BY id')
            rows = cur.fetchall()
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

    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.lock, self._get_connection() as conn:
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
            cur = conn.cursor()
            cur.execute('SELECT value FROM meta WHERE key = "next_id"')
            row = cur.fetchone()
            if not row:
                conn.execute('INSERT INTO meta (key, value) VALUES ("next_id", "1")')
            conn.commit()

    def _get_next_id(self, conn) -> int:
        cur = conn.cursor()
        cur.execute('SELECT value FROM meta WHERE key = "next_id"')
        val = int(cur.fetchone()['value'])
        conn.execute('UPDATE meta SET value = ? WHERE key = "next_id"', (str(val + 1),))
        return val

    def account_uid(self, account: str) -> int:
        """The account's uid, registering the name on its first login."""
        with self.lock, self._get_connection() as conn:
            conn.execute('INSERT OR IGNORE INTO accounts (name, created) VALUES (?, strftime("%s","now"))',
                         (account,))
            conn.commit()
            row = conn.execute('SELECT uid FROM accounts WHERE name = ?', (account,)).fetchone()
            return int(row['uid'])

    def accounts(self) -> list:
        with self.lock, self._get_connection() as conn:
            return [(r['uid'], r['name']) for r in conn.execute('SELECT uid, name FROM accounts ORDER BY uid')]

    def characters(self, account: str) -> list:
        with self.lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT id, data_json FROM characters WHERE account = ? ORDER BY id', (account,))
            rows = cur.fetchall()
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
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute('SELECT data_json FROM characters WHERE account = ? AND id = ?', (account, char_id))
                row = cur.fetchone()
                if row:
                    char_dict = json.loads(row['data_json'])
                    self._cache[key] = char_dict
                    return char_dict
                return None

    def create(self, account: str, request: dict):
        with self.lock, self._get_connection() as conn:
            name = request['name'].strip()
            cur = conn.cursor()
            cur.execute('SELECT id FROM characters WHERE name = ?', (name,))
            if cur.fetchone():
                return None
            char_id = self._get_next_id(conn)
            char = dict(request, id=char_id, level=1, tutorial_cleared=False)
            ensure_inventory(char)
            conn.execute(
                'INSERT INTO characters (id, account, name, char_class, level, data_json) VALUES (?, ?, ?, ?, ?, ?)',
                (char_id, account, name, char.get('char_class', 1), char.get('level', 1), json.dumps(char))
            )
            conn.commit()
            self._cache[(account, char_id)] = char
            return char

    def delete(self, account: str, char_id: int) -> bool:
        with self.lock, self._get_connection() as conn:
            self._cache.pop((account, char_id), None)
            cur = conn.cursor()
            cur.execute('DELETE FROM characters WHERE account = ? AND id = ?', (account, char_id))
            conn.commit()
            return cur.rowcount > 0

    def save(self):
        """Persist all active cached character changes to SQLite atomically."""
        with self.lock, self._get_connection() as conn:
            for (account, char_id), char in list(self._cache.items()):
                conn.execute(
                    'UPDATE characters SET name = ?, char_class = ?, level = ?, data_json = ? WHERE account = ? AND id = ?',
                    (char.get('name', ''), char.get('char_class', 1), char.get('level', 1), json.dumps(char), account, char_id)
                )
            conn.commit()

    def update(self, account: str, char: dict):
        """Update serialized record of a character."""
        with self.lock, self._get_connection() as conn:
            char_id = char.get('id')
            if not char_id:
                return
            self._cache[(account, char_id)] = char
            conn.execute(
                'UPDATE characters SET name = ?, char_class = ?, level = ?, data_json = ? WHERE account = ? AND id = ?',
                (char.get('name', ''), char.get('char_class', 1), char.get('level', 1), json.dumps(char), account, char_id)
            )
            conn.commit()

    # Account values (cash shop balance). Read from SQLite on every call, not
    # cached, so changes made by tools/dashboard.py (a separate process)
    # reach the running server.
    def account_cash(self, account: str) -> int:
        with self.lock, self._get_connection() as conn:
            row = conn.execute('SELECT value FROM meta WHERE key = ?', ('cash:' + account,)).fetchone()
            return int(row['value']) if row else 0

    def set_account_cash(self, account: str, amount: int) -> int:
        amount = max(0, min(int(amount), 2 ** 63 - 1))
        with self.lock, self._get_connection() as conn:
            conn.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', ('cash:' + account, str(amount)))
            conn.commit()
        return amount

    def add_account_cash(self, account: str, delta: int) -> int:
        return self.set_account_cash(account, self.account_cash(account) + int(delta))
