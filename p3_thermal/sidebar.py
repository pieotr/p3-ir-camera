"""Single-window navigation for persistent tools and temporary editors."""

from tkinter import ttk

import tkinter as tk


class Sidebar(ttk.Frame):
    """Stack pages behind a section selector instead of crowding notebook tabs."""

    def __init__(self, parent):
        super().__init__(parent)
        self.pages = {}
        self.selection = tk.StringVar()
        self.selector = ttk.Combobox(
            self, textvariable=self.selection, state="readonly"
        )
        self.selector.pack(fill="x", padx=8, pady=8)
        self.selector.bind(
            "<<ComboboxSelected>>", lambda _: self.select(self.selection.get())
        )

    def add(self, page, text):
        self.pages[text] = page
        self.selector.configure(values=list(self.pages))
        if len(self.pages) == 1:
            self.select(text)

    def select(self, name):
        for page in self.pages.values():
            page.pack_forget()
        self.selection.set(name)
        self.pages[name].pack(fill="both", expand=True)

    def remove(self, title):
        """Dispose a temporary page and remove its navigation entry."""
        page = self.pages.pop(title, None)
        if page is not None:
            page.destroy()
        self.selector.configure(values=list(self.pages))

    def editor(self, title):
        """Replace a disposable editor page, keeping all controls in the main window."""
        old = self.pages.pop(title, None)
        if old is not None:
            old.destroy()
        page = ttk.Frame(self)
        self.add(page, title)
        self.select(title)
        return page
