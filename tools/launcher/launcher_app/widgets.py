"""Reusable dark-themed Tkinter widgets for Dark Blood Launcher."""
import tkinter as tk
from tkinter import ttk

from launcher_app.theme import (
    ACCENT,
    BG_CARD,
    BG_CARD_ALT,
    BG_INPUT,
    BORDER,
    GOLD,
    TEXT_DIM,
    TEXT_MAIN,
    TEXT_MUTED,
)
from launcher_app.gm_catalogs import CATALOG_LABELS, lookup_entry, search_catalog


class ScrollFrame(tk.Frame):
    """Dark-themed vertical scrollable container with flicker-free atomic swaps."""

    def __init__(self, parent, bg=BG_CARD, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)
        self._bg = bg
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(
            self, orient='vertical', command=self.canvas.yview,
            style='Dark.Vertical.TScrollbar',
        )
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._bind_inner(self.inner)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side='left', fill='both', expand=True)
        self.scrollbar.pack(side='right', fill='y')

        # Bind wheel only while pointer is over this scroll area
        self.canvas.bind('<Enter>', self._bind_wheel)
        self.canvas.bind('<Leave>', self._unbind_wheel)

    def _bind_inner(self, frame):
        frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        frame.bind('<Enter>', self._bind_wheel)
        frame.bind('<Leave>', self._unbind_wheel)

    def new_offscreen_inner(self):
        return tk.Frame(self.canvas, bg=self._bg)

    def swap_inner(self, new_inner):
        """Atomically replace inner frame to avoid Win32 white/light-theme redraw flash."""
        old = self.inner
        self._bind_inner(new_inner)
        new_inner.update_idletasks()
        self.inner = new_inner
        self.canvas.itemconfigure(self._win, window=new_inner, width=max(1, self.canvas.winfo_width()))
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        self.canvas.yview_moveto(0.0)
        if old is not None and old is not new_inner:
            old.destroy()

    def _bind_wheel(self, _event=None):
        self.canvas.bind_all('<MouseWheel>', self._on_wheel)

    def _unbind_wheel(self, _event=None):
        self.canvas.unbind_all('<MouseWheel>')

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')


class SearchableIdPicker(tk.Frame):
    """Dark-themed dropdown button that opens a searchable ID + Name popup menu."""

    def __init__(self, parent, catalog: str, initial_value: str = '',
                 extra_choices=(), on_change=None, bg=BG_CARD_ALT):
        super().__init__(parent, bg=bg)
        self.catalog = catalog
        self.extra_choices = list(extra_choices or ())
        self.on_change = on_change
        self._value = (initial_value or '').strip()
        self._popup = None
        self._matches = []

        self._btn = tk.Label(
            self,
            text=self._format_button_text(),
            bg=BG_INPUT,
            fg=TEXT_MAIN,
            font=('Consolas', 8),
            anchor='w',
            padx=8,
            pady=4,
            cursor='hand2',
            highlightbackground=BORDER,
            highlightthickness=1,
            width=30,
        )
        self._btn.pack(fill='x', expand=True)
        self._btn.bind('<Button-1>', lambda _e: self._toggle_popup())
        self._btn.bind('<Enter>', lambda _e: self._btn.configure(highlightbackground=ACCENT))
        self._btn.bind('<Leave>', lambda _e: self._btn.configure(highlightbackground=BORDER))

    def get(self) -> str:
        return self._value

    def set(self, value: str, notify: bool = False):
        self._value = (value or '').strip()
        self._btn.configure(text=self._format_button_text())
        if notify and self.on_change:
            self.on_change(self._value)

    def _format_button_text(self) -> str:
        if not self._value:
            label = CATALOG_LABELS.get(self.catalog, self.catalog.title())
            return f'Select {label}...  ▾'
        entry = lookup_entry(self.catalog, self._value)
        text = entry.short_label() if entry else self._value
        if len(text) > 28:
            text = text[:27] + '…'
        return f'{text}  ▾'

    def _toggle_popup(self):
        if self._popup is not None and self._popup.winfo_exists():
            self._close_popup()
        else:
            self._open_popup()

    def _close_popup(self, _event=None):
        if self._popup is not None:
            try:
                self._popup.destroy()
            except tk.TclError:
                pass
            self._popup = None

    def _open_popup(self):
        self._close_popup()
        top = tk.Toplevel(self)
        top.overrideredirect(True)
        top.configure(bg=BORDER)
        top.attributes('-topmost', True)
        self._popup = top

        popup_w, popup_h = 480, 310
        self.update_idletasks()
        x = self._btn.winfo_rootx()
        y_below = self._btn.winfo_rooty() + self._btn.winfo_height() + 2
        screen_h = self.winfo_screenheight()
        screen_w = self.winfo_screenwidth()
        y = y_below if (y_below + popup_h) < (screen_h - 32) else max(16, self._btn.winfo_rooty() - popup_h - 2)
        if x + popup_w > screen_w - 12:
            x = max(12, screen_w - popup_w - 12)
        top.geometry(f'{popup_w}x{popup_h}+{x}+{y}')

        inner = tk.Frame(top, bg=BG_CARD)
        inner.pack(fill='both', expand=True, padx=1, pady=1)

        # Header + search input
        hdr = tk.Frame(inner, bg=BG_CARD_ALT, padx=8, pady=6)
        hdr.pack(fill='x')
        cat_lbl = CATALOG_LABELS.get(self.catalog, self.catalog.title())
        tk.Label(hdr, text=f'Search {cat_lbl}:', bg=BG_CARD_ALT, fg=GOLD,
                 font=('Segoe UI', 8, 'bold')).pack(side='left', padx=(0, 6))

        search_var = tk.StringVar()
        entry = tk.Entry(
            hdr, textvariable=search_var, bg=BG_INPUT, fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN, relief='flat', bd=0,
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
            font=('Segoe UI', 9),
        )
        entry.pack(side='left', fill='x', expand=True, ipady=3)

        close_lbl = tk.Label(hdr, text='✕', bg=BG_CARD_ALT, fg=TEXT_MUTED,
                             font=('Segoe UI', 9, 'bold'), cursor='hand2', padx=6)
        close_lbl.pack(side='right')
        close_lbl.bind('<Button-1>', self._close_popup)

        # Optional quick choice buttons (e.g. 'off' for %riding)
        if self.extra_choices:
            quick = tk.Frame(inner, bg=BG_CARD, padx=8, pady=3)
            quick.pack(fill='x')
            tk.Label(quick, text='Quick:', bg=BG_CARD, fg=TEXT_MUTED,
                     font=('Segoe UI', 8)).pack(side='left', padx=(0, 4))
            for ch in self.extra_choices:
                b = tk.Label(quick, text=ch, bg=BG_CARD_ALT, fg=TEXT_MAIN,
                             font=('Consolas', 8, 'bold'), padx=8, pady=2, cursor='hand2',
                             highlightbackground=BORDER, highlightthickness=1)
                b.pack(side='left', padx=2)
                b.bind('<Button-1>', lambda _e, val=ch: self._pick_value(val))

        # Results listbox
        list_wrap = tk.Frame(inner, bg=BG_CARD)
        list_wrap.pack(fill='both', expand=True, padx=6, pady=(4, 2))
        lb = tk.Listbox(
            list_wrap, bg=BG_CARD_ALT, fg=TEXT_MAIN,
            selectbackground=ACCENT, selectforeground='white',
            activestyle='none', relief='flat', bd=0, highlightthickness=0,
            font=('Consolas', 8),
        )
        sb = ttk.Scrollbar(list_wrap, orient='vertical', command=lb.yview,
                           style='Dark.Vertical.TScrollbar')
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        count_lbl = tk.Label(inner, text='', bg=BG_CARD, fg=TEXT_MUTED,
                             font=('Segoe UI', 8), anchor='w', padx=8, pady=3)
        count_lbl.pack(fill='x')

        def refresh(*_args):
            matches, total = search_catalog(self.catalog, search_var.get(), limit=150)
            self._matches = matches
            lb.delete(0, 'end')
            for m in matches:
                lb.insert('end', ' ' + m.display())
            if matches:
                lb.selection_set(0)
            shown = len(matches)
            suffix = f' (showing first {shown})' if total > shown else ''
            count_lbl.config(text=f'{total:,} {cat_lbl.lower()}(s){suffix}  •  Enter or click to select')

        def pick_selected(_event=None):
            sel = lb.curselection()
            if not sel:
                return
            idx = sel[0]
            if 0 <= idx < len(self._matches):
                self._pick_value(self._matches[idx].id)

        def move_sel(delta: int):
            if not self._matches:
                return 'break'
            sel = lb.curselection()
            cur = sel[0] if sel else 0
            nxt = max(0, min(len(self._matches) - 1, cur + delta))
            lb.selection_clear(0, 'end')
            lb.selection_set(nxt)
            lb.see(nxt)
            return 'break'

        search_var.trace_add('write', refresh)
        entry.bind('<Return>', pick_selected)
        entry.bind('<Down>', lambda _e: move_sel(1))
        entry.bind('<Up>', lambda _e: move_sel(-1))
        entry.bind('<Escape>', self._close_popup)
        lb.bind('<ButtonRelease-1>', pick_selected)
        lb.bind('<Return>', pick_selected)
        lb.bind('<Escape>', self._close_popup)
        top.bind('<FocusOut>', lambda e: self.after(120, self._check_focus_out))

        refresh()
        entry.focus_set()

    def _check_focus_out(self):
        if self._popup is None or not self._popup.winfo_exists():
            return
        focused = self.focus_get()
        if focused is None:
            self._close_popup()
            return
        if focused.winfo_toplevel() is not self._popup:
            self._close_popup()

    def _pick_value(self, value: str):
        self._close_popup()
        self.set(value, notify=True)
