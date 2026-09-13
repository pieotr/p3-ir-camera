# Thermal Studio architecture

## Module boundaries

| Module | Responsibility and extension point |
| --- | --- |
| `p3_viewer.py` | CLI and Tk startup; importing does not open USB or a window. |
| `p3_camera.py` | USB protocol, models, frame decoding and native temperature conversion. No GUI dependency. |
| `acquisition.py` | Immutable-field `Frame` container, sole camera owner, command/event queues and latest-frame delivery. |
| `processing.py` | Display settings, normalization, temporal filtering, CLAHE, DDE, LUTs and orientation. |
| `canvas.py` | Viewport rendering, sensor-coordinate picking, zoom/pan, ROI previews, annotations and legend. |
| `app.py` | Session state, theme, controls, offline/live transitions and Tk polling. |
| `sidebar.py` | Persistent section navigation and disposable embedded editor pages. |
| `export.py` | NPZ validation/migration, RAW import and presentation-image export. |
| `palettes.py` | Absolute-temperature palette validation, mapping and atomic JSON persistence. |
| `palette_ui.py` | Embedded stop editor and user preset management. |
| `image_ui.py` | Embedded format, quality, enlargement and legend choices. |
| `analysis.py` | Sensor-coordinate ROIs, correction model, emissivity masks and serialized analysis state. |
| `analysis_ui.py` | Measurements, RAW editing, embedded plots, recording controls and playback. |
| `recording.py` | Bounded writer queue, SQLite sequence persistence and random-access reads. |

Module names without paths refer to `p3_thermal/`.

## Data flow and ownership

```text
USB / demo → Acquisition → Frame(raw, brightness, timestamp)
                            ├→ Recorder queue → SQLite
                            └→ latest-frame GUI queue
                                ├→ AnalysisState → measured temperatures
                                └→ Processor → RGB → orientation → ThermalCanvas
```

RAW is H×W uint16; brightness is H×W uint8. Acquisition copies both arrays before publication. Consumers must treat them as immutable: the frozen dataclass protects attributes but NumPy arrays remain technically writable. Timestamps use the host monotonic clock, not sensor exposure time.

The GUI queue holds one frame and replaces old frames to prevent increasing latency. Recording receives frames **before** this queue. Its separate queue holds 128 frames; overflow is counted. USB code never runs inside Tk callbacks. Tk polls frame/event queues every 40 ms.

## Camera lifecycle

The acquisition thread performs connect → initialize → start streaming → read frames, and disconnects in `finally`. libusb resources are disposed even when stopping the stream fails. Partial initialization is also cleaned up.

Bulk transfers have 500 ms timeouts, while frame assembly and post-shutter reads have a five-second deadline checked between transfers. The last transfer can extend this deadline by its own timeout. Cancellation is checked between transfers. Invalid synchronization markers are skipped. A control-command timeout is reported while frame acquisition can continue; other session errors trigger cleanup and reconnect handling.

The UI remains open after failure and retries two seconds after the previous worker finishes. No concurrent camera sessions are started. The first new live frame resumes viewing, including a previously frozen live view. Imported offline frames are isolated from connection events and incoming frames. Return to live restores normal acquisition handling.

Close signals cancellation and continues processing Tk events while waiting for USB and writer cleanup. Initialization/control transfers can delay closure by several seconds. Daemon threads are a process-exit fallback, not the normal cleanup mechanism.

## Image versus measurement

Native conversion uses float64 and six-decimal formatting to preserve 1/64 K encoding. Never derive measurements from RGB, EMA history or resized exports. `AnalysisState.celsius` optionally derives corrected estimates from original RAW; invalid results remain NaN, appear gray, and are excluded from statistics.

Rendering is cached by frame/settings/analysis revision. Changing orientation must not apply temporal filtering to the same frame repeatedly. Reset processing state after settings changes, imports and reconnection. Auto range uses 1st/99th percentiles with a 0.15 adaptation weight. Temporal temperature EMA defaults to 0.35 with a configurable 0.05–1 weight.

DDE is float32 unsharp masking with Gaussian sigma 1.2 sensor pixels and strength 0–4, default 1.5. Rounding/clipping occurs at the final 8-bit mapping. CLAHE and DDE are independent. Absolute temperature palettes bypass these operations and normalization.

Factory brightness and nonlinear filters cannot provide a global one-to-one temperature legend. Their five palette-index bands are 0–31, 32–95, 96–159, 160–223 and 224–255. Each reports observed min/max temperatures of pixels mapped into that band. Empty bands have no value; bands may overlap in temperature or be non-monotonic.

Orientation applies counterclockwise `np.rot90`, then optional horizontal mirroring, to RGB, RAW and a native sensor-coordinate map. Picking uses floor on the viewport coordinate, then this map. ROI and brush gestures are converted to native coordinates before storage. Drag previews use the same inverse mapping as committed shapes. Rotation/zoom never modify stored ROI geometry.

The canvas renders only a viewport-sized bitmap with `warpAffine`; it does not allocate a full 256× enlargement. Nearest-neighbor interpolation preserves native pixel boundaries. Legend space is excluded from picking.

## Single-window UI

`Sidebar` registers pages by English section name. Selecting a page changes visibility without destroying persistent state. Temporary editors replace their own previous page; disposing a plot cancels its refresh timer. File and color selection still use native dialogs. The main horizontal pane allows users to allocate space to the image or controls.

The theme explicitly specifies table background/text, selection colors, input fields and readonly/disabled states. New editable widgets should use these ttk styles rather than platform defaults that may mix dark text with dark backgrounds.

Recording completion is observed during regular UI polling. `pending_recording` identifies the active recording awaiting completion. It is cleared before loading to prevent reentrant imports. Only a stopped writer with no error and at least one committed frame is opened; shutdown does not auto-import. `load_sequence` is shared by manual and automatic opening.

## Analysis and persistence

`AnalysisState` holds radiometric parameters, regions, masks and isotherm settings. Its revision invalidates display caches. Later enabled masks override earlier ones. Shape changes clear incompatible spatial data. Masks use packed-bit metadata in NPZ; optional `corrected_celsius` is an export convenience, while imports recompute from original RAW and parameters.

The recording thread alone owns the write connection. `submit` samples FPS and enqueues; it does not perform disk I/O on the acquisition thread. `Sequence` uses short-lived read-only connections. Time-profile computation uses a background thread and a copy of analysis settings. Playback schedules frames using their actual timestamp differences.

## Extension contracts

- Add processing modes with explicit reset behavior; never modify `Frame.raw`.
- Add ROI geometry through `Region.samples`, then implement matching committed and provisional canvas rendering.
- Add persistent tool pages through `Sidebar.add`; use `editor` for replaceable pages and `remove` when disposing them.
- A future calibrated radiometry model must preserve original readings separately from modeled results and identify its calibration assumptions.
- Future lock-in processing should consume frames/timestamps from acquisition, with explicit stimulus control and cancellation; it must not own another USB reader.
- Keep import validation, serialization and numeric processing independent of Tk and cover them with headless tests.

The `p3-viewer` command, direct Python entry point and camera API remain available. Legacy viewer internals and lock-in CLI switches are not part of the new public interface. AUTO gain explicitly raises an unsupported-mode error.
