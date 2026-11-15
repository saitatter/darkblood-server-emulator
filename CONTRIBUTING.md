# Contributing to Dark Blood Server Emulator

Thank you for contributing to the **Dark Blood Online (Project Hound / Karcass Online)** preservation and local server emulator project.

The goal of this project is to create an open-source, local offline server emulator that allows the client (`DarkBlood.exe`, Steam AppID 267790) to be played locally on `127.0.0.1` without requiring official external servers.

---

## 1. Quick Start & Prerequisites

### Requirements
- **OS**: Windows 10/11 x64
- **Python**: Python 3.8+ (standard library only for the core server; `pefile`, `capstone` for tooling)
- **C/C++ Compiler**: Microsoft Visual C++ 2022 x86 (`vcvars32.bat`) for compiling `client_hook/steam_api_hook.c`
- **Reverse Engineering**:
  - Ghidra 12.1+ (`JDK 21+`)
  - REA CLI (`reverse-engineer-anything`)
  - Disassembler / Hex Editor

### Repository Layout
```
├── server/                 # Python emulator server implementation
│   ├── run_bootstrap.py    # Main server entrypoint (binds 127.0.0.1:9400)
│   ├── bootstrap_server.py # AsyncIO ProudNet transport listener
│   ├── proudnet_crypto.py  # RSA-1024 OAEP, AES-128 ECB crypto implementation
│   ├── game_wire.py        # JEvent packet framing, opcode dispatch, handlers
│   ├── characters.py       # Character data storage & serialization
│   └── data/               # Static tables (e.g. opcodes.tsv: 1,192 opcodes)
├── tools/                  # Automation, control & analysis tooling
│   ├── gamectl.py          # CLI / automation engine (starts server/client, input, screenshots)
│   ├── mcp_server.py       # MCP stdio server for AI agents
│   └── decomp.ps1          # Headless Ghidra decompilation helper
├── client_hook/            # Minimal DLL shim (steam_api.dll)
│   └── steam_api_hook.c    # Loopback network redirect, INT3 tracer, Steam mocks
├── docs/                   # Architecture & protocol documentation
│   ├── PROTOCOL.md         # Wire protocol specification & opcode catalog
│   ├── STATUS.md           # Current implementation status & verified milestones
│   └── ROADMAP.md          # Implementation roadmap
├── CONTRIBUTING.md         # This contributor guide
└── AGENTS.md               # Guidelines for autonomous AI agents
```

---

## 2. Agent & Collaborator Workflow Rules

### Continuous 10-Minute Synchronization Rule
To ensure seamless collaboration between human developers and autonomous AI agents:
1. **Pull Regularly**: Every agent and developer must pull remote changes (`git pull --rebase origin main`) at least once every **10 minutes**.
2. **Push Discoveries**: Do not keep discoveries local. Once an opcode schema, hook, or server handler is verified, commit it to `main` with a clear commit message and push (`git push origin main`).
3. **Push Permissions**: Direct push access on `main` is granted to authorized contributors (including `CristianVita` / `cri999sti@gmail.com`).
4. **Clean Git State**: Never push binary assets, large memory dumps, game client files (`Data/`), or files in `research/` or `logs/`. Only source code, tests, schemas, and markdown documentation belong on `main`.

---

## 3. Protocol Architecture & Conventions

### ProudNet Handshake (Core Transport)
The game communicates using ProudNet on TCP port 9400.
1. **Session Establishment**:
   - `Type 0x05`: Server connection hint with server RSA-1024 public key.
   - `Type 0x06`: Client sends encrypted AES session key (RSA-OAEP-SHA1) and fast key.
   - `Type 0x07`: Server sends `SessionKeyAccepted`.
   - `Type 0x08`: Client sends encrypted initial message.
   - `Type 0x0B`: Server confirms `ConnectionSuccess`.
2. **Encryption Envelope**:
   - Request payloads (`Type 0x26`) use AES-128 ECB mode with a 4-byte CRC-32 envelope.
3. **Application Events (JEvent)**:
   - Handled inside ProudNet user messages (`Type 0x02`).
   - Frame header: `u32 opcode`, `u64 correlation`, `varuint length`, `u8 compressed_flag`, `bytes body`.

### JSerBuffer Serialization Tags
The client's internal serializer (`0x00A40760`, `0x00A52630`, etc.) relies on tagged streams:
- `b'\x10' + varuint(N)`: Vector (list of elements). Empty = `b'\x10\x80'`.
- `b'\x17' + varuint(N)`: Map (dictionary / key-value pairs). Empty = `b'\x17\x80'`.
- `b'\x13' + varuint(N)`: Set / container. Empty = `b'\x13\x80'`.
- `b'\x1e' + struct_data`: Nested struct.
- Numbers/Strings:
  - Strings: UTF-16LE prefixed with `varuint(char_count)`.
  - Varuint: 7-bit groups; termination byte has bit 7 **set** (`byte & 0x80 != 0`).

---

## 4. Testing & Verification

Always test changes against the live client before committing:
```powershell
# 1. Start emulator server and game client
python tools/gamectl.py start

# 2. Walk automatically to Character Select
python tools/gamectl.py enter-lobby

# 3. Capture screen to verify visual state
python tools/gamectl.py screenshot research/verify.png

# 4. Check decoded wire events
python tools/gamectl.py events

# 5. Stop test session cleanly
python tools/gamectl.py stop
```

---

## 5. Coding Standards & Documentation
- **Language**: All documentation, code comments, and commit messages **must be written in English**.
- **No Heavy Third-Party Dependencies**: The core server (`server/`) must run on standard Python 3.8+ without mandatory native compilation or heavy package dependencies.
- **Evidence-Based Reverse Engineering**:
  - Do not guess packet schemas. Extract handlers using Ghidra (`tools/decomp.ps1`) or REA.
  - Document disassembled/decompiled function virtual addresses (VAs) in docstrings.
  - Keep `docs/STATUS.md`, `docs/PROTOCOL.md`, and `ROADMAP.md` updated as new milestones are unlocked.
