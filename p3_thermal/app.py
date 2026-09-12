"""Tk workstation: UI owns presentation; Acquisition exclusively owns USB."""

from dataclasses import asdict
from tkinter import filedialog, messagebox, ttk

import queue
import time
import tkinter as tk

import numpy as np

from .acquisition import Acquisition
from .canvas import ThermalCanvas
from .export import load_snapshot, save_snapshot, snapshot_display_settings
from .image_ui import image_dialog
from .palette_ui import PalettePanel
from .palettes import PaletteLibrary, TemperaturePalette
from .processing import (
    PALETTES,
    DisplaySettings,
    Processor,
    legend_colors,
    orient,
    pixel_label,
    temperature,
)


class ThermalApp:
    """Professional desktop controls with raw-accurate pixel inspection."""

    RECONNECT_DELAY = 2.0

    def __init__(self, root, model="p3", demo=False):
        self.root, self.model, self.demo = root, model, demo
        self.worker = None
        self.frame = None
        self.offline = False
        self.snapshot_metadata = {}
        self.library = PaletteLibrary(PALETTES)
        self._combos = {}
        self._render_key = None
        self.processor = Processor()
        self.settings = DisplaySettings()
        self.rotation = 0
        self.mirror = False
        self.paused = False
        self.closing = False
        self._waiting = False
        self._retry_at = 0.0
        self._connection_error = ""
        self.root.title("P3 Thermal Studio" + (" · DEMO" if demo else ""))
        self.root.geometry("1280x850")
        self.root.minsize(1100, 850)
        self._style()
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        for key, callback in {
            "<Control-x>": self.canvas.inspect,
            "<plus>": lambda: self.canvas.zoom(1.25),
            "<minus>": lambda: self.canvas.zoom(0.8),
            "<Escape>": self.canvas.fit,
            "<Control-s>": self.export,
        }.items():
            root.bind(key, lambda e, fn=callback: fn())
        self.connect()
        self._poll_id = self.root.after(40, self.poll)

    def _style(self):
        self.root.configure(background="#18212e")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            ".", background="#18212e", foreground="#e7edf5", font=("TkDefaultFont", 10)
        )
        style.configure("TButton", padding=(10, 7), background="#2b3b50")
        style.map("TButton", background=[("active", "#385673")])
        style.configure(
            "TCombobox", fieldbackground="#f0f4f9", foreground="#142030", padding=5
        )
        style.configure("TEntry", fieldbackground="#f0f4f9", foreground="#142030")
        style.configure("TNotebook.Tab", background="#2b3b50", padding=(10, 8))
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#385673")],
            foreground=[("selected", "#ffffff")],
        )
        style.configure("Title.TLabel", font=("TkDefaultFont", 20, "bold"))
        style.configure(
            "Readout.TLabel", font=("TkFixedFont", 12), foreground="#76dfd0"
        )
        style.configure("TLabelframe", padding=12)
        style.configure("TLabelframe.Label", foreground="#91a8c1")

    def _build(self):
        header = ttk.Frame(self.root, padding=16)
        header.pack(fill="x")
        ttk.Label(header, text="THERMAL STUDIO", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=f"  {self.model.upper()} / radiometric workspace").pack(
            side="left"
        )
        toolbar = ttk.Frame(self.root, padding=(16, 0, 16, 12))
        toolbar.pack(fill="x")
        self.connect_button = ttk.Button(
            toolbar, text="Reconnect", command=self.connect
        )
        self.connect_button.pack(side="left", padx=3)
        self.pause_button = ttk.Button(toolbar, text="Freeze", command=self.pause)
        self.pause_button.pack(side="left", padx=3)
        ttk.Button(toolbar, text="Open RAW…", command=self.open_snapshot).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="Save data…", command=self.export).pack(
            side="left", padx=3
        )
        ttk.Button(toolbar, text="Save image…", command=self.screenshot).pack(
            side="left", padx=3
        )
        self.shutter_button = ttk.Button(
            toolbar, text="Shutter / NUC", command=lambda: self.command("shutter", None)
        )
        self.shutter_button.pack(side="left", padx=3)
        ttk.Button(toolbar, text="Help", command=self.help).pack(side="right")
        body = ttk.Frame(self.root, padding=(16, 0, 16, 8))
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        self.canvas = ThermalCanvas(
            left,
            self.pixel,
            lambda scale: self.zoom_text.set(
                f"Zoom  {scale * 100:.0f}%  ·  wheel to zoom / drag to pan"
            ),
        )
        self.canvas.pack(fill="both", expand=True)
        navigation = ttk.Frame(left, padding=(0, 5))
        navigation.pack(fill="x")
        for label, action in [
            ("−", lambda: self.canvas.zoom(0.8)),
            ("+", lambda: self.canvas.zoom(1.25)),
            ("←", lambda: self.canvas.move_image(-60, 0)),
            ("→", lambda: self.canvas.move_image(60, 0)),
            ("↑", lambda: self.canvas.move_image(0, -60)),
            ("↓", lambda: self.canvas.move_image(0, 60)),
            ("Fit", self.canvas.fit),
            ("Pixels", self.canvas.inspect),
        ]:
            ttk.Button(navigation, text=label, width=5, command=action).pack(
                side="left", padx=2
            )
        self.show_legend = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            navigation, text="Legend", variable=self.show_legend, command=self.render
        ).pack(side="right")
        self.zoom_text = tk.StringVar(value="Zoom")
        self.pixel_text = tk.StringVar(value="Pixel: move the pointer over the image")
        ttk.Label(left, textvariable=self.zoom_text, padding=(8, 7)).pack(fill="x")
        ttk.Label(
            left, textvariable=self.pixel_text, style="Readout.TLabel", padding=(8, 7)
        ).pack(fill="x")
        self.legend = tk.StringVar()
        ttk.Label(left, textvariable=self.legend, padding=8).pack(fill="x")
        side = ttk.Frame(body, padding=(16, 0, 0, 0), width=280)
        side.pack(side="right", fill="y")
        tabs = ttk.Notebook(side)
        tabs.pack(fill="both", expand=True)
        display = ttk.Frame(tabs, padding=12)
        tabs.add(display, text="View")
        self.mode = self.combo(
            display,
            "Source",
            ["Temperature", "Filtered temperature", "Raw counts", "Factory brightness"],
            self.settings.mode,
        )
        self.palette = self.combo(
            display,
            "Palette",
            list(PALETTES) + sorted(self.library.palettes),
            self.settings.palette,
        )
        self.range_mode = self.combo(
            display, "Range", ["Auto percentile", "Fixed"], self.settings.range_mode
        )
        self.low = tk.StringVar(value="15")
        self.high = tk.StringVar(value="40")
        for label, variable in [("Minimum °C", self.low), ("Maximum °C", self.high)]:
            ttk.Label(display, text=label).pack(anchor="w")
            ttk.Entry(display, textvariable=variable, width=22).pack(
                fill="x", pady=(2, 6)
            )
        ttk.Button(display, text="Apply range", command=self.update_settings).pack(
            fill="x"
        )
        ttk.Button(
            display, text="Temperature vs Factory brightness?", command=self.source_help
        ).pack(fill="x", pady=12)
        self.palette_note = tk.StringVar(
            value="Factory palette: range follows Auto / Fixed."
        )
        ttk.Label(display, textvariable=self.palette_note, wraplength=290).pack(
            anchor="w", pady=8
        )
        filters = ttk.Frame(tabs, padding=12)
        tabs.add(filters, text="Filters")
        self.detail = tk.BooleanVar()
        self.clahe = tk.BooleanVar()
        self.clahe_switch = ttk.Checkbutton(
            filters,
            text="CLAHE · local contrast",
            variable=self.clahe,
            command=self.update_settings,
        )
        self.clahe_switch.pack(anchor="w", pady=8)
        self.dde_switch = ttk.Checkbutton(
            filters,
            text="DDE · edge sharpening",
            variable=self.detail,
            command=self.update_settings,
        )
        self.dde_switch.pack(anchor="w", pady=8)
        ttk.Checkbutton(
            filters, text="X³ · unavailable in current USB driver", state="disabled"
        ).pack(anchor="w", pady=8)
        ttk.Label(
            filters,
            text="X³ needs a verified camera command or the manufacturer's algorithm. It is not ordinary zoom.",
            wraplength=290,
        ).pack(anchor="w", pady=8)
        ttk.Label(filters, text="Temporal filter: current-frame weight").pack(
            anchor="w"
        )
        self.alpha = tk.DoubleVar(value=0.35)
        ttk.Scale(
            filters,
            from_=0.05,
            to=1,
            variable=self.alpha,
            command=lambda value: self.update_settings(),
        ).pack(fill="x")
        ttk.Label(
            filters,
            text="Temporal filtering applies only to Filtered temperature. All pixel readouts use original RAW.\n\nAbsolute temperature palettes bypass CLAHE and DDE to preserve their temperature thresholds.",
            wraplength=290,
        ).pack(anchor="w", pady=15)
        view = ttk.Frame(tabs, padding=12)
        tabs.add(view, text="Sensor")
        for label, fn in [
            ("Fit image", self.canvas.fit),
            ("Inspect pixels · Ctrl+X", self.canvas.inspect),
            ("Rotate 90°", self.rotate),
            ("Mirror", self.flip),
        ]:
            ttk.Button(view, text=label, command=fn).pack(fill="x", pady=2)
        self.spots = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            view,
            text="Minimum / maximum markers",
            variable=self.spots,
            command=self.render,
        ).pack(anchor="w", pady=5)
        self.gain = self.combo(
            view,
            "Sensor gain",
            ["HIGH", "LOW"],
            "HIGH",
            lambda: self.command("gain", self.gain.get()),
        )
        ttk.Label(
            view,
            text="LOW: experimental radiometry. Tested firmware\nreturned an offset that NUC did not resolve.",
            foreground="#f4ba76",
            wraplength=310,
        ).pack(anchor="w", pady=8)
        if self.demo:
            self.shutter_button.state(["disabled"])
        self.statistics = tk.StringVar(value="No frame")
        ttk.Label(
            view, textvariable=self.statistics, justify="left", style="Readout.TLabel"
        ).pack(anchor="w", pady=8)
        self.palette_panel = PalettePanel(tabs, self.library, self.palette_changed)
        tabs.add(self.palette_panel, text="Palettes")
        self.status = tk.StringVar(value="Starting…")
        ttk.Label(self.root, textvariable=self.status, padding=(16, 10)).pack(
            fill="x", side="bottom", before=body
        )

    def combo(self, parent, label, values, value, callback=None):
        ttk.Label(parent, text=label).pack(anchor="w")
        variable = tk.StringVar(value=value)
        widget = ttk.Combobox(
            parent, textvariable=variable, values=values, state="readonly", width=25
        )
        widget.pack(fill="x", pady=(3, 9))
        self._combos[label] = widget
        widget.bind(
            "<<ComboboxSelected>>", lambda e: (callback or self.update_settings)()
        )
        return variable

    def update_settings(self):
        try:
            low, high = float(self.low.get()), float(self.high.get())
            if not np.isfinite([low, high]).all() or high <= low:
                raise ValueError()
        except ValueError:
            self.status.set(
                "Invalid range: enter finite values with maximum > minimum."
            )
            return
        custom = self.library.palettes.get(self.palette.get())
        if custom and self.mode.get() not in ("Temperature", "Filtered temperature"):
            self.mode.set("Temperature")
        self.palette_note.set(
            "Absolute temperature stops: Auto / Fixed and enhancements are bypassed."
            if custom
            else "Factory palette: range follows Auto / Fixed."
        )
        self.clahe_switch.state(["disabled"] if custom else ["!disabled"])
        self.dde_switch.state(["disabled"] if custom else ["!disabled"])
        self.settings = DisplaySettings(
            self.mode.get(),
            self.palette.get(),
            self.range_mode.get(),
            low,
            high,
            self.alpha.get(),
            self.detail.get(),
            self.clahe.get(),
        )
        self.processor.reset()
        self.render()

    def connect(self):
        """Start one connection attempt; retries never overlap USB cleanup."""
        if self.closing:
            return
        if self.offline:
            self.return_live()
            return
        if self.worker is not None and self.worker.is_alive():
            self.status.set("Camera worker is already active.")
            return
        self._waiting = False
        self.paused = False
        self.pause_button.configure(text="Freeze")
        self.processor.reset()
        self._render_key = None
        self.worker = Acquisition(self.model, self.demo)
        self.worker.start()

    def command(self, name, value):
        if self.offline:
            self.status.set("Imported snapshot · return to live to control the camera.")
        elif self.demo:
            self.status.set("Sensor controls are unavailable in demo mode.")
        elif self.worker and self.worker.is_alive():
            self.worker.commands.put((name, value))
            self.status.set(f"Queued: {name} {value or ''}")
        else:
            self.status.set("Reconnect the camera before issuing a sensor command.")

    def poll(self):
        if self.closing:
            return
        if self.worker:
            while True:
                try:
                    event = self.worker.events.get_nowait()
                    if not self.offline:
                        self.status.set(event)
                    if event.startswith("Disconnected / error:"):
                        self._connection_error = event
                    if event.startswith("Applied:") and not self.offline:
                        self.processor.reset()
                        self._render_key = None
                except queue.Empty:
                    break
            try:
                frame = self.worker.frames.get_nowait()
                if not self.paused and not self.offline:
                    self.frame = frame
                    self.render()
            except queue.Empty:
                pass
            alive = self.worker.is_alive()
            self.connect_button.state(
                ["disabled"] if alive and not self.offline else ["!disabled"]
            )
            if not alive and not self.demo and not self.offline:
                if not self._waiting:
                    self._waiting = True
                    self._retry_at = time.monotonic() + self.RECONNECT_DELAY
                    self.frame = None
                    self.canvas.raw = self.canvas.rgb = self.canvas.coordinates = None
                    self.canvas.empty_message = "No camera · waiting for reconnection…"
                    self.canvas.redraw()
                    self.pixel_text.set("Pixel: no camera")
                    self.statistics.set("No camera connected")
                    self.legend.set("")
                    self.status.set(
                        "No camera · retrying automatically. " + self._connection_error
                    )
                elif time.monotonic() >= self._retry_at:
                    self.connect()
        self._poll_id = self.root.after(40, self.poll)

    def render(self):
        if self.frame is None:
            return
        custom = self.library.palettes.get(self.settings.palette)
        key = (id(self.frame), repr(self.settings), repr(custom))
        if key != self._render_key:
            self._rendered = self.processor.render(
                self.frame.raw, self.frame.brightness, self.settings, custom
            )
            self._render_key = key
        rgb, limits = self._rendered
        raw = orient(self.frame.raw, self.rotation, self.mirror)
        coords = np.moveaxis(np.indices(self.frame.raw.shape), 0, -1)
        self.canvas.markers = self.spots.get()
        self.canvas.show_legend = self.show_legend.get()
        unit = "counts" if self.settings.mode == "Raw counts" and not custom else "°C"
        self.canvas.legend_data = (
            (
                legend_colors(self.settings, custom),
                float(limits[0]),
                float(limits[1]),
                unit,
            )
            if limits
            else (legend_colors(self.settings), 0.0, 255.0, "Brightness")
        )
        self.canvas.set_frame(
            orient(rgb, self.rotation, self.mirror),
            raw,
            orient(coords, self.rotation, self.mirror),
        )
        data = temperature(self.frame.raw)
        self.statistics.set(
            f"SENSOR TEMPERATURE\nMin   {data.min():.6f} °C\nMax   {data.max():.6f} °C\nMean  {data.mean():.6f} °C\n\n{self.frame.raw.shape[1]} × {self.frame.raw.shape[0]} pixels\nNative step: 0.015625 K"
        )
        unit = "counts" if self.settings.mode == "Raw counts" and not custom else "°C"
        self.legend.set(
            f"Palette range: {limits[0]:.6f} → {limits[1]:.6f} {unit}"
            if limits
            else "Brightness / enhanced contrast · colors have no linear temperature scale"
        )

    def pixel(self, sample):
        if sample is None:
            self.pixel_text.set("Pixel: move the pointer over the image")
        else:
            x, y, raw = sample
            self.pixel_text.set(f"Pixel ({x}, {y})   {pixel_label(raw)}   RAW {raw}")

    def pause(self):
        if self.offline:
            self.return_live()
            return
        self.paused = not self.paused
        self.pause_button.configure(text="Resume" if self.paused else "Freeze")
        self.status.set(
            "Frozen frame · acquisition continues"
            if self.paused
            else "Live view resumed"
        )

    def rotate(self):
        self.rotation = (self.rotation + 1) % 4
        self.canvas.auto_fit = True
        self.render()

    def flip(self):
        self.mirror = not self.mirror
        self.render()

    def export(self):
        if self.frame is None:
            self.status.set("No frame to save.")
            return
        frame = self.frame
        metadata = {
            **self.snapshot_metadata,
            "snapshot_version": 2,
            "model": self.snapshot_metadata.get("model", self.model)
            if self.offline
            else self.model,
            "demo": self.snapshot_metadata.get("demo", False)
            if self.offline
            else self.demo,
            "display": asdict(self.settings),
            "rotation_quarters_ccw": self.rotation,
            "mirror": self.mirror,
        }
        custom = self.library.palettes.get(self.settings.palette)
        metadata["palette_spec"] = custom.to_dict() if custom else None
        path = filedialog.asksaveasfilename(
            defaultextension=".npz", filetypes=[("Thermal snapshot", "*.npz")]
        )
        if path:
            try:
                save_snapshot(path, frame, metadata)
                self.status.set(f"Saved thermal data: {path}")
            except OSError as exc:
                messagebox.showerror("Save failed", str(exc))

    def screenshot(self):
        if self.frame is None or self.canvas.rgb is None:
            self.status.set("No image to save.")
            return
        image_dialog(
            self.root,
            self.frame,
            self.canvas.rgb.copy(),
            lambda path: self.status.set(f"Saved image: {path}"),
            self.canvas.legend_data if self.show_legend.get() else None,
        )

    def palette_changed(self, name):
        self._combos["Palette"].configure(
            values=list(PALETTES) + sorted(self.library.palettes)
        )
        if name:
            self.palette.set(name)
        elif (
            self.palette.get() not in PALETTES
            and self.palette.get() not in self.library.palettes
        ):
            self.palette.set("Inferno")
        self.update_settings()

    def source_help(self):
        messagebox.showinfo(
            "Image sources",
            "Temperature: the app converts native 16-bit RAW samples to °C and maps the selected range to colors. Fixed range gives repeatable colors across frames.\n\nFactory brightness: a separate 8-bit image already processed by the camera. It can show clearer detail, but intensity is not a linear temperature scale.\n\nCLAHE increases local contrast; DDE sharpens edges. Both affect visualization only. Pixel readouts always come from the original RAW plane.",
        )

    def open_snapshot(self):
        path = filedialog.askopenfilename(
            filetypes=[("Full thermal snapshot", "*.npz")]
        )
        if path:
            try:
                self.import_snapshot(path)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                messagebox.showerror("Cannot open snapshot", str(exc))

    def import_snapshot(self, path):
        """Enter offline analysis; background camera activity cannot replace this frame."""
        frame, metadata = load_snapshot(path)
        restored = snapshot_display_settings(metadata)
        rotation = metadata.get("rotation_quarters_ccw", 0)
        mirror = metadata.get("mirror", False)
        if (
            type(rotation) is not int
            or rotation not in range(4)
            or type(mirror) is not bool
        ):
            raise ValueError("Invalid snapshot orientation")
        palette_data = metadata.get("palette_spec")
        selected = (
            restored.palette
            if restored.palette in PALETTES or restored.palette in self.library.palettes
            else "Inferno"
        )
        if palette_data is not None:
            palette = TemperaturePalette.from_dict(palette_data)
            # Never replace an existing custom preset merely by opening a snapshot.
            original = palette.name
            index = 1
            while palette.name in PALETTES or (
                palette.name in self.library.palettes
                and self.library.palettes[palette.name] != palette
            ):
                index += 1
                palette = TemperaturePalette(
                    f"{original[:65]} ({index})", palette.stops, palette.interpolation
                )
            self.library.save(palette)
            self.palette_panel.refresh()
            selected = palette.name
        self.offline = True
        self.paused = True
        self.snapshot_metadata = metadata
        self.frame = frame
        self.rotation = rotation
        self.mirror = mirror
        self.mode.set(restored.mode)
        self.range_mode.set(restored.range_mode)
        self.low.set(str(restored.minimum))
        self.high.set(str(restored.maximum))
        self.alpha.set(restored.alpha)
        self.clahe.set(restored.clahe)
        self.detail.set(restored.detail)
        self.canvas.auto_fit = True
        self.pause_button.configure(text="Return to live")
        self._render_key = None
        self.processor.reset()
        self.palette_changed(selected)
        self.status.set(f"Imported frozen frame · {path}")

    def return_live(self):
        self.offline = False
        self.paused = False
        self.snapshot_metadata = {}
        self._waiting = False
        self.pause_button.configure(text="Freeze")
        self.processor.reset()
        self._render_key = None
        self.frame = None
        self.canvas.raw = self.canvas.rgb = self.canvas.coordinates = None
        self.canvas.empty_message = "Waiting for live camera…"
        self.canvas.redraw()
        self.pixel_text.set("Pixel: waiting for live camera")
        self.statistics.set("Waiting for live camera")
        self.legend.set("")
        self.status.set("Returning to live camera…")
        if self.worker is None or not self.worker.is_alive():
            self.connect()

    def help(self):
        messagebox.showinfo(
            "Thermal Studio",
            "Wheel / + / −: zoom\nDrag: pan · double-click / Escape: fit\nCtrl+X: pixel inspection · Ctrl+S: save raw snapshot\n\nPixel readouts and statistics always use unfiltered camera samples, including in factory/raw/filtered display modes. Six decimal places preserve the 1/64 K encoding, not sensor accuracy. Coordinates refer to the original sensor.\n\nFreeze holds the displayed frame; USB capture continues. After disconnection the window stays open and reconnects automatically. Reconnect retries immediately.\n\nSee README.md and docs/ for architecture and operating instructions. Lock-in remains an experimental future extension.",
        )

    def close(self):
        """Keep event processing alive until the USB owner completes cleanup."""
        self.closing = True
        self.root.after_cancel(self._poll_id)
        self.status.set("Closing · stopping stream and releasing USB…")
        if self.worker:
            self.worker.stop_event.set()
        self._await_close()

    def _await_close(self):
        if self.worker and self.worker.is_alive():
            self.root.after(50, self._await_close)
        else:
            self.root.destroy()
