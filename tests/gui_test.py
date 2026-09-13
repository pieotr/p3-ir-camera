"""Opt-in real Tk smoke test: P3_GUI_TEST=1 python -m pytest tests/gui_test.py."""

import os
import time

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("P3_GUI_TEST") != "1", reason="requires desktop session"
)


@pytest.mark.filterwarnings("ignore:Due to '_pack_'.*:DeprecationWarning")
def test_desktop_zoom_sources_and_shutdown():
    import tkinter as tk

    from p3_thermal.app import ThermalApp

    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    app = ThermalApp(root, demo=os.environ.get("P3_GUI_CAMERA") != "1")
    try:
        deadline = time.monotonic() + 12
        while app.frame is None and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        assert app.frame is not None
        app.pause()
        for mode in (
            "Temperature",
            "Filtered temperature",
            "Raw counts",
            "Factory brightness",
        ):
            app.mode.set(mode)
            app.update_settings()
            root.update()
        app.clahe.set(True)
        app.update_settings()
        assert app.canvas.legend_data[3] == "°C min/max"
        assert len(app.canvas.legend_data[4]) == 5
        app.detail.set(True)
        app.dde_strength.set(3.0)
        app.update_settings()
        assert app.settings.dde_strength == 3.0
        app.canvas.inspect()
        root.update()
        labels = [
            app.canvas.itemcget(item, "text")
            for item in app.canvas.find_all()
            if app.canvas.type(item) == "text"
        ]
        assert any("°C" in label and "." in label for label in labels)
        app.rotate()
        app.flip()
        app.canvas.pick(
            app.canvas.offset[0] + 0.5 * app.canvas.pixel_scale,
            app.canvas.offset[1] + 0.5 * app.canvas.pixel_scale,
        )
        assert "RAW" in app.pixel_text.get()
        assert not errors
    finally:
        app.close()
        deadline = time.monotonic() + 4
        while app.worker.is_alive() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        assert not app.worker.is_alive()
        try:
            root.update()
            root.destroy()
        except tk.TclError:
            pass


def test_disconnect_waits_reconnects_and_close_cancels_retries(monkeypatch):
    import queue
    import threading
    import tkinter as tk

    import numpy as np

    from p3_thermal import app as module
    from p3_thermal.acquisition import Frame

    workers = []

    class FakeAcquisition:
        def __init__(self, *args):
            self.frames = queue.Queue()
            self.events = queue.Queue()
            self.stop_event = threading.Event()
            self.alive = False
            workers.append(self)

        def start(self):
            # First attempt fails (app starts without a camera).
            self.alive = len(workers) > 1
            if self.alive:
                self.frames.put(
                    Frame(
                        np.full((8, 8), 19000, np.uint16),
                        np.zeros((8, 8), np.uint8),
                        time.monotonic(),
                    )
                )
            else:
                self.events.put("Disconnected / error: camera not found")

        def is_alive(self):
            return self.alive and not self.stop_event.is_set()

    monkeypatch.setattr(module, "Acquisition", FakeAcquisition)
    monkeypatch.setattr(module.ThermalApp, "RECONNECT_DELAY", 0.15)
    root = tk.Tk()
    app = module.ThermalApp(root)

    def until(predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert predicate()

    try:
        until(lambda: app._waiting)
        assert root.winfo_exists() and not app.closing
        assert "No camera" in app.status.get()
        until(lambda: app.frame is not None)
        assert len(workers) == 2
        app.paused = True
        workers[-1].alive = False
        until(lambda: app._waiting)
        assert app.frame is None and app.canvas.raw is None
        assert not app.closing
        until(lambda: app.frame is not None)
        assert len(workers) == 3 and not app.paused
        workers[-1].alive = False
        until(lambda: app._waiting)
        count = len(workers)
        app.close()
        time.sleep(0.2)
        assert len(workers) == count
    finally:
        if not app.closing:
            app.close()


@pytest.fixture(autouse=True)
def isolated_palette_config(monkeypatch, tmp_path):
    """GUI tests never read or overwrite the user's saved palettes."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def test_imported_frame_survives_live_frames_and_disconnect(monkeypatch, tmp_path):
    from dataclasses import asdict

    import tkinter as tk

    import numpy as np

    from p3_thermal.acquisition import Frame
    from p3_thermal.app import ThermalApp
    from p3_thermal.export import save_snapshot
    from p3_thermal.palettes import TemperaturePalette
    from p3_thermal.processing import DisplaySettings

    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    app = ThermalApp(root, demo=True)
    raw = np.arange(192, dtype=np.uint16).reshape(12, 16) + 19000
    frame = Frame(raw, np.zeros_like(raw, dtype=np.uint8), 10)
    palette = TemperaturePalette.from_dict(
        {
            "version": 1,
            "name": "Imported board",
            "stops": [[20, "#000000"], [30, "#FFFFFF"]],
        }
    )
    path = tmp_path / "capture.npz"
    save_snapshot(
        path,
        frame,
        {
            "snapshot_version": 2,
            "palette_spec": palette.to_dict(),
            "display": asdict(DisplaySettings(palette=palette.name)),
            "rotation_quarters_ccw": 1,
            "mirror": True,
        },
    )
    try:
        root.update()
        app.import_snapshot(path)
        app.canvas.inspect()
        root.update()
        imported_rgb = app.canvas.rgb.copy()
        app.palette.set("White hot")
        app.update_settings()
        assert not np.array_equal(imported_rgb, app.canvas.rgb)
        np.testing.assert_array_equal(app.frame.raw, raw)
        app.canvas.move_image(60, -60)
        app.worker.stop_event.set()
        app.worker.join(2)
        app.demo = False  # exercise the same disconnected-camera path as live mode
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert app.offline and app.paused and not app.closing
        np.testing.assert_array_equal(app.frame.raw, raw)
        assert app.canvas.legend_data[-1] == "°C"
        app.library.delete(palette.name)
        app.palette_changed(None)
        assert "Inferno" in app._combos["Palette"]["values"]
        assert not errors
    finally:
        app.close()
