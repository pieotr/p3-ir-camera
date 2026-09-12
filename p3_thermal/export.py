"""Lossless snapshot export, suitable for subsequent radiometric analysis."""

from datetime import datetime, timezone
from pathlib import Path

import json

import numpy as np


def save_snapshot(path, frame, metadata):
    """Save native planes and self-describing JSON; never save display-filtered raw."""
    metadata = {
        **metadata,
        "saved_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_timestamp": frame.timestamp,
        "conversion": "celsius = raw / 64 - 273.15",
        "raw_unit": "1/64 K",
    }
    with Path(path).open("wb") as stream:
        np.savez_compressed(
            stream,
            raw=frame.raw,
            brightness=frame.brightness,
            metadata=json.dumps(metadata),
        )


def load_snapshot(path):
    """Load validated native planes without pickle; legacy NPZ snapshots are accepted."""
    import zipfile

    from .acquisition import Frame

    if not zipfile.is_zipfile(path):
        raise ValueError("Not a valid NPZ snapshot")
    with zipfile.ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > 32_000_000:
            raise ValueError("Snapshot exceeds 32 MB uncompressed")
    with np.load(path, allow_pickle=False) as data:
        raw = data["raw"]
        brightness = data["brightness"]
        if raw.dtype != np.uint16 or raw.ndim != 2 or not 0 < raw.size <= 1_048_576:
            raise ValueError("RAW must be a nonempty 2D uint16 sensor plane")
        if brightness.dtype != np.uint8 or brightness.shape != raw.shape:
            raise ValueError("Brightness must be uint8 with the same dimensions as RAW")
        metadata = json.loads(str(data["metadata"])) if "metadata" in data else {}
        if not isinstance(metadata, dict):
            raise ValueError("Snapshot metadata must be a JSON object")
        if metadata.get("snapshot_version", 1) not in (1, 2):
            raise ValueError("Unsupported snapshot version")
        if metadata.get("raw_unit", "1/64 K") != "1/64 K":
            raise ValueError("Unsupported RAW units")
        stamp = float(metadata.get("monotonic_timestamp", 0.0))
        if not np.isfinite(stamp):
            raise ValueError("Invalid acquisition timestamp")
        return Frame(raw.copy(), brightness.copy(), stamp), metadata


def save_image(path, frame, rgb, kind="jpeg", scale=3, quality=95, legend=None):
    """Export smooth presentation JPEG, native uint16 RAW PNG, or rendered RGB PNG."""
    import cv2

    if kind == "raw_png":
        image = frame.raw  # preserve native orientation and every bit
        parameters = []
    elif kind in ("jpeg", "color_png"):
        image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        parameters = []
        if kind == "jpeg":
            if not 1 <= scale <= 8 or not 1 <= quality <= 100:
                raise ValueError("JPEG scale must be 1–8 and quality 1–100")
            image = cv2.resize(
                image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
            )
            parameters = [cv2.IMWRITE_JPEG_QUALITY, quality]
    else:
        raise ValueError("Unknown image export format")
    if legend is not None and kind != "raw_png":
        image = append_legend(image, legend)
    extension = ".jpg" if kind == "jpeg" else ".png"
    success, encoded = cv2.imencode(extension, image, parameters)
    if not success:
        raise OSError("Image encoder failed")
    Path(path).write_bytes(encoded.tobytes())


def append_legend(image, legend):
    """Append an RGB-palette legend to a BGR presentation image, keeping RAW untouched."""
    import cv2

    colors, low, high, unit = legend
    h, w = image.shape[:2]
    height = max(h, 160)
    output = np.full((height, w + 140, 3), (29, 21, 16), np.uint8)
    output[:h, :w] = image
    ramp = cv2.resize(
        colors[::-1].reshape(256, 1, 3),
        (20, height - 50),
        interpolation=cv2.INTER_NEAREST,
    )
    output[30 : height - 20, w + 10 : w + 30] = ramp[..., ::-1]
    cv2.putText(
        output,
        unit.replace("°", ""),
        (w + 10, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    for fraction in (0, 0.25, 0.5, 0.75, 1):
        value = high + (low - high) * fraction
        y = int(30 + (height - 50) * fraction)
        cv2.putText(
            output,
            f"{value:.2f}",
            (w + 37, min(height - 5, y + 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return output


def snapshot_display_settings(metadata):
    """Validate optional presentation metadata, including migration of the old combined enhancement flag."""
    from .processing import DisplaySettings

    data = metadata.get("display", {})
    if not isinstance(data, dict):
        raise ValueError("Display metadata must be an object")
    settings = DisplaySettings()
    for field in (
        "mode",
        "palette",
        "range_mode",
        "minimum",
        "maximum",
        "alpha",
        "detail",
        "clahe",
    ):
        if field in data:
            setattr(settings, field, data[field])
    if settings.mode not in (
        "Temperature",
        "Filtered temperature",
        "Raw counts",
        "Factory brightness",
    ) or settings.range_mode not in ("Auto percentile", "Fixed"):
        raise ValueError("Invalid snapshot display mode")
    if not isinstance(settings.palette, str):
        raise ValueError("Invalid snapshot palette name")
    numbers = (settings.minimum, settings.maximum, settings.alpha)
    if any(
        isinstance(n, bool) or not isinstance(n, (int, float)) or not np.isfinite(n)
        for n in numbers
    ):
        raise ValueError("Invalid display range or filter weight")
    if settings.maximum <= settings.minimum or not 0.05 <= settings.alpha <= 1:
        raise ValueError("Invalid display range or filter weight")
    if not isinstance(settings.detail, bool) or not isinstance(settings.clahe, bool):
        raise ValueError("Enhancement flags must be booleans")
    if metadata.get("snapshot_version", 1) == 1 and "clahe" not in data:
        settings.clahe = settings.detail
    return settings
