"""Thermal canvas with sensor-coordinate picking and temperature pixel labels."""

import tkinter as tk

import cv2
import numpy as np

from .processing import pixel_label


class ThermalCanvas(tk.Canvas):
    """Zoom is screen pixels per sensor pixel. Pan and picking share one transform."""

    def __init__(self, parent, on_pixel, on_zoom):
        super().__init__(parent, background="#10151d", highlightthickness=0)
        self.on_pixel, self.on_zoom = on_pixel, on_zoom
        self.rgb = self.raw = self.coordinates = None
        self.pixel_scale = 3.0
        self.offset = [0.0, 0.0]
        self.auto_fit = True
        self.markers = True
        self.show_legend = True
        self.legend_data: tuple | None = None
        self.legend_rect = None
        self.legend_photo = None
        self.photo = None
        self.empty_message = "Waiting for thermal frames…"
        self.bind(
            "<Configure>", lambda e: self.fit() if self.auto_fit else self.redraw()
        )
        self.bind("<Motion>", self.hover)
        self.bind("<Leave>", lambda e: self.on_pixel(None))
        self.bind(
            "<MouseWheel>", lambda e: self.zoom(1.25 if e.delta > 0 else 0.8, e.x, e.y)
        )
        self.bind("<Button-4>", lambda e: self.zoom(1.25, e.x, e.y))
        self.bind("<Button-5>", lambda e: self.zoom(0.8, e.x, e.y))
        self.bind("<ButtonPress-1>", self.start_pan)
        self.bind("<B1-Motion>", self.pan)
        self.bind("<Double-Button-1>", lambda e: self.fit())

    def set_frame(self, rgb, raw, coordinates):
        self.rgb, self.raw, self.coordinates = rgb, raw, coordinates
        if self.auto_fit:
            self.fit()
        else:
            self.redraw()
        x, y = (
            self.winfo_pointerx() - self.winfo_rootx(),
            self.winfo_pointery() - self.winfo_rooty(),
        )
        self.pick(x, y)

    def fit(self):
        self.auto_fit = True
        if self.raw is None:
            return
        h, w = self.raw.shape
        self.pixel_scale = max(
            0.1, min(self.winfo_width() / w, self.winfo_height() / h) * 0.95
        )
        self.offset = [
            (self.winfo_width() - w * self.pixel_scale) / 2,
            (self.winfo_height() - h * self.pixel_scale) / 2,
        ]
        self.redraw()

    def zoom(self, factor, x=None, y=None):
        self.auto_fit = False
        x = self.winfo_width() / 2 if x is None else x
        y = self.winfo_height() / 2 if y is None else y
        new = min(256.0, max(0.25, self.pixel_scale * factor))
        ratio = new / self.pixel_scale
        self.offset = [
            x - (x - self.offset[0]) * ratio,
            y - (y - self.offset[1]) * ratio,
        ]
        self.pixel_scale = new
        self.redraw()

    def move_image(self, dx, dy):
        """Move the image using screen-space buttons, with the same transform as dragging."""
        self.auto_fit = False
        self.offset = [self.offset[0] + dx, self.offset[1] + dy]
        self.redraw()

    def inspect(self):
        """Ctrl+X selects a legible native-pixel inspection magnification."""
        self.zoom(128 / self.pixel_scale)

    def start_pan(self, event):
        self.drag = (event.x, event.y, *self.offset)

    def pan(self, event):
        self.auto_fit = False
        x, y, ox, oy = self.drag
        self.offset = [ox + event.x - x, oy + event.y - y]
        self.redraw()
        self.hover(event)

    def hover(self, event):
        self.pick(event.x, event.y)

    def pick(self, x, y):
        if self.raw is None or self.coordinates is None:
            return
        if self.legend_rect is not None:
            left, top, right, bottom = self.legend_rect
            if left <= x <= right and top <= y <= bottom:
                self.on_pixel(None)
                return
        col, row = (
            int(np.floor((x - self.offset[0]) / self.pixel_scale)),
            int(np.floor((y - self.offset[1]) / self.pixel_scale)),
        )
        if 0 <= row < self.raw.shape[0] and 0 <= col < self.raw.shape[1]:
            sensor_y, sensor_x = self.coordinates[row, col]
            self.on_pixel((int(sensor_x), int(sensor_y), int(self.raw[row, col])))
        else:
            self.on_pixel(None)

    def redraw(self):
        self.delete("all")
        self.legend_rect = None
        self.on_zoom(self.pixel_scale)
        if self.raw is None or self.rgb is None:
            self.create_text(
                self.winfo_width() / 2,
                self.winfo_height() / 2,
                text=self.empty_message,
                fill="#93a3b8",
                font=("TkDefaultFont", 16),
            )
            return
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        ox, oy = self.offset
        # Render only the viewport, never a 65536 × 49152 full zoom image.
        matrix = np.array(
            [
                [self.pixel_scale, 0, ox + (self.pixel_scale - 1) / 2],
                [0, self.pixel_scale, oy + (self.pixel_scale - 1) / 2],
            ],
            dtype=np.float64,
        )
        view = cv2.warpAffine(
            self.rgb,
            matrix,
            (width, height),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(16, 21, 29),
        )
        self.photo = tk.PhotoImage(
            data=f"P6\n{width} {height}\n255\n".encode() + view.tobytes(), format="PPM"
        )
        self.create_image(0, 0, image=self.photo, anchor="nw")
        h, w = self.raw.shape
        if self.pixel_scale >= 28:
            x0, x1 = (
                max(0, int(-ox / self.pixel_scale)),
                min(w, int((width - ox) / self.pixel_scale) + 1),
            )
            y0, y1 = (
                max(0, int(-oy / self.pixel_scale)),
                min(h, int((height - oy) / self.pixel_scale) + 1),
            )
            for col in range(x0, x1 + 1):
                x = ox + col * self.pixel_scale
                self.create_line(
                    x,
                    max(0, oy),
                    x,
                    min(height, oy + h * self.pixel_scale),
                    fill="#677384",
                )
            for row in range(y0, y1 + 1):
                y = oy + row * self.pixel_scale
                self.create_line(
                    max(0, ox),
                    y,
                    min(width, ox + w * self.pixel_scale),
                    y,
                    fill="#677384",
                )
            # Full precision labels become legible once each cell is wide enough.
            if self.pixel_scale >= 96:
                for row in range(y0, y1):
                    for col in range(x0, x1):
                        x, y = (
                            ox + (col + 0.5) * self.pixel_scale,
                            oy + (row + 0.5) * self.pixel_scale,
                        )
                        label = pixel_label(self.raw[row, col]).replace(" °C", "\n°C")
                        self.create_text(
                            x + 1,
                            y + 1,
                            text=label,
                            fill="black",
                            font=("TkDefaultFont", 9, "bold"),
                        )
                        self.create_text(
                            x,
                            y,
                            text=label,
                            fill="white",
                            font=("TkDefaultFont", 9, "bold"),
                        )
        if self.markers:
            for index, color, label in [
                (np.argmin(self.raw), "#64c9ff", "MIN"),
                (np.argmax(self.raw), "#ff7d7d", "MAX"),
            ]:
                row, col = np.unravel_index(index, self.raw.shape)
                x, y = (
                    ox + (col + 0.5) * self.pixel_scale,
                    oy + (row + 0.5) * self.pixel_scale,
                )
                self.create_line(x - 7, y, x + 7, y, fill=color, width=2)
                self.create_line(x, y - 7, x, y + 7, fill=color, width=2)
                self.create_text(x + 10, y - 10, text=label, fill=color, anchor="w")

        self.draw_legend()

    def draw_legend(self):
        """Overlay a labeled ramp; intensity legends deliberately never claim Celsius."""
        if not self.show_legend or self.legend_data is None:
            return
        colors, low, high, unit = self.legend_data[:4]
        bands = self.legend_data[4] if len(self.legend_data) > 4 else None
        width, height = self.winfo_width(), self.winfo_height()
        if width < 180 or height < 180:
            return
        x, y = width - 115, 18
        bar_height = min(240, height - 85)
        self.legend_rect = (x - 8, y - 8, width - 8, y + bar_height + 45)
        self.create_rectangle(*self.legend_rect, fill="#10151d", outline="#536175")
        self.create_text(
            x + 5,
            y + 4,
            text=unit,
            fill="white",
            anchor="nw",
            font=("TkDefaultFont", 9),
        )
        ramp = cv2.resize(
            colors[::-1].reshape(256, 1, 3),
            (18, bar_height),
            interpolation=cv2.INTER_NEAREST,
        )
        self.legend_photo = tk.PhotoImage(
            data=f"P6\n18 {bar_height}\n255\n".encode() + ramp.tobytes(), format="PPM"
        )
        self.create_image(x, y + 25, image=self.legend_photo, anchor="nw")
        for index, fraction in enumerate((0, 0.25, 0.5, 0.75, 1)):
            value = high + (low - high) * fraction
            label = f"{value:.2f}"
            if bands is not None:
                bounds = bands[index]
                label = "—" if bounds is None else f"{bounds[0]:.2f}\n{bounds[1]:.2f}"
            self.create_text(
                x + 25,
                y + 25 + bar_height * fraction,
                text=label,
                anchor="w",
                fill="white",
                font=("TkDefaultFont", 9),
            )
