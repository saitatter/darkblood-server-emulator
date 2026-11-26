#!/usr/bin/env python3
"""Dark Blood Server Emulator - Web Dashboard & Administration Tool.

Provides real-time server telemetry, character management, opcode exploration,
and GM diagnostics through a modern, standalone web UI.
"""
import argparse
import html
import json
import os
import socket
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Ensure darkblood package is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / 'src'))

from darkblood.player_management.store import SqliteCharacterStore

DEFAULT_ACCOUNT = 'OfflinePlayer'  # single local account (Steam shim persona)


CLASS_NAMES = {
    1: 'Warrior (Slayer)',
    2: 'Knight (Paladin)',
    3: 'Hunter (Shooter)',
    4: 'Thief (Assassin)',
    5: 'Breaker',
    6: 'Mage'
}


def probe_socket(host: str, port: int, timeout: float = 0.5) -> dict:
    """Check if a TCP port is open and measure response latency."""
    start = time.perf_counter()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        sock.close()
        return {'open': True, 'latency_ms': round(elapsed_ms, 2)}
    except (socket.timeout, ConnectionRefusedError, OSError):
        return {'open': False, 'latency_ms': None}


def load_opcodes_tsv() -> list:
    """Load opcode definitions from assets/opcodes.tsv."""
    tsv_path = REPO_ROOT / 'assets' / 'opcodes.tsv'
    opcodes = []
    if not tsv_path.exists():
        return opcodes

    # Known implemented opcodes in the emulator
    implemented = {
        2006, 2007, 2012, 2013, 2018, 2019, 2021, 2022, 2023, 2024, 2028, 2030,
        2031, 2036, 2037, 2038, 2039, 2040, 2041, 2042, 2043, 2044, 2045, 2046,
        2047, 2048, 2049, 2065, 2066, 2073, 2074, 2075, 2076, 2080, 2082, 2085,
        2092, 2102, 2109, 2111, 2112, 2118, 2119, 2120, 2130, 2131, 2132, 2133,
        2137, 2138, 2139, 2140, 2141, 2142, 2148, 2149, 2150, 2151, 2152, 2153,
        2154, 2155, 2157, 2158, 2164, 2165, 2170, 2171, 2179, 2180, 2181, 2182,
        2183, 2184, 2185, 2186, 2187, 2188, 2189, 2190, 2196, 2200, 2201, 2202,
        2203, 2205, 2216, 2217, 2220, 2221, 2222, 2223, 2224, 2225, 2227, 2228,
        2229, 2230, 2231, 2234, 2235, 2245, 2246, 2247, 2248, 2249, 2250, 2251,
        2252, 2253, 2254, 2255, 2256, 2257, 2280, 2283, 2286, 2304, 2305, 2321,
        2322, 2327, 2328, 2335, 2336, 2348, 2349, 2350, 2351, 2362, 2363, 2364,
        2365, 2369, 2370, 2390, 2391, 2400, 2401, 2402, 2403, 2406, 2407, 2437,
        2438, 2442, 2443, 2451, 2452, 2457, 2458, 2470, 2471, 2475, 2476, 2477,
        2478, 2479, 2480, 2484, 2485, 2488, 2489, 2490, 2491, 2492, 2493, 2494,
        2495, 2500, 2501, 2516, 2517, 2518, 2519, 2523, 2524, 2536, 2537, 2538,
        2539, 2571, 2572, 2573, 2574, 2576, 2577, 2578, 2579, 2580, 2581, 2582,
        2630, 2631, 2676, 2677, 2697, 2698, 2709, 2710, 5096, 5114, 5117, 5118,
        5119, 5122, 5123, 5165, 5166, 5256, 5257, 5258, 5259, 5260, 5261, 5344,
        5345, 5346, 5351, 5352, 5353, 5354, 5355, 5362, 5363, 5364, 5365, 5366,
        5367, 6011, 6012, 6028, 6029
    }

    try:
        with open(tsv_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '\t' not in line:
                    continue
                parts = line.split('\t', 1)
                try:
                    opcode_id = int(parts[0])
                except ValueError:
                    continue
                name = parts[1]
                domain = name.split('_')[0] if '_' in name else 'OTHER'
                opcodes.append({
                    'id': opcode_id,
                    'hex': f'0x{opcode_id:04X}',
                    'name': name,
                    'domain': domain,
                    'implemented': opcode_id in implemented
                })
    except Exception as e:
        print(f"Error loading opcodes: {e}", file=sys.stderr)
    return opcodes


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for Dashboard API and Frontend."""

    store = SqliteCharacterStore()
    opcodes_cache = load_opcodes_tsv()

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path

        if path == '/' or path == '/index.html':
            self.serve_html()
        elif path == '/api/status':
            self.serve_api_status()
        elif path == '/api/characters':
            self.serve_api_characters()
        elif path.startswith('/api/character/'):
            char_id_str = path.split('/')[-1]
            try:
                char_id = int(char_id_str)
                self.serve_api_character_detail(char_id)
            except ValueError:
                self.send_error(400, 'Invalid character ID')
        elif path == '/api/opcodes':
            self.serve_api_opcodes(parse_qs(url.query))
        elif path == '/api/account/cash':
            self.serve_account_cash(parse_qs(url.query).get('account', [DEFAULT_ACCOUNT])[0])
        else:
            self.send_error(404, 'Not Found')

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length > 0 else b'{}'
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            data = {}

        if path.startswith('/api/character/') and path.endswith('/modify'):
            parts = path.split('/')
            try:
                char_id = int(parts[3])
                self.handle_character_modify(char_id, data)
            except (IndexError, ValueError):
                self.send_error(400, 'Invalid character ID')
        elif path == '/api/test_probe':
            self.handle_test_probe(data)
        elif path == '/api/account/cash':
            self.handle_account_cash(data)
        else:
            self.send_error(404, 'Endpoint Not Found')

    def do_DELETE(self):
        url = urlparse(self.path)
        path = url.path
        if path.startswith('/api/character/'):
            try:
                char_id = int(path.split('/')[-1])
                self.handle_character_delete(char_id)
            except ValueError:
                self.send_error(400, 'Invalid character ID')
        else:
            self.send_error(404, 'Endpoint Not Found')

    def send_json(self, data, code=200):
        payload = json.dumps(data, indent=2).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(payload)

    def serve_api_status(self):
        game_probe = probe_socket('127.0.0.1', 9400)
        relay_probe = probe_socket('127.0.0.1', 9401)
        
        all_chars = self.store.all_characters()
        accounts = set(acc for acc, _ in all_chars)

        status = {
            'servers': {
                'game': {
                    'name': 'Dark Blood Game Server',
                    'endpoint': '127.0.0.1:9400',
                    'status': 'ONLINE' if game_probe['open'] else 'OFFLINE',
                    'latency_ms': game_probe['latency_ms']
                },
                'relay': {
                    'name': 'Dark Blood Relay Server',
                    'endpoint': '127.0.0.1:9401',
                    'status': 'ONLINE' if relay_probe['open'] else 'OFFLINE',
                    'latency_ms': relay_probe['latency_ms']
                }
            },
            'database': {
                'type': 'SQLite Primary Backend',
                'path': str(self.store.path),
                'total_accounts': len(accounts),
                'total_characters': len(all_chars),
                'next_id': getattr(self.store, 'next_id', 1)
            },
            'opcodes': {
                'total_discovered': len(self.opcodes_cache),
                'implemented': sum(1 for op in self.opcodes_cache if op['implemented'])
            },
            'system': {
                'python_version': sys.version.split()[0],
                'platform': sys.platform,
                'repo_root': str(REPO_ROOT)
            }
        }
        self.send_json(status)

    def serve_api_characters(self):
        result = []
        for acc, c in self.store.all_characters():
            result.append({
                'id': c.get('id'),
                'account': acc,
                'name': c.get('name', 'Unknown'),
                'class_id': c.get('char_class', 1),
                'class_name': CLASS_NAMES.get(c.get('char_class', 1), f"Class {c.get('char_class')}"),
                'level': c.get('level', 1),
                'tutorial_cleared': c.get('tutorial_cleared', False),
                'item_count': len(c.get('items', [])),
                'quests_active': len(c.get('quests_active', {})),
                'quests_done': len(c.get('quests_done', []))
            })
        self.send_json(result)

    def serve_api_character_detail(self, char_id: int):
        for acc, c in self.store.all_characters():
            if c.get('id') == char_id:
                detail = dict(c)
                detail['account'] = acc
                detail['class_name'] = CLASS_NAMES.get(c.get('char_class', 1), f"Class {c.get('char_class')}")
                self.send_json(detail)
                return
        self.send_json({'error': 'Character not found'}, code=404)

    def handle_character_modify(self, char_id: int, updates: dict):
        found = False
        for acc, c in self.store.all_characters():
            if c.get('id') == char_id:
                if 'level' in updates:
                    c['level'] = max(1, min(60, int(updates['level'])))
                if 'name' in updates and updates['name'].strip():
                    c['name'] = updates['name'].strip()
                if 'tutorial_cleared' in updates:
                    c['tutorial_cleared'] = bool(updates['tutorial_cleared'])
                if 'gold' in updates:
                    c['gold'] = max(0, int(updates['gold']))
                if hasattr(self.store, 'update'):
                    self.store.update(acc, c)
                else:
                    self.store.save()
                found = True
                break
        if found:
            self.send_json({'success': True, 'char_id': char_id})
        else:
            self.send_json({'error': 'Character not found'}, code=404)

    def serve_account_cash(self, account: str):
        self.send_json({'account': account, 'cash': self.store.account_cash(account)})

    def handle_account_cash(self, data: dict):
        """Cheat: change the cash shop balance (2370 u64 cash) of an account.

        {"add": n} adds (negative subtracts), {"set": n} replaces. The game
        server reads the value on every 2369, e.g. when the cash shop opens.
        """
        account = str(data.get('account') or DEFAULT_ACCOUNT)
        try:
            if 'set' in data:
                cash = self.store.set_account_cash(account, int(data['set']))
            else:
                cash = self.store.add_account_cash(account, int(data.get('add', 0)))
        except (TypeError, ValueError):
            self.send_json({'error': 'amount must be an integer'}, code=400)
            return
        self.send_json({'success': True, 'account': account, 'cash': cash})

    def handle_character_delete(self, char_id: int):
        for acc, c in self.store.all_characters():
            if c.get('id') == char_id:
                self.store.delete(acc, char_id)
                self.send_json({'success': True, 'deleted_id': char_id})
                return
        self.send_json({'error': 'Character not found'}, code=404)

    def serve_api_opcodes(self, query_params: dict):
        search = query_params.get('q', [''])[0].lower()
        domain = query_params.get('domain', [''])[0].upper()
        only_impl = query_params.get('implemented', [''])[0].lower() == 'true'

        filtered = []
        for op in self.opcodes_cache:
            if domain and op['domain'] != domain:
                continue
            if only_impl and not op['implemented']:
                continue
            if search:
                if (search not in op['name'].lower() and
                    search not in str(op['id']) and
                    search not in op['hex'].lower()):
                    continue
            filtered.append(op)
        self.send_json(filtered[:500])

    def handle_test_probe(self, data: dict):
        target = data.get('target', 'game')
        port = 9400 if target == 'game' else 9401
        res = probe_socket('127.0.0.1', port, timeout=1.0)
        self.send_json({
            'target': target,
            'port': port,
            'reachable': res['open'],
            'latency_ms': res['latency_ms']
        })

    def serve_html(self):
        html_content = DASHBOARD_HTML
        payload = html_content.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        # Silent dashboard logging to keep console clean
        pass


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dark Blood Server Emulator - GM Dashboard</title>
  <style>
    :root {
      --bg: #0f1013;
      --card-bg: #16181e;
      --card-border: #262934;
      --blood: #b31b1b;
      --blood-glow: rgba(179, 27, 27, 0.35);
      --gold: #d4af37;
      --text: #e1e3ea;
      --text-muted: #8c90a0;
      --online: #2ecc71;
      --offline: #e74c3c;
      --code-bg: #0a0b0e;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: linear-gradient(180deg, #1f0808 0%, #16181e 100%);
      border-bottom: 2px solid var(--blood);
      padding: 18px 32px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .brand h1 {
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: #fff;
    }
    .brand h1 span { color: var(--blood); }
    .nav-tabs {
      display: flex;
      gap: 8px;
    }
    .nav-btn {
      background: transparent;
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      padding: 8px 18px;
      border-radius: 6px;
      cursor: pointer;
      font-weight: 600;
      font-size: 14px;
      transition: all 0.2s ease;
    }
    .nav-btn:hover {
      color: #fff;
      border-color: var(--blood);
    }
    .nav-btn.active {
      background: var(--blood);
      color: #fff;
      border-color: var(--blood);
      box-shadow: 0 0 12px var(--blood-glow);
    }
    main {
      flex: 1;
      padding: 28px 32px;
      max-width: 1400px;
      margin: 0 auto;
      width: 100%;
    }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    
    /* Grid cards */
    .grid-cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 20px;
      margin-bottom: 28px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
    .card h3 {
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: var(--text-muted);
      margin-bottom: 10px;
    }
    .card .value {
      font-size: 28px;
      font-weight: 700;
      color: #fff;
    }
    .badge {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .badge-online { background: rgba(46, 204, 113, 0.2); color: var(--online); border: 1px solid var(--online); }
    .badge-offline { background: rgba(231, 76, 60, 0.2); color: var(--offline); border: 1px solid var(--offline); }
    .badge-gold { background: rgba(212, 175, 55, 0.2); color: var(--gold); border: 1px solid var(--gold); }

    /* Tables */
    .table-container {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th {
      background: #121419;
      color: var(--text-muted);
      font-weight: 600;
      text-align: left;
      padding: 14px 16px;
      border-bottom: 1px solid var(--card-border);
    }
    td {
      padding: 14px 16px;
      border-bottom: 1px solid var(--card-border);
      color: var(--text);
    }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(255,255,255,0.02); }

    /* Buttons & Inputs */
    .btn {
      background: var(--blood);
      color: #fff;
      border: none;
      padding: 8px 14px;
      border-radius: 4px;
      cursor: pointer;
      font-weight: 600;
      font-size: 13px;
      transition: all 0.2s;
    }
    .btn:hover { background: #d02222; }
    .btn-secondary {
      background: #232733;
      border: 1px solid var(--card-border);
      color: var(--text);
    }
    .btn-secondary:hover { background: #2f3445; }
    .input-box {
      background: var(--code-bg);
      border: 1px solid var(--card-border);
      color: var(--text);
      padding: 8px 12px;
      border-radius: 4px;
      font-size: 14px;
      outline: none;
    }
    .input-box:focus { border-color: var(--blood); }

    /* Modal */
    .modal-overlay {
      display: none;
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.75);
      backdrop-filter: blur(4px);
      justify-content: center;
      align-items: center;
      z-index: 1000;
    }
    .modal-overlay.open { display: flex; }
    .modal {
      background: var(--card-bg);
      border: 1px solid var(--blood);
      border-radius: 8px;
      width: 90%;
      max-width: 600px;
      padding: 24px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.8);
    }
    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 12px;
    }
    .modal-header h2 { font-size: 18px; color: #fff; }
    .close-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 20px;
      cursor: pointer;
    }
    .modal-body { margin-bottom: 20px; }
    .form-group {
      margin-bottom: 14px;
    }
    .form-group label {
      display: block;
      color: var(--text-muted);
      font-size: 13px;
      margin-bottom: 6px;
    }
    .form-group input { width: 100%; }
    .modal-footer {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <h1>Dark <span>Blood</span> Server Emulator</h1>
      <span class="badge badge-gold">Admin Console</span>
    </div>
    <div class="nav-tabs">
      <button class="nav-btn active" onclick="switchTab('overview')">Overview</button>
      <button class="nav-btn" onclick="switchTab('characters')">Characters</button>
      <button class="nav-btn" onclick="switchTab('opcodes')">Opcode Directory</button>
      <button class="nav-btn" onclick="switchTab('diagnostics')">Diagnostics</button>
    </div>
  </header>

  <main>
    <!-- OVERVIEW TAB -->
    <div id="tab-overview" class="tab-content active">
      <div class="grid-cards">
        <div class="card">
          <h3>Game Server (TCP 9400)</h3>
          <div id="game-status" class="value"><span class="badge badge-offline">Checking...</span></div>
          <div id="game-latency" style="font-size: 13px; color: var(--text-muted); margin-top: 8px;">--</div>
        </div>
        <div class="card">
          <h3>Relay Server (TCP 9401)</h3>
          <div id="relay-status" class="value"><span class="badge badge-offline">Checking...</span></div>
          <div id="relay-latency" style="font-size: 13px; color: var(--text-muted); margin-top: 8px;">--</div>
        </div>
        <div class="card">
          <h3>Active Characters</h3>
          <div id="stat-chars" class="value">0</div>
          <div id="stat-accounts" style="font-size: 13px; color: var(--text-muted); margin-top: 8px;">Across 0 accounts</div>
        </div>
        <div class="card">
          <h3>Opcodes Implemented</h3>
          <div id="stat-opcodes" class="value">0</div>
          <div id="stat-opcodes-total" style="font-size: 13px; color: var(--text-muted); margin-top: 8px;">out of 0 discovered</div>
        </div>
      </div>

      <div class="card" style="margin-bottom: 24px;">
        <h3 style="margin-bottom: 16px;">Quick Actions & System Info</h3>
        <div style="display: flex; gap: 12px; flex-wrap: wrap;">
          <button class="btn btn-secondary" onclick="runProbe('game')">Probe Game Server</button>
          <button class="btn btn-secondary" onclick="runProbe('relay')">Probe Relay Server</button>
          <button class="btn btn-secondary" onclick="refreshData()">Refresh Telemetry</button>
        </div>
      </div>
    </div>

    <!-- CHARACTERS TAB -->
    <div id="tab-characters" class="tab-content">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
        <h2>Character Accounts</h2>
        <button class="btn" onclick="refreshCharacters()">Reload</button>
      </div>
      <div class="card" style="margin-bottom: 16px;">
        <h3 style="margin-top:0;">Cash Shop Balance (cheat)</h3>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
          <span>Account <b>OfflinePlayer</b>: <b id="cash-value">--</b> cash</span>
          <input type="number" id="cash-amount" class="input-box" value="10000" style="width:140px;">
          <button class="btn" onclick="changeCash('add')">Add</button>
          <button class="btn btn-secondary" onclick="changeCash('set')">Set</button>
          <button class="btn btn-secondary" onclick="changeCash('set', 0)">Reset</button>
        </div>
        <div style="font-size:13px; color:var(--text-muted); margin-top:8px;">
          The client asks for the balance (2369) when the cash shop opens; reopen it to see the new value.
        </div>
      </div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Account</th>
              <th>Name</th>
              <th>Class</th>
              <th>Level</th>
              <th>Tutorial</th>
              <th>Items</th>
              <th>Quests</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="char-table-body">
            <tr><td colspan="9" style="text-align:center;">Loading characters...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- OPCODES TAB -->
    <div id="tab-opcodes" class="tab-content">
      <div style="display: flex; gap: 12px; margin-bottom: 16px; align-items: center;">
        <input type="text" id="opcode-search" class="input-box" placeholder="Search opcode name, ID, or hex..." style="flex:1;" oninput="filterOpcodes()">
        <select id="domain-filter" class="input-box" onchange="filterOpcodes()">
          <option value="">All Domains</option>
          <option value="eEGS">Game Server (eEGS)</option>
          <option value="eERC">Relay Server (eERC)</option>
          <option value="eECN">Channel / Square (eECN)</option>
          <option value="eEDB">Database (eEDB)</option>
          <option value="eELG">Login (eELG)</option>
        </select>
        <label style="display:flex; align-items:center; gap:6px; font-size:13px; color:var(--text-muted); cursor:pointer;">
          <input type="checkbox" id="implemented-only" onchange="filterOpcodes()"> Implemented Only
        </label>
      </div>
      <div class="table-container" style="max-height: 600px; overflow-y: auto;">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Hex</th>
              <th>Name</th>
              <th>Domain</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="opcodes-table-body">
            <tr><td colspan="5" style="text-align:center;">Loading opcodes...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- DIAGNOSTICS TAB -->
    <div id="tab-diagnostics" class="tab-content">
      <div class="card">
        <h3 style="margin-bottom: 16px;">Server Diagnostics & Connectivity</h3>
        <p style="color:var(--text-muted); margin-bottom: 20px;">
          Direct socket probe verification against Dark Blood Game and Relay instances.
        </p>
        <div id="probe-results" style="background:var(--code-bg); padding:16px; border-radius:6px; font-family:monospace; font-size:13px; border:1px solid var(--card-border);">
          Ready for diagnostic requests.
        </div>
      </div>
    </div>
  </main>

  <!-- EDIT CHARACTER MODAL -->
  <div id="edit-modal" class="modal-overlay">
    <div class="modal">
      <div class="modal-header">
        <h2>Edit Character Stats (GM Tool)</h2>
        <button class="close-btn" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">
        <input type="hidden" id="edit-char-id">
        <div class="form-group">
          <label>Character Name</label>
          <input type="text" id="edit-char-name" class="input-box">
        </div>
        <div class="form-group">
          <label>Level (1 - 60)</label>
          <input type="number" id="edit-char-level" class="input-box" min="1" max="60">
        </div>
        <div class="form-group">
          <label style="display:flex; align-items:center; gap:8px;">
            <input type="checkbox" id="edit-char-tutorial"> Tutorial Cleared
          </label>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn" onclick="saveCharacter()">Save Changes</button>
      </div>
    </div>
  </div>

  <script>
    function switchTab(name) {
      document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
      document.getElementById('tab-' + name).classList.add('active');
      event.target.classList.add('active');
      if (name === 'characters') refreshCharacters();
      if (name === 'opcodes') filterOpcodes();
    }

    async function refreshData() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        // Servers
        const gs = data.servers.game;
        document.getElementById('game-status').innerHTML = gs.status === 'ONLINE'
          ? '<span class="badge badge-online">ONLINE</span>'
          : '<span class="badge badge-offline">OFFLINE</span>';
        document.getElementById('game-latency').innerText = gs.latency_ms ? gs.latency_ms + ' ms latency' : 'Port 9400 unreachable';

        const rs = data.servers.relay;
        document.getElementById('relay-status').innerHTML = rs.status === 'ONLINE'
          ? '<span class="badge badge-online">ONLINE</span>'
          : '<span class="badge badge-offline">OFFLINE</span>';
        document.getElementById('relay-latency').innerText = rs.latency_ms ? rs.latency_ms + ' ms latency' : 'Port 9401 unreachable';

        // Stats
        document.getElementById('stat-chars').innerText = data.database.total_characters;
        document.getElementById('stat-accounts').innerText = 'Across ' + data.database.total_accounts + ' accounts';

        document.getElementById('stat-opcodes').innerText = data.opcodes.implemented;
        document.getElementById('stat-opcodes-total').innerText = 'out of ' + data.opcodes.total_discovered + ' discovered';
      } catch (err) {
        console.error('Failed to load status:', err);
      }
    }

    async function refreshCash() {
      try {
        const res = await fetch('/api/account/cash');
        const data = await res.json();
        document.getElementById('cash-value').textContent = data.cash.toLocaleString();
      } catch (err) {
        console.error('Failed to load cash:', err);
      }
    }

    async function changeCash(mode, fixed) {
      const amount = fixed !== undefined ? fixed : parseInt(document.getElementById('cash-amount').value, 10);
      if (isNaN(amount)) return;
      const res = await fetch('/api/account/cash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account: 'OfflinePlayer', [mode]: amount })
      });
      const data = await res.json();
      if (data.success) document.getElementById('cash-value').textContent = data.cash.toLocaleString();
    }

    async function refreshCharacters() {
      refreshCash();
      try {
        const res = await fetch('/api/characters');
        const chars = await res.json();
        const tbody = document.getElementById('char-table-body');
        if (!chars.length) {
          tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;">No characters found.</td></tr>';
          return;
        }
        tbody.innerHTML = chars.map(c => `
          <tr>
            <td><strong>#${c.id}</strong></td>
            <td>${c.account}</td>
            <td style="color:#fff; font-weight:600;">${c.name}</td>
            <td><span class="badge badge-gold">${c.class_name}</span></td>
            <td><strong>Lv. ${c.level}</strong></td>
            <td>${c.tutorial_cleared ? '✅ Cleared' : '⏳ Pending'}</td>
            <td>${c.item_count} items</td>
            <td>${c.quests_active} active / ${c.quests_done} done</td>
            <td>
              <button class="btn btn-secondary" style="padding:4px 8px; font-size:12px;" onclick="openEditModal(${c.id}, '${c.name}', ${c.level}, ${c.tutorial_cleared})">Edit</button>
              <button class="btn" style="padding:4px 8px; font-size:12px; background:#8a1b1b;" onclick="deleteChar(${c.id})">Delete</button>
            </td>
          </tr>
        `).join('');
      } catch (err) {
        console.error('Failed to load characters:', err);
      }
    }

    function openEditModal(id, name, level, tutorial) {
      document.getElementById('edit-char-id').value = id;
      document.getElementById('edit-char-name').value = name;
      document.getElementById('edit-char-level').value = level;
      document.getElementById('edit-char-tutorial').checked = tutorial;
      document.getElementById('edit-modal').classList.add('open');
    }

    function closeModal() {
      document.getElementById('edit-modal').classList.remove('open');
    }

    async function saveCharacter() {
      const id = document.getElementById('edit-char-id').value;
      const name = document.getElementById('edit-char-name').value;
      const level = parseInt(document.getElementById('edit-char-level').value, 10);
      const tutorial = document.getElementById('edit-char-tutorial').checked;

      await fetch(`/api/character/${id}/modify`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name, level: level, tutorial_cleared: tutorial})
      });
      closeModal();
      refreshCharacters();
      refreshData();
    }

    async function deleteChar(id) {
      if (!confirm('Are you sure you want to delete character #' + id + '?')) return;
      await fetch(`/api/character/${id}`, { method: 'DELETE' });
      refreshCharacters();
      refreshData();
    }

    async function filterOpcodes() {
      const q = document.getElementById('opcode-search').value;
      const domain = document.getElementById('domain-filter').value;
      const impl = document.getElementById('implemented-only').checked;

      const params = new URLSearchParams();
      if (q) params.set('q', q);
      if (domain) params.set('domain', domain);
      if (impl) params.set('implemented', 'true');

      const res = await fetch('/api/opcodes?' + params.toString());
      const list = await res.json();
      const tbody = document.getElementById('opcodes-table-body');
      tbody.innerHTML = list.map(op => `
        <tr>
          <td><strong>${op.id}</strong></td>
          <td style="font-family:monospace; color:var(--text-muted);">${op.hex}</td>
          <td style="color:#fff; font-family:monospace;">${op.name}</td>
          <td><span class="badge badge-gold">${op.domain}</span></td>
          <td>${op.implemented ? '<span class="badge badge-online">Implemented</span>' : '<span class="badge badge-offline">Pending</span>'}</td>
        </tr>
      `).join('');
    }

    async function runProbe(target) {
      const el = document.getElementById('probe-results');
      el.innerText = `Connecting to ${target} server (127.0.0.1:${target === 'game' ? 9400 : 9401})...`;
      const res = await fetch('/api/test_probe', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({target: target})
      });
      const data = await res.json();
      el.innerText = JSON.stringify(data, null, 2);
      refreshData();
    }

    // Auto-refresh telemetry every 4 seconds
    refreshData();
    setInterval(refreshData, 4000);
  </script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description='Dark Blood Emulator GM Dashboard')
    parser.add_argument('--port', type=int, default=9494, help='Dashboard HTTP port (default: 9494)')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host to bind (default: 127.0.0.1)')
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), DashboardHandler)
    print(f"=======================================================")
    print(f" Dark Blood Server Emulator - GM Dashboard Online")
    print(f" URL: http://{args.host}:{args.port}/")
    print(f"=======================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Dashboard...")
        server.server_close()


if __name__ == '__main__':
    main()
