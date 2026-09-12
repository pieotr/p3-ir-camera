"""Display processing only: measurements always use original uint16 samples."""

from dataclasses import dataclass

import cv2
import numpy as np


PALETTES = {
    "Inferno": cv2.COLORMAP_INFERNO,
    "Magma": cv2.COLORMAP_MAGMA,
    "Viridis": cv2.COLORMAP_VIRIDIS,
    "Turbo": cv2.COLORMAP_TURBO,
    "Rainbow": cv2.COLORMAP_JET,
    "White hot": None,
    "Black hot": None,
}


def temperature(raw):
    """Decode 1/64 K samples in float64; do not quantize through float32."""
    return np.asarray(raw, dtype=np.float64) / 64.0 - 273.15


def pixel_label(raw):
    """Six decimals represent every native sample exactly in decimal Celsius."""
    return f"{float(temperature(raw)):.6f} °C"


def orient(array, rotation=0, mirror=False):
    """Apply identical counterclockwise quarter turns and mirror to all planes."""
    result = np.rot90(array, rotation)
    return np.fliplr(result) if mirror else result


@dataclass
class DisplaySettings:
    """Editable display parameters; none mutate the captured frame."""

    mode: str = "Temperature"
    palette: str = "Inferno"
    range_mode: str = "Auto percentile"
    minimum: float = 15.0
    maximum: float = 40.0
    alpha: float = 0.35
    detail: bool = False  # DDE only; legacy snapshots migrate the combined flag
    clahe: bool = False


class Processor:
    """Per-session temporal filter and range state, reset on reconnect/settings."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.bounds = None

    def render(self, raw, brightness, settings, custom_palette=None):
        """Return RGB sensor-sized image and actual display limits (or None)."""
        data = temperature(raw)
        if settings.mode == "Filtered temperature":
            self.previous = (
                data.copy()
                if self.previous is None
                else (settings.alpha * data + (1 - settings.alpha) * self.previous)
            )
            data = self.previous
        if custom_palette is not None:
            # Absolute temperature stops must never be distorted by AGC/CLAHE/DDE.
            return custom_palette.colorize(data), (
                custom_palette.stops[0][0],
                custom_palette.stops[-1][0],
            )
        if settings.mode == "Factory brightness":
            gray = brightness
            limits = None
        else:
            if settings.mode == "Raw counts":
                data = raw.astype(np.float64)
            if settings.range_mode == "Fixed" and settings.mode != "Raw counts":
                low, high = settings.minimum, settings.maximum
                if high <= low:
                    raise ValueError("Maximum must be greater than minimum")
            else:
                low, high = np.percentile(data, (1, 99))
                if self.bounds is not None:
                    low, high = 0.15 * np.array([low, high]) + 0.85 * self.bounds
                self.bounds = np.array([low, high])
            limits = (float(low), float(high))
            gray = (np.clip((data - low) / max(high - low, 1e-9), 0, 1) * 255).astype(
                np.uint8
            )
        if settings.clahe:
            gray = cv2.createCLAHE(2.0, (8, 8)).apply(gray)
            limits = None
        if settings.detail:
            gray = cv2.addWeighted(
                gray, 1.3, cv2.GaussianBlur(gray, (3, 3), 0), -0.3, 0
            )
            limits = None  # nonlinear enhancement invalidates a quantitative legend
        if settings.palette in ("White hot", "Black hot"):
            if settings.palette == "Black hot":
                gray = 255 - gray
            rgb = np.repeat(gray[..., None], 3, axis=2)
        else:
            rgb = cv2.cvtColor(
                cv2.applyColorMap(gray, PALETTES[settings.palette]), cv2.COLOR_BGR2RGB
            )
        return rgb, limits


def legend_colors(settings, custom_palette=None):
    """Return low-to-high RGB ramp; callers attach temperature or intensity units."""
    if custom_palette is not None:
        return custom_palette.colorize(
            np.linspace(custom_palette.stops[0][0], custom_palette.stops[-1][0], 256)
        )
    gray = np.arange(256, dtype=np.uint8).reshape(256, 1)
    if settings.palette in ("White hot", "Black hot"):
        if settings.palette == "Black hot":
            gray = 255 - gray
        return np.repeat(gray, 3, axis=1)
    return cv2.cvtColor(
        cv2.applyColorMap(gray, PALETTES[settings.palette]), cv2.COLOR_BGR2RGB
    ).reshape(256, 3)
