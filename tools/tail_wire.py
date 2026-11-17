#!/usr/bin/env python3
"""Tail and filter wire.jsonl events."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIRE = ROOT / 'logs' / 'wire.jsonl'

OPCODES = {}
tsv = ROOT / 'assets' / 'opcodes.tsv'
if tsv.exists():
    for line in tsv.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#'):
            k, v = line.split('\t', 1)
            OPCODES[int(k)] = v


def format_entry(e):
    event = e.get('event')
    op = e.get('opcode')
    op_name = OPCODES.get(op, '')
    note = e.get('note', '')
    err = e.get('error', '')
    role = e.get('role', '')
    data_hex = e.get('hex', '')

    if event in ('recv', 'message', 'send') and not note and not err and op is None:
        # Ignore keepalive noise
        return None

    prefix = f"[{role or 'game'}] {event}"
    if op is not None:
        prefix += f" op={op} ({op_name})"
    if note:
        prefix += f" note={note}"
    if err:
        prefix += f" ERR={err}"
    if event in ('unhandled-event', 'bad-event', 'event'):
        prefix += f" hex={data_hex[:60]}"
    return prefix


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    if not WIRE.exists():
        print("wire.jsonl does not exist")
        return
    with WIRE.open('r', encoding='utf-8') as f:
        lines = f.readlines()
    
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except Exception:
            pass

    formatted = []
    for e in entries:
        msg = format_entry(e)
        if msg:
            formatted.append(msg)

    for line in formatted[-n:]:
        print(line)


if __name__ == '__main__':
    main()
