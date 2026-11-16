"""Character Storage Abstraction: JSON & SQLite Backends.

Provides an abstract store interface with JsonCharacterStore and SqliteCharacterStore,
enabling robust ACID transactions, querying, and seamless migration between formats.
"""
import json
import os
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


class JsonCharacterStore(ICharacterStore):
    """JSON file backed character store."""

    def __init__(self, path=None):
        self.path = Path(path or DATA / 'characters.json')
        self.lock = threading.Lock()
        try:
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.data = {'version': 1, 'next_id': 1, 'accounts': {}}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.data, indent=2), encoding='utf-8')
        os.replace(tmp, self.path)

    def characters(self, account: str) -> list:
        return self.data['accounts'].get(account, [])

    def get(self, account: str, char_id: int):
        for c in self.characters(account):
            if c['id'] == char_id:
                return c
        return None

    def delete(self, account: str, char_id: int) -> bool:
        with self.lock:
            chars = self.data['accounts'].get(account, [])
            for i, c in enumerate(chars):
                if c['id'] == char_id:
                    del chars[i]
                    self.save()
                    return True
            return False

    def create(self, account: str, request: dict):
        with self.lock:
            chars = self.data['accounts'].setdefault(account, [])
            if any(c['name'].lower() == request['name'].lower()
                   for acc in self.data['accounts'].values() for c in acc):
                return None
            char = dict(request, id=self.data['next_id'], level=1, tutorial_cleared=False)
            self.data['next_id'] += 1
            ensure_inventory(char)
            chars.append(char)
            self.save()
            return char

    @property
    def next_id(self) -> int:
        return self.data.get('next_id', 1)

    def all_characters(self) -> list:
        result = []
        for acc, chars in self.data.get('accounts', {}).items():
            for c in chars:
                result.append((acc, c))
        return result


class SqliteCharacterStore(ICharacterStore):
    """SQLite relational backend for characters with ACID durability and JSON migration."""

    def __init__(self, db_path=None):
        self.db_path = Path(db_path or DATA / 'darkblood.db')
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._cache = {}  # (account, char_id) -> dict
        self._init_db()
        self._auto_import_if_empty()

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

    def _auto_import_if_empty(self):
        """Auto-migrate legacy characters.json if sqlite database is brand new."""
        json_path = DATA / 'characters.json'
        if json_path.exists():
            with self.lock, self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute('SELECT COUNT(*) FROM characters')
                count = cur.fetchone()[0]
                if count == 0:
                    self.import_from_json(json_path)

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

    def import_from_json(self, json_path: Path):
        """Import all accounts and characters from a JSON character store."""
        if not json_path.exists():
            return
        data = json.loads(json_path.read_text(encoding='utf-8'))
        with self.lock, self._get_connection() as conn:
            next_id = data.get('next_id', 1)
            conn.execute('UPDATE meta SET value = ? WHERE key = "next_id"', (str(next_id),))
            for acc, chars in data.get('accounts', {}).items():
                for c in chars:
                    conn.execute(
                        'INSERT OR REPLACE INTO characters (id, account, name, char_class, level, data_json) VALUES (?, ?, ?, ?, ?, ?)',
                        (c['id'], acc, c['name'], c.get('char_class', 1), c.get('level', 1), json.dumps(c))
                    )
            conn.commit()

    def export_to_json(self, json_path: Path):
        """Export current database to JSON format."""
        with self.lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT value FROM meta WHERE key = "next_id"')
            next_id = int(cur.fetchone()['value'])
            cur.execute('SELECT account, data_json FROM characters ORDER BY id')
            accounts = {}
            for r in cur.fetchall():
                accounts.setdefault(r['account'], []).append(json.loads(r['data_json']))
            payload = {'version': 1, 'next_id': next_id, 'accounts': accounts}
            json_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
