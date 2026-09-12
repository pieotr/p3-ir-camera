"""Explicit image-export choices keep presentation images distinct from sensor RAW."""

from tkinter import filedialog, messagebox, ttk

import tkinter as tk

import cv2

from .export import save_image


def image_dialog(parent, frame, rgb, on_saved, legend=None):
    """Capture frame/RGB when opening the dialog, so a live feed cannot change the export."""
    dialog = tk.Toplevel(parent)
    dialog.title("Save image")
    dialog.transient(parent)
    box = ttk.Frame(dialog, padding=18)
    box.pack(fill="both", expand=True)
    kind = tk.StringVar(value="jpeg")
    for label, value in [
        ("JPEG · smooth color image", "jpeg"),
        ("PNG · native 16-bit sensor RAW", "raw_png"),
        ("PNG · current color image (lossless)", "color_png"),
    ]:
        ttk.Radiobutton(box, text=label, value=value, variable=kind).pack(
            anchor="w", pady=5
        )
    include_legend = tk.BooleanVar(value=legend is not None)
    ttk.Checkbutton(
        box, text="Include legend (color images only)", variable=include_legend
    ).pack(anchor="w", pady=6)
    scale, quality = tk.StringVar(value="3"), tk.StringVar(value="95")
    for label, variable, low, high in [
        ("JPEG enlargement (bicubic)", scale, 1, 8),
        ("JPEG quality", quality, 1, 100),
    ]:
        ttk.Label(box, text=label).pack(anchor="w", pady=(10, 2))
        ttk.Spinbox(box, from_=low, to=high, textvariable=variable, width=10).pack(
            anchor="w"
        )
    ttk.Label(
        box,
        text="RAW PNG preserves sensor counts and native orientation.\nIt may look dark in ordinary image viewers.\nUse full NPZ data to reopen all channels in this application.",
        wraplength=440,
    ).pack(anchor="w", pady=12)

    def save():
        try:
            factor, q = (
                (int(scale.get()), int(quality.get()))
                if kind.get() == "jpeg"
                else (1, 95)
            )
            if not 1 <= factor <= 8 or not 1 <= q <= 100:
                raise ValueError("JPEG enlargement: 1–8; quality: 1–100")
            ext = ".jpg" if kind.get() == "jpeg" else ".png"
            path = filedialog.asksaveasfilename(
                parent=dialog, defaultextension=ext, filetypes=[("Image", "*" + ext)]
            )
            if not path:
                return
            save_image(
                path,
                frame,
                rgb,
                kind.get(),
                factor,
                q,
                legend if include_legend.get() else None,
            )
            on_saved(path)
            dialog.destroy()
        except (ValueError, OSError, cv2.error) as exc:
            messagebox.showerror("Save failed", str(exc), parent=dialog)

    ttk.Button(box, text="Save…", command=save).pack(fill="x")
