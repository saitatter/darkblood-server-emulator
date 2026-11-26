"""Reusable dark-themed Tkinter widgets for Dark Blood Launcher."""
import tkinter as tk
from tkinter import ttk

from launcher_app.theme import BG_CARD


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
