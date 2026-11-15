"""Run automated lobby test: launch client against running server, select character, and monitor world entry."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import gamectl

LAB = ROOT / 'research' / 'client'
LOGS = ROOT / 'logs'
WIRE = LOGS / 'wire.jsonl'


def main():
    print("[1] Checking if server is listening on 127.0.0.1:9400...")
    if gamectl._port_free():
        print("ERROR: Server is not running on 9400!")
        return 1

    offset = WIRE.stat().st_size if WIRE.exists() else 0
    print(f"[2] Wire offset: {offset}")

    # Launch client
    env = dict(os.environ, __COMPAT_LAYER='RunAsInvoker')
    DETACHED_PROCESS = 0x00000008
    client = subprocess.Popen([str(LAB / 'DarkBlood.exe')], cwd=str(LAB), env=env,
                              creationflags=DETACHED_PROCESS)
    print(f"[3] Client launched (PID: {client.pid})")

    # Update session.json
    state = dict(started=time.time(), wire_offset=offset, client_pid=client.pid)
    gamectl._save_state(state)

    print("[4] Entering lobby (skip intro -> server list -> channel list)...")
    try:
        res = gamectl.enter_lobby(timeout=90)
        print("Lobby result:", res)
    except Exception as e:
        print("Failed entering lobby:", e)
        print("Recent events:")
        for ev in gamectl.events(since_start=True, limit=20):
            print("  ", ev)
        return 1

    time.sleep(2)
    print("[5] Reached Character Select! Taking screenshot...")
    shot_path = ROOT / 'research' / 'char_select_live.png'
    try:
        gamectl.screenshot(shot_path)
        print(f"Screenshot saved to {shot_path}")
    except Exception as e:
        print("Failed to capture screenshot:", e)

    print("[6] Selecting character: pressing Enter / clicking Ok...")
    # In DarkBlood, pressing enter or clicking the Ok button (approx 0.84, 0.96) selects character
    time.sleep(1)
    gamectl.keys('enter')
    time.sleep(1)

    print("[7] Monitoring wire log for 2006 (SELECT_CHAR_REQ) and subsequent opcodes for 20 seconds...")
    deadline = time.time() + 20
    seen_2006 = False
    seen_2007 = False
    new_opcodes = []

    while time.time() < deadline:
        evs = gamectl.events(since_start=True, include_transport=True, limit=30)
        for ev in evs:
            if '2006' in ev and not seen_2006:
                print(">>> RECEIVED 2006 (SELECT_CHAR_REQ)!")
                seen_2006 = True
            if 'select char ack' in ev and not seen_2007:
                print(">>> SENT 2007 (SELECT_CHAR_ACK)!")
                seen_2007 = True
            if 'C->S' in ev and ' 2006 ' not in ev and ' 2008 ' not in ev and ' 2001 ' not in ev and ' 5028 ' not in ev and ' 2402 ' not in ev and ' 2203 ' not in ev:
                if ev not in new_opcodes:
                    new_opcodes.append(ev)
                    print(">>> NEW CLIENT OPCODES OBSERVED:", ev)
        time.sleep(1)

    # Take screenshot of whatever screen is showing now
    after_shot = ROOT / 'research' / 'after_select_live.png'
    try:
        gamectl.screenshot(after_shot)
        print(f"[8] After-select screenshot saved to {after_shot}")
    except Exception as e:
        print("Failed to capture after screenshot:", e)

    print("[9] Final status of new events:")
    for ev in new_opcodes:
        print("   *", ev)

    return 0


if __name__ == '__main__':
    sys.exit(main())
