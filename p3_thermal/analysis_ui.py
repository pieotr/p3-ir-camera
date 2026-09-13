"""Measurement workspace: ROI, emissivity painting and radiometric video tools."""

from tkinter import colorchooser, filedialog, messagebox, ttk

import copy
import csv
import queue
import sqlite3
import threading
import tkinter as tk

import numpy as np

from .analysis import EmissivityLayer, Radiometry, Region
from .recording import Recorder, Sequence


def plot_window(parent, title, values, xlabel):
    """Live plot with Matplotlib's standard toolbar and image export."""
    from matplotlib.backends.backend_tkagg import (
        FigureCanvasTkAgg,
        NavigationToolbar2Tk,
    )
    from matplotlib.figure import Figure

    window = parent.editor("Profile")
    ttk.Label(window, text=title).pack(fill="x")
    figure = Figure(figsize=(7, 4), dpi=100)
    axis = figure.add_subplot(111)
    axis.set(xlabel=xlabel, ylabel="Temperature (°C)", title=title)
    (line,) = axis.plot([], [])
    axis.grid(True, alpha=0.3)
    canvas = FigureCanvasTkAgg(figure, master=window)
    canvas.get_tk_widget().pack(fill="both", expand=True)
    NavigationToolbar2Tk(canvas, window)
    timer = None

    def refresh():
        nonlocal timer
        x, y = values()
        line.set_data(x, y)
        axis.relim()
        axis.autoscale_view()
        canvas.draw_idle()
        timer = window.after(300, refresh)

    def close():
        if timer is not None:
            window.after_cancel(timer)
        parent.remove("Profile")
        figure.clear()

    def destroyed(event):
        if event.widget is window and timer is not None:
            window.after_cancel(timer)

    window.bind("<Destroy>", destroyed)
    ttk.Button(
        window,
        text="Close profile",
        command=lambda: (close(), parent.select("Measurements")),
    ).pack(fill="x")
    refresh()
    return window


class AnalysisWorkspace:
    def __init__(self, app):
        self.app = app
        self.window = app.root
        self.pending_recording = None
        self.undo = []
        self.sequence = None
        self.playing = False
        self.play_timer = None
        self.plot_jobs = queue.Queue()
        self.profile_busy = False
        self.profile_cancel = threading.Event()
        tabs = app.sidebar
        roi, raw, video = [
            self.scroll_tab(tabs, title)
            for title in ("Measurements", "RAW editing", "Video")
        ]
        self._build_roi(roi)
        self._build_raw(raw)
        self._build_video(video)
        self._wrap_labels(tabs)
        self.refresh_state()

    @staticmethod
    def _wrap_labels(parent):
        for child in parent.winfo_children():
            if isinstance(child, ttk.Label):
                child.configure(wraplength=440)
            AnalysisWorkspace._wrap_labels(child)

    @staticmethod
    def scroll_tab(tabs, title):
        shell = ttk.Frame(tabs)
        tabs.add(shell, text=title)
        canvas = tk.Canvas(shell, highlightthickness=0, background="#18212e")
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        content = ttk.Frame(canvas, padding=12)
        item = canvas.create_window(0, 0, window=content, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
        content.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        return content

    def stop_playback(self):
        self.playing = False
        if self.play_timer is not None:
            self.window.after_cancel(self.play_timer)
            self.play_timer = None

    def hide(self):
        self.profile_cancel.set()
        self.app.canvas.tool = "Pan"
        self.tool.set("Pan")
        self.stop_playback()
        self.app.sidebar.select("View")

    def _build_roi(self, panel):
        self.tool = tk.StringVar(value="Pan")
        ttk.Label(panel, text="Tool · draw on the main thermal image").pack(anchor="w")
        tools = ttk.Combobox(
            panel,
            values=("Pan", "Spot", "Rectangle", "Circle", "Line"),
            textvariable=self.tool,
            state="readonly",
        )
        tools.pack(fill="x", pady=6)
        tools.bind("<<ComboboxSelected>>", lambda e: self.set_tool(self.tool.get()))
        ttk.Label(
            panel,
            text="Spot: click. Rectangle / line: drag. Circle: center → radius.\nCoordinates and measurements remain attached to native sensor pixels.",
        ).pack(anchor="w", pady=6)
        self.rois = ttk.Treeview(
            panel,
            columns=("name", "min", "max", "mean", "count"),
            show="headings",
            height=9,
        )
        for name in ("name", "min", "max", "mean", "count"):
            self.rois.heading(name, text=name)
            self.rois.column(name, width=85, minwidth=55, stretch=True)
        self.rois.pack(fill="x", pady=8)
        row = ttk.Frame(panel)
        row.pack(fill="x")
        for name, fn in (
            ("Delete selected", self.delete_roi),
            ("Line profile…", self.line_profile),
            ("Export ROI CSV…", self.roi_csv),
        ):
            ttk.Button(row, text=name, command=fn).pack(side="left", padx=3)
        self.iso_enabled = tk.BooleanVar()
        self.iso_min = tk.StringVar(value="50")
        self.iso_max = tk.StringVar(value="1000")
        self.iso_color = "#FF00FF"
        ttk.Checkbutton(
            panel,
            text="Isotherm (inclusive temperature interval)",
            variable=self.iso_enabled,
            command=self.apply_isotherm,
        ).pack(anchor="w", pady=(25, 6))
        for label, var in (("Minimum °C", self.iso_min), ("Maximum °C", self.iso_max)):
            ttk.Label(panel, text=label).pack(anchor="w")
            ttk.Entry(panel, textvariable=var).pack(fill="x", pady=3)
        ttk.Button(panel, text="Isotherm color…", command=self.choose_iso_color).pack(
            fill="x", pady=5
        )
        ttk.Button(panel, text="Apply interval", command=self.apply_isotherm).pack(
            fill="x"
        )
        ttk.Label(
            panel,
            text="For 'above 50°C', set minimum 50 and a sufficiently high maximum.\nColored isotherms are an overlay; the palette legend describes the base image.",
        ).pack(anchor="w", pady=8)

    def _build_raw(self, panel):
        self.enabled = tk.BooleanVar()
        self.atmos_enabled = tk.BooleanVar()
        ttk.Checkbutton(
            panel,
            text="Enable experimental radiometric correction",
            variable=self.enabled,
        ).pack(anchor="w")
        self.params = {}
        grid = ttk.Frame(panel)
        grid.pack(fill="x", pady=6)
        for index, (key, label, value) in enumerate(
            (
                ("emissivity", "Global emissivity ε", 1),
                ("reflected", "Reflected / background °C", 20),
                ("atmosphere", "Air temperature °C", 20),
                ("distance", "Object distance m", 0),
                ("humidity", "Relative humidity %", 50),
            )
        ):
            var = tk.StringVar(value=str(value))
            self.params[key] = var
            ttk.Label(grid, text=label).grid(row=index, column=0, sticky="w", padx=4)
            ttk.Entry(grid, textvariable=var, width=15).grid(
                row=index, column=1, sticky="ew", pady=3
            )
        ttk.Checkbutton(
            panel,
            text="Apply distance / humidity model (generic LWIR)",
            variable=self.atmos_enabled,
        ).pack(anchor="w")
        ttk.Button(
            panel, text="Apply radiometric parameters", command=self.apply_radiometry
        ).pack(fill="x", pady=6)
        self.correction_info = tk.StringVar(value="Original sensor temperatures")
        ttk.Label(panel, textvariable=self.correction_info, wraplength=440).pack(
            anchor="w"
        )
        ttk.Label(
            panel, text="Emissivity layers · later layers override earlier ones"
        ).pack(anchor="w", pady=(16, 4))
        self.layers = ttk.Treeview(
            panel, columns=("name", "eps", "enabled"), show="headings", height=5
        )
        for col in ("name", "eps", "enabled"):
            self.layers.heading(col, text=col)
            self.layers.column(col, width=130)
        self.layers.pack(fill="x")
        self.layers.bind("<<TreeviewSelect>>", lambda e: self.layer_selected())
        self.layer_name, self.layer_eps = (
            tk.StringVar(value="Material 1"),
            tk.StringVar(value="0.95"),
        )
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=4)
        ttk.Entry(row, textvariable=self.layer_name, width=20).pack(side="left")
        ttk.Entry(row, textvariable=self.layer_eps, width=8).pack(side="left", padx=5)
        ttk.Button(row, text="Add layer", command=self.add_layer).pack(side="left")
        ttk.Button(row, text="Update ε", command=self.update_layer).pack(side="left")
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=4)
        for label, fn in (
            ("Toggle", self.toggle_layer),
            ("Delete", self.delete_layer),
            ("Move up", lambda: self.move_layer(-1)),
            ("Move down", lambda: self.move_layer(1)),
            ("Undo stroke", self.undo_stroke),
        ):
            ttk.Button(row, text=label, command=fn).pack(fill="x", pady=2)
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="Brush", command=lambda: self.set_tool("Brush")).pack(
            side="left"
        )
        ttk.Button(row, text="Eraser", command=lambda: self.set_tool("Eraser")).pack(
            side="left"
        )
        ttk.Button(row, text="Pan", command=lambda: self.set_tool("Pan")).pack(
            side="left"
        )
        ttk.Label(row, text="Radius px:").pack(side="left")
        self.radius = tk.StringVar(value="4")
        ttk.Spinbox(row, from_=1, to=100, textvariable=self.radius, width=5).pack(
            side="left"
        )
        self.show_mask = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            panel,
            text="Show active layer mask while painting",
            variable=self.show_mask,
            command=self.changed,
        ).pack(anchor="w")
        ttk.Button(
            panel, text="Save RAW + correction project…", command=self.app.export
        ).pack(fill="x", pady=5)
        ttk.Label(
            panel,
            text="Correction is a broad-band estimate, not a calibrated P3 model.\nIt cannot remove solar reflections or recover missing/invalid sensor information.\nPainting freezes live view. RAW is never overwritten; invalid results are marked.",
            wraplength=440,
        ).pack(anchor="w", pady=6)

    def _build_video(self, panel):
        ttk.Label(
            panel, text="Recording rate (sampling captured frames, not sensor control)"
        ).pack(anchor="w")
        self.fps = tk.StringVar(value="25")
        ttk.Combobox(
            panel, values=("1", "2", "5", "10", "15", "25"), textvariable=self.fps
        ).pack(fill="x", pady=6)
        self.experimental = tk.BooleanVar()
        ttk.Checkbutton(
            panel,
            text="Allow experimental rates 0.1–240 fps",
            variable=self.experimental,
        ).pack(anchor="w")
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="Record…", command=self.start_recording).pack(side="left")
        ttk.Button(row, text="Stop recording", command=self.stop_recording).pack(
            side="left"
        )
        ttk.Button(row, text="Open sequence…", command=self.open_sequence).pack(
            side="left"
        )
        self.record_info = tk.StringVar(value="No recording")
        ttk.Label(panel, textvariable=self.record_info, wraplength=440).pack(
            anchor="w", pady=8
        )
        self.position = tk.DoubleVar(value=0)
        self.timeline = ttk.Scale(
            panel, from_=0, to=1, variable=self.position, command=self.seek
        )
        self.timeline.pack(fill="x", pady=15)
        self.time_info = tk.StringVar(value="No sequence open")
        ttk.Label(panel, textvariable=self.time_info).pack(anchor="w")
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=8)
        for label, fn in (
            ("◀ Frame", lambda: self.step(-1)),
            ("Play / pause", self.play),
            ("Frame ▶", lambda: self.step(1)),
            ("Temperature over time…", self.time_profile),
        ):
            ttk.Button(row, text=label, command=fn).pack(fill="x", pady=2)
        ttk.Label(
            panel,
            text="Playback preserves real frame timestamps and allows recoloring, ROI and correction.\nTime profile uses the selected ROI (or the full frame).\nRates above the camera output never synthesize additional measurements.",
            wraplength=440,
        ).pack(anchor="w", pady=12)

    def layer_selected(self):
        index = self.selected_layer()
        if index is not None and index < len(self.app.analysis.layers):
            layer = self.app.analysis.layers[index]
            self.layer_name.set(layer.name)
            self.layer_eps.set(str(layer.emissivity))

    def selected_layer(self):
        return int(self.layers.selection()[0]) if self.layers.selection() else None

    def selected_roi(self):
        return int(self.rois.selection()[0]) if self.rois.selection() else None

    def changed(self):
        self.app.analysis.touch()
        self.app.processor.reset()
        self.app._render_key = None
        self.app.render()
        self.refresh_state()

    def set_tool(self, tool):
        if tool in ("Brush", "Eraser"):
            if self.app.frame is None or self.selected_layer() is None:
                messagebox.showinfo(
                    "Paint", "Load/freeze a frame and select an emissivity layer."
                )
                return
            if not self.app.paused:
                self.app.pause()
        self.app.canvas.tool = tool
        self.tool.set(tool)
        self.app.render()

    def gesture(self, phase, tool, start, end):
        if self.app.frame is None:
            return
        state = self.app.analysis
        if tool in ("Brush", "Eraser"):
            index = self.selected_layer()
            if index is None:
                return
            try:
                radius = int(self.radius.get())
                if not 1 <= radius <= 100:
                    raise ValueError()
            except ValueError:
                self.app.status.set("Brush radius must be 1–100 pixels")
                return
            if phase == "begin":
                self.undo.append((state.layers[index], state.layers[index].mask.copy()))
                self.undo = self.undo[-20:]
            state.paint(index, start, end, radius, tool == "Eraser")
            self.app.processor.reset()
            self.app.render()
        elif phase == "end":
            if len(state.regions) >= 100:
                return
            number = 1
            names = {r.name for r in state.regions}
            while f"{tool} {number}" in names:
                number += 1
            state.regions.append(Region(f"{tool} {number}", tool, start, end))
            self.changed()

    def delete_roi(self):
        index = self.selected_roi()
        if index is not None:
            del self.app.analysis.regions[index]
            self.changed()

    def line_profile(self):
        index = self.selected_roi()
        if index is None or self.app.analysis.regions[index].kind != "Line":
            messagebox.showinfo("Line profile", "Draw and select a Line ROI first.")
            return
        region = self.app.analysis.regions[index]
        plot_window(
            self.app.sidebar,
            region.name,
            lambda: (
                region.profile(self.app.measured)
                if self.app.measured is not None
                else ([], [])
            ),
            "Distance along line (sensor pixels)",
        )

    def roi_csv(self):
        if self.app.measured is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv")
        if path:
            try:
                with open(path, "w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(
                        stream,
                        fieldnames=("name", "kind", "count", "min", "max", "mean"),
                    )
                    writer.writeheader()
                    for region in self.app.analysis.regions:
                        writer.writerow(
                            {
                                "name": region.name,
                                "kind": region.kind,
                                **region.statistics(self.app.measured),
                            }
                        )
            except OSError as exc:
                messagebox.showerror("CSV", str(exc))

    def choose_iso_color(self):
        color = colorchooser.askcolor(self.iso_color, parent=self.window)[1]
        if color:
            self.iso_color = color
            self.apply_isotherm()

    def apply_isotherm(self):
        try:
            low, high = float(self.iso_min.get()), float(self.iso_max.get())
            if not np.isfinite([low, high]).all() or low > high:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Isotherm", "Enter finite minimum ≤ maximum.")
            return
        state = self.app.analysis
        state.isotherm, state.iso_min, state.iso_max, state.iso_color = (
            self.iso_enabled.get(),
            low,
            high,
            self.iso_color,
        )
        self.changed()

    def apply_radiometry(self):
        try:
            params = Radiometry(
                enabled=self.enabled.get(),
                atmospheric_correction=self.atmos_enabled.get(),
                **{key: float(var.get()) for key, var in self.params.items()},
            )
            tau = params.transmission()
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Radiometry", str(exc))
            return
        self.app.analysis.radiometry = params
        self.correction_info.set(
            f"Experimental correction · atmospheric transmission {tau:.6f}"
            if params.enabled
            else "Original sensor temperatures"
        )
        self.changed()

    def add_layer(self):
        if self.app.frame is None:
            return
        try:
            eps = float(self.layer_eps.get())
            if (
                not 0.01 <= eps <= 1
                or not self.layer_name.get().strip()
                or len(self.app.analysis.layers) >= 32
            ):
                raise ValueError()
        except ValueError:
            messagebox.showerror(
                "Layer", "Provide a name and ε between 0.01 and 1 (maximum 32 layers)."
            )
            return
        self.app.analysis.layers.append(
            EmissivityLayer(
                self.layer_name.get().strip(),
                eps,
                np.zeros(self.app.frame.raw.shape, bool),
            )
        )
        self.changed()
        self.layers.selection_set(str(len(self.app.analysis.layers) - 1))

    def update_layer(self):
        index = self.selected_layer()
        if index is None:
            return
        try:
            eps = float(self.layer_eps.get())
            if not 0.01 <= eps <= 1:
                raise ValueError()
        except ValueError:
            return
        self.app.analysis.layers[index].emissivity = eps
        self.changed()

    def toggle_layer(self):
        index = self.selected_layer()
        if index is not None:
            layer = self.app.analysis.layers[index]
            layer.enabled = not layer.enabled
            self.changed()

    def delete_layer(self):
        index = self.selected_layer()
        if index is not None:
            del self.app.analysis.layers[index]
            self.undo.clear()
            self.changed()

    def move_layer(self, direction):
        index = self.selected_layer()
        layers = self.app.analysis.layers
        if index is not None and 0 <= index + direction < len(layers):
            layers[index], layers[index + direction] = (
                layers[index + direction],
                layers[index],
            )
            self.changed()
            self.layers.selection_set(str(index + direction))

    def undo_stroke(self):
        if self.undo:
            layer, mask = self.undo.pop()
            if any(layer is item for item in self.app.analysis.layers):
                layer.mask[:] = mask
                self.changed()

    def refresh_state(self):
        state = self.app.analysis
        self.enabled.set(state.radiometry.enabled)
        self.atmos_enabled.set(state.radiometry.atmospheric_correction)
        for key, var in self.params.items():
            var.set(str(getattr(state.radiometry, key)))
        self.iso_enabled.set(state.isotherm)
        self.iso_min.set(str(state.iso_min))
        self.iso_max.set(str(state.iso_max))
        self.iso_color = state.iso_color
        selected = self.layers.selection()
        self.layers.delete(*self.layers.get_children())
        for i, layer in enumerate(state.layers):
            self.layers.insert(
                "",
                "end",
                iid=str(i),
                values=(layer.name, layer.emissivity, layer.enabled),
            )
        if selected and selected[0] in self.layers.get_children():
            self.layers.selection_set(selected[0])
        self.update_values()

    def update_values(self):
        selected = self.rois.selection()
        self.rois.delete(*self.rois.get_children())
        if self.app.measured is not None:
            for i, region in enumerate(self.app.analysis.regions):
                stats = region.statistics(self.app.measured)
                values = [
                    "—" if stats[key] is None else f"{stats[key]:.3f}"
                    for key in ("min", "max", "mean")
                ]
                self.rois.insert(
                    "", "end", iid=str(i), values=(region.name, *values, stats["count"])
                )
        if selected and selected[0] in self.rois.get_children():
            self.rois.selection_set(selected[0])
        recorder = self.app.recorder
        if recorder:
            self.record_info.set(
                f"Frames {recorder.written} · actual {recorder.actual_fps:.2f} fps · dropped {recorder.dropped}"
                + (f" · ERROR {recorder.error}" if recorder.error else "")
            )
        pending = self.pending_recording
        if pending is not None and not pending.is_alive():
            self.pending_recording = None
            if not self.app.closing and not pending.error and pending.written:
                self.load_sequence(pending.path)
                self.app.sidebar.select("Video")
            elif not pending.error and not pending.written:
                self.record_info.set("Recording finished without frames")
        try:
            result = self.plot_jobs.get_nowait()
        except queue.Empty:
            return
        self.profile_busy = False
        if self.profile_cancel.is_set():
            return
        if isinstance(result, Exception):
            messagebox.showerror("Time profile", str(result))
        else:
            x, y = result
            plot_window(
                self.app.sidebar,
                "Mean temperature over time",
                lambda: (x, y),
                "Elapsed time (s)",
            )

    def start_recording(self):
        if self.app.offline:
            messagebox.showinfo("Recording", "Return to live before recording.")
            return
        if self.app.recorder and self.app.recorder.is_alive():
            return
        try:
            fps = float(self.fps.get())
            if not self.experimental.get() and fps not in (1, 2, 5, 10, 15, 25):
                raise ValueError("Choose a listed rate or enable experimental rates")
            path = filedialog.asksaveasfilename(
                defaultextension=".p3v", filetypes=[("Radiometric sequence", "*.p3v")]
            )
            if not path:
                return
            self.app.recorder = Recorder(path, fps, self.app.capture_metadata())
            self.app.recorder.start()
            self.pending_recording = self.app.recorder
            if self.app.worker:
                self.app.worker.recorder = self.app.recorder
        except (ValueError, OSError) as exc:
            messagebox.showerror("Recording", str(exc))

    def stop_recording(self):
        if self.app.recorder:
            self.app.recorder.stop()

    def open_sequence(self):
        path = filedialog.askopenfilename(filetypes=[("Radiometric sequence", "*.p3v")])
        if not path:
            return
        self.load_sequence(path)

    def load_sequence(self, path):
        """Open only a finalized sequence; reuse this path for recording completion."""
        try:
            sequence = Sequence(path)
            frame = sequence.frame(0)
            self.app.apply_import(frame, sequence.metadata)
            self.stop_playback()
            self.sequence = sequence
            self.timeline.configure(to=max(1, len(sequence.index) - 1))
            self.position.set(0)
            self.time_info.set(f"Frame 1/{len(sequence.index)} · 0.000 s")
        except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
            messagebox.showerror("Sequence", str(exc))

    def seek(self, value):
        if self.sequence is None:
            return
        index = min(len(self.sequence.index) - 1, max(0, int(float(value))))
        try:
            self.app.frame = self.sequence.frame(index)
            self.app.offline = self.app.paused = True
            self.app.pause_button.configure(text="Return to live")
            self.app.processor.reset()
            self.app._render_key = None
            self.app.render()
            self.time_info.set(
                f"Frame {index + 1}/{len(self.sequence.index)} · {self.sequence.times[index]:.3f} s"
            )
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.playing = False
            messagebox.showerror("Sequence frame", str(exc))

    def step(self, direction):
        self.stop_playback()
        self.position.set(max(0, self.position.get() + direction))
        self.seek(self.position.get())

    def play(self):
        if self.playing:
            self.stop_playback()
        else:
            self.playing = True
            self._tick()

    def _tick(self):
        if not self.playing or self.sequence is None or self.app.closing:
            return
        index = int(self.position.get())
        if index >= len(self.sequence.index) - 1:
            self.playing = False
            return
        next_index = index + 1
        delay = max(
            1,
            int((self.sequence.times[next_index] - self.sequence.times[index]) * 1000),
        )

        def advance():
            self.play_timer = None
            if self.playing:
                self.position.set(next_index)
                self.seek(next_index)
                self._tick()

        self.play_timer = self.window.after(delay, advance)

    def time_profile(self):
        if self.sequence is None or self.profile_busy:
            return
        self.profile_busy = True
        self.profile_cancel.clear()
        state = copy.deepcopy(self.app.analysis)
        index = self.selected_roi()
        region = state.regions[index] if index is not None else None
        sequence = self.sequence
        self.record_info.set("Computing time profile…")

        def work():
            try:
                means = []
                for i in range(len(sequence.index)):
                    if self.app.closing or self.profile_cancel.is_set():
                        self.plot_jobs.put(ValueError("Analysis cancelled"))
                        return
                    measured = state.celsius(sequence.frame(i).raw)
                    values = (
                        measured[region.samples(measured.shape)] if region else measured
                    )
                    finite = values[np.isfinite(values)]
                    means.append(float(finite.mean()) if finite.size else np.nan)
                self.plot_jobs.put((sequence.times, np.array(means)))
            except Exception as exc:
                self.plot_jobs.put(exc)

        threading.Thread(target=work, daemon=True).start()
