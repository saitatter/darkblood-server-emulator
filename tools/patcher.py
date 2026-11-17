"""Dark Blood emulator options: a small GUI to toggle client patches and server behaviour.

    python tools/patcher.py

Writes research/client/darkblood_options.ini. [client] options are applied by
the steam_api shim when a client starts; [server] options are read by the
running server when they are used (e.g. adult content at the next login).
"""
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
from darkblood.core import options  # noqa: E402


class Patcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Dark Blood options')
        self.resizable(False, False)
        values = options.read()
        self.vars = {}
        frame = ttk.Frame(self, padding=12)
        frame.grid(sticky='nsew')
        row = 0
        for section, title in (('client', 'Client patches (restart the client)'),
                               ('server', 'Server behaviour')):
            ttk.Label(frame, text=title, font=('Segoe UI', 10, 'bold')).grid(
                row=row, column=0, sticky='w', pady=(8 if row else 0, 2))
            row += 1
            for key, (sec, default, label, description) in options.OPTIONS.items():
                if sec != section:
                    continue
                var = tk.BooleanVar(value=values[key])
                self.vars[key] = var
                ttk.Checkbutton(frame, text=label, variable=var).grid(row=row, column=0, sticky='w')
                row += 1
                ttk.Label(frame, text=description, foreground='#666', wraplength=420).grid(
                    row=row, column=0, sticky='w', padx=(22, 0))
                row += 1

        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, sticky='ew', pady=(12, 0))
        ttk.Button(buttons, text='Save', command=self.save).pack(side='left')
        ttk.Label(buttons, text='  Clients:').pack(side='left')
        self.count = tk.IntVar(value=1)
        ttk.Spinbox(buttons, from_=1, to=4, width=3, textvariable=self.count).pack(side='left')
        ttk.Button(buttons, text='Save && launch', command=self.launch).pack(side='left', padx=(6, 0))
        row += 1
        self.status = ttk.Label(frame, text=str(options.OPTIONS_PATH), foreground='#666', wraplength=420)
        self.status.grid(row=row, column=0, sticky='w', pady=(8, 0))

    def save(self):
        options.write({key: var.get() for key, var in self.vars.items()})
        self.status.config(text='Saved to %s' % options.OPTIONS_PATH)

    def launch(self):
        self.save()
        count = max(1, min(4, self.count.get()))
        self.status.config(text='Launching %d client(s)...' % count)

        def run():
            import multibox
            try:
                result = multibox.start(count)
                text = 'Running: %s' % ', '.join(map(str, result['clients']))
            except Exception as exc:  # report in the window, keep the GUI alive
                text = 'Launch failed: %s' % exc
            self.after(0, lambda: self.status.config(text=text))

        threading.Thread(target=run, daemon=True).start()


if __name__ == '__main__':
    Patcher().mainloop()
