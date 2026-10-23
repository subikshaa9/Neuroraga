"""Offline EEG quality checks and non-destructive filtering for saved sessions."""
from __future__ import annotations

import csv
from functools import lru_cache
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.data_exporter import RECORDINGS_DIR

TARGET_SAMPLE_RATE = 250.0
LOW_CUTOFF_HZ = 0.5
HIGH_CUTOFF_HZ = 40.0
FILTER_ORDER = 4
ARTIFACT_MARGIN_SEC = 0.2
MIN_FLATLINE_SEC = 1.0
FILTER_EDGE_SEC = 1.0
PREVIEW_SECONDS = 5.0
EXPECTED_CHANNELS = ("O1", "O2", "T3", "T4")


def _safe_session(folder: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", folder):
        raise ValueError("Invalid recording selection.")
    root = RECORDINGS_DIR.resolve()
    path = (root / folder).resolve()
    if path.parent != root or not path.is_dir():
        raise ValueError("The selected recording was not found.")
    return path


def _signal_csv_paths(session: Path) -> List[Path]:
    paths = []
    for path in sorted(session.glob("*.csv")):
        if "subjective_ratings" in path.name.lower():
            continue
        try:
            with path.open("r", newline="", encoding="utf-8-sig") as stream:
                headers = next(csv.reader(stream), [])
        except (OSError, UnicodeError, csv.Error):
            continue
        # Process only source exports. A prior processing CSV also carries the
        # original *_raw columns, so requiring that *_filtered is absent avoids
        # ever treating a previous result as a new raw input.
        lower_headers = [h.strip().lower() for h in headers]
        if (any(h.endswith("_raw") for h in lower_headers)
                and not any(h.endswith("_filtered") for h in lower_headers)
                and not path.stem.lower().endswith(("_filtered", "_clean", "_final_filtered"))):
            paths.append(path)
    return paths


def _read_signal_csv(path: Path) -> Dict[str, Any]:
    def number(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("nan")

    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        timestamp_col = next((h for h in headers if h.strip().lower() == "timestamp"), None)
        channel_cols = [h for h in headers if h.strip().lower().endswith("_raw")]
        if not timestamp_col or len(channel_cols) != 4:
            raise ValueError(f"{path.name}: expected Timestamp and four *_raw EEG columns; found {channel_cols}.")
        timestamps_list: List[float] = []
        channel_values: Dict[str, List[float]] = {col[:-4]: [] for col in channel_cols}
        for row in reader:
            timestamps_list.append(number(row.get(timestamp_col)))
            for col in channel_cols:
                channel_values[col[:-4]].append(number(row.get(col)))

    timestamps = np.asarray(timestamps_list, dtype=np.float64)
    channels = {name: np.asarray(values, dtype=np.float64) for name, values in channel_values.items()}
    return {"path": path, "headers": headers, "timestamp_col": timestamp_col, "channel_cols": channel_cols,
            "row_count": len(timestamps), "timestamps": timestamps, "channels": channels}


def _sampling_summary(timestamps: np.ndarray) -> Dict[str, Any]:
    finite = np.isfinite(timestamps)
    diffs = np.diff(timestamps)
    positive = diffs[np.isfinite(diffs) & (diffs > 0)]
    median_dt = float(np.median(positive)) if len(positive) else None
    rate = 1.0 / median_dt if median_dt else None
    valid_diffs = diffs[np.isfinite(diffs)]
    nonmonotonic = int(np.count_nonzero(valid_diffs <= 0))
    gap_limit = 1.5 / TARGET_SAMPLE_RATE
    gaps = int(np.count_nonzero(valid_diffs > gap_limit))
    return {
        "rows": int(len(timestamps)),
        "invalid_timestamps": int(np.count_nonzero(~finite)),
        "nonmonotonic_steps": nonmonotonic,
        "gaps_over_6ms": gaps,
        "sampling_rate_hz": round(rate, 4) if rate else None,
        "target_rate_hz": TARGET_SAMPLE_RATE,
        "duration_sec": round(float(timestamps[finite][-1] - timestamps[finite][0]), 3) if np.count_nonzero(finite) > 1 else 0.0,
        "rate_matches_250hz": bool(rate and abs(rate - TARGET_SAMPLE_RATE) <= TARGET_SAMPLE_RATE * 0.02),
    }


def _artifact_mask(data: Dict[str, Any], fs: float) -> Tuple[np.ndarray, Dict[str, int], np.ndarray]:
    n = len(data["timestamps"])
    mask = np.zeros(n, dtype=bool)
    labels = np.full(n, "", dtype=object)
    reasons = {"missing_or_nonfinite": 0, "timestamp_gap_or_order": 0, "near_full_scale_candidate": 0, "large_amplitude": 0,
               "sudden_jump": 0, "flatline_over_1s": 0, "filter_edge": 0}
    margin = max(1, int(round(ARTIFACT_MARGIN_SEC * fs)))

    def mark(indices: np.ndarray, reason: str, expand: bool = True) -> None:
        if not len(indices):
            return
        reasons[reason] += int(len(indices))
        if expand:
            expanded = np.zeros(n, dtype=bool)
            for offset in range(-margin, margin + 1):
                shifted = indices + offset
                shifted = shifted[(shifted >= 0) & (shifted < n)]
                expanded[shifted] = True
            mask[:] |= expanded
            for idx in np.flatnonzero(expanded):
                labels[idx] = f"{labels[idx]};{reason}".strip(";")
        else:
            mask[indices] = True
            for idx in indices:
                labels[idx] = f"{labels[idx]};{reason}".strip(";")

    timestamps = data["timestamps"]
    bad = ~np.isfinite(timestamps)
    for values in data["channels"].values():
        bad |= ~np.isfinite(values)
    mark(np.flatnonzero(bad), "missing_or_nonfinite", expand=False)

    diffs = np.diff(timestamps)
    bad_steps = np.flatnonzero(~np.isfinite(diffs) | (diffs <= 0) | (diffs > 1.5 / TARGET_SAMPLE_RATE))
    step_samples = np.unique(np.concatenate((bad_steps, bad_steps + 1))) if len(bad_steps) else np.array([], dtype=int)
    mark(step_samples, "timestamp_gap_or_order")

    flat_tolerance = np.finfo(np.float64).eps
    for values in data["channels"].values():
        finite_values = values[np.isfinite(values)]
        if len(finite_values) < 3:
            continue
        # The supplied headband specification says ±0.4 V. The SDK does not
        # document the raw getter's unit, so this is recorded as a numeric
        # full-scale candidate rather than asserted to be volts.
        rail_idx = np.flatnonzero(np.isfinite(values) & (np.abs(values) >= 0.399))
        mark(rail_idx, "near_full_scale_candidate")
        center = float(np.median(finite_values))
        mad = float(np.median(np.abs(finite_values - center))) * 1.4826
        amplitude_limit = max(8.0 * mad, 100.0 * flat_tolerance * max(1.0, abs(center)))
        amp_idx = np.flatnonzero(np.isfinite(values) & (np.abs(values - center) > amplitude_limit))
        mark(amp_idx, "large_amplitude")

        delta = np.diff(values)
        finite_delta = delta[np.isfinite(delta)]
        if len(finite_delta):
            dcenter = float(np.median(finite_delta))
            dmad = float(np.median(np.abs(finite_delta - dcenter))) * 1.4826
            jump_limit = max(10.0 * dmad, 100.0 * flat_tolerance * max(1.0, float(np.max(np.abs(finite_values)))))
            jump_idx = np.flatnonzero(np.isfinite(delta) & (np.abs(delta - dcenter) > jump_limit)) + 1
            mark(jump_idx, "sudden_jump")

            equal = np.isfinite(delta) & (np.abs(delta) <= flat_tolerance * max(1.0, float(np.max(np.abs(finite_values)))))
            starts = np.flatnonzero(equal & np.r_[True, ~equal[:-1]])
            ends = np.flatnonzero(equal & np.r_[~equal[1:], True]) + 1
            for start, end in zip(starts, ends):
                if end - start + 1 >= int(fs * MIN_FLATLINE_SEC):
                    mark(np.arange(start, min(end + 1, n)), "flatline_over_1s")

    return mask, reasons, labels


def _artifact_masks_by_channel(data: Dict[str, Any], fs: float) -> Tuple[Dict[str, np.ndarray], Dict[str, Dict[str, int]], Dict[str, np.ndarray]]:
    masks: Dict[str, np.ndarray] = {}
    counts: Dict[str, Dict[str, int]] = {}
    labels: Dict[str, np.ndarray] = {}
    for channel, values in data["channels"].items():
        channel_data = {"timestamps": data["timestamps"], "channels": {channel: values}}
        masks[channel], counts[channel], labels[channel] = _artifact_mask(channel_data, fs)
    return masks, counts, labels


def _mask_intervals(mask: np.ndarray, labels: np.ndarray, timestamps: np.ndarray,
                    fs: float, limit: int = 12) -> List[Dict[str, Any]]:
    intervals: List[Dict[str, Any]] = []
    indices = np.flatnonzero(mask)
    if not len(indices):
        return intervals
    starts = [int(indices[0])]
    ends: List[int] = []
    for previous, current in zip(indices[:-1], indices[1:]):
        if current > previous + 1:
            ends.append(int(previous))
            starts.append(int(current))
    ends.append(int(indices[-1]))
    origin_indices = np.flatnonzero(np.isfinite(timestamps))
    origin = timestamps[origin_indices[0]] if len(origin_indices) else 0.0
    for start, end in zip(starts, ends):
        first_ts, last_ts = timestamps[start], timestamps[end]
        reasons = sorted({reason for label in labels[start:end + 1]
                          for reason in str(label).split(";") if reason})
        intervals.append({"start_sec": round(float(first_ts - origin), 3) if np.isfinite(first_ts) else None,
                          "end_sec": round(float(last_ts - origin), 3) if np.isfinite(last_ts) else None,
                          "duration_sec": round((end - start + 1) / fs, 3), "reasons": reasons})
    intervals.sort(key=lambda item: item["duration_sec"], reverse=True)
    return intervals[:limit]


def _detrend_channel(values: np.ndarray, fs: float) -> np.ndarray:
    """Remove channel DC offset and best-fit linear trend within one valid span."""
    t = np.arange(len(values), dtype=np.float64) / fs
    centered_t = t - float(np.mean(t))
    centered_values = values - float(np.mean(values))
    denominator = float(np.dot(centered_t, centered_t))
    slope = float(np.dot(centered_t, centered_values) / denominator) if denominator else 0.0
    return centered_values - slope * centered_t


def _filter_span(values: np.ndarray, fs: float) -> np.ndarray:
    """Detrend, then apply an FFT-domain zero-phase Butterworth response."""
    values = _detrend_channel(values, fs)
    pad = min(int(round(3.0 * fs)), len(values) - 1)
    extended = np.pad(values, (pad, pad), mode="reflect") if pad else values.copy()
    frequencies = np.fft.rfftfreq(len(extended), d=1.0 / fs)
    response = np.zeros_like(frequencies)
    positive = frequencies > 0
    f = frequencies[positive]
    low = 1.0 / np.sqrt(1.0 + np.power(LOW_CUTOFF_HZ / f, 2 * FILTER_ORDER))
    high = 1.0 / np.sqrt(1.0 + np.power(f / HIGH_CUTOFF_HZ, 2 * FILTER_ORDER))
    response[positive] = low * high
    filtered = np.fft.irfft(np.fft.rfft(extended) * response, n=len(extended))
    return filtered[pad:pad + len(values)] if pad else filtered


def _analytic_filter_gain(frequency_hz: float) -> float:
    if frequency_hz <= 0:
        return 0.0
    highpass = 1.0 / math.sqrt(1.0 + (LOW_CUTOFF_HZ / frequency_hz) ** (2 * FILTER_ORDER))
    lowpass = 1.0 / math.sqrt(1.0 + (frequency_hz / HIGH_CUTOFF_HZ) ** (2 * FILTER_ORDER))
    return highpass * lowpass


@lru_cache(maxsize=4)
def _validate_filter_response(fs: float = TARGET_SAMPLE_RATE) -> Dict[str, Any]:
    """Compare measured sine gains with the specified frequency response."""
    frequencies = (0.1, 0.25, 0.5, 1.0, 10.0, 30.0, 40.0, 50.0, 60.0, 100.0)
    duration = 60.0
    t = np.arange(int(duration * fs), dtype=np.float64) / fs
    inner = (t >= 5.0) & (t <= duration - 5.0)
    samples_t = t[inner]
    validation = []
    for frequency in frequencies:
        tone = np.sin(2.0 * math.pi * frequency * t + 0.17)
        filtered = _filter_span(tone, fs)[inner]
        sine = np.sin(2.0 * math.pi * frequency * samples_t + 0.17)
        cosine = np.cos(2.0 * math.pi * frequency * samples_t + 0.17)
        measured = 2.0 * math.hypot(float(np.dot(filtered, sine)), float(np.dot(filtered, cosine))) / len(samples_t)
        expected = _analytic_filter_gain(frequency)
        validation.append({"frequency_hz": frequency, "expected_gain": round(expected, 5),
                           "measured_gain": round(measured, 5), "absolute_error": round(abs(measured - expected), 5)})
    max_error = max((point["absolute_error"] for point in validation), default=0.0)
    return {"method": "Synthetic sine inputs, measured interior amplitude ratio versus analytic Butterworth response",
            "tolerance_absolute_gain": 0.03, "max_absolute_error": max_error,
            "passed": bool(max_error <= 0.03), "points": validation}


def _filter_channels(data: Dict[str, Any], fs: float) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray]]:
    timestamps = data["timestamps"]
    n = len(timestamps)
    time_ok = np.isfinite(timestamps)
    starts_at_gap = np.zeros(n, dtype=bool)
    starts_at_gap[0:1] = True
    if n > 1:
        dt = np.diff(timestamps)
        starts_at_gap[1:] = ~np.isfinite(dt) | (dt <= 0) | (dt > 1.5 / TARGET_SAMPLE_RATE)
    results: Dict[str, np.ndarray] = {}
    edge_masks: Dict[str, np.ndarray] = {}
    edge_n = int(round(FILTER_EDGE_SEC * fs))

    for name, values in data["channels"].items():
        out = np.full(n, np.nan, dtype=np.float64)
        edge_mask = np.zeros(n, dtype=bool)
        valid = time_ok & np.isfinite(values)
        i = 0
        while i < n:
            if not valid[i]:
                i += 1
                continue
            start = i
            i += 1
            while i < n and valid[i] and not starts_at_gap[i]:
                i += 1
            end = i
            if end - start >= int(5.0 * fs):
                out[start:end] = _filter_span(values[start:end], fs)
                edge_mask[start:min(end, start + edge_n)] = True
                edge_mask[max(start, end - edge_n):end] = True
        results[name] = out
        edge_masks[name] = edge_mask
    return results, edge_masks


def _preview(data: Dict[str, Any], filtered: Optional[Dict[str, np.ndarray]] = None,
             flagged: Optional[Dict[str, np.ndarray]] = None) -> Dict[str, Any]:
    timestamps = data["timestamps"]
    valid = np.flatnonzero(np.isfinite(timestamps))
    if len(valid) == 0:
        return {"channels": {}}
    start = valid[0]
    # When flags are available, show the most affected 5-second interval
    # (prefer T4) so a quiet opening does not make the diagnostic look blank.
    if flagged and len(timestamps) > int(PREVIEW_SECONDS * TARGET_SAMPLE_RATE):
        width = int(PREVIEW_SECONDS * TARGET_SAMPLE_RATE)
        preferred = flagged.get("T4", next(iter(flagged.values())))
        if len(preferred) >= width:
            density = np.convolve(preferred.astype(np.int32), np.ones(width, dtype=np.int32), mode="valid")
            candidate = int(np.argmax(density))
            if density[candidate] > 0:
                start = candidate
    end = start
    while end + 1 < len(timestamps) and timestamps[end + 1] - timestamps[end] <= 1.5 / TARGET_SAMPLE_RATE and timestamps[end + 1] - timestamps[start] < PREVIEW_SECONDS:
        end += 1
    indices = np.arange(start, end + 1)
    step = max(1, int(math.ceil(len(indices) / 1250)))
    indices = indices[::step]
    result = {}
    for name, values in data["channels"].items():
        series = {"raw": [float(x) if np.isfinite(x) else None for x in values[indices]]}
        if filtered is not None:
            series["filtered"] = [float(x) if np.isfinite(x) else None for x in filtered[name][indices]]
        if flagged is not None:
            series["flagged"] = [bool(x) for x in flagged[name][indices]]
        result[name] = series
    return {"channels": result, "sample_count": int(len(indices)), "seconds": PREVIEW_SECONDS,
            "start_sec": round(float(timestamps[start] - timestamps[valid[0]]), 3),
            "sample_rate_hz": TARGET_SAMPLE_RATE}


def _inspect_file(path: Path) -> Dict[str, Any]:
    data = _read_signal_csv(path)
    sampling = _sampling_summary(data["timestamps"])
    missing = {name: int(np.count_nonzero(~np.isfinite(values))) for name, values in data["channels"].items()}
    screen_fs = sampling["sampling_rate_hz"] or TARGET_SAMPLE_RATE
    masks_by_channel, counts_by_channel, labels_by_channel = _artifact_masks_by_channel(data, float(screen_fs))
    artifact_mask = np.logical_or.reduce(list(masks_by_channel.values()))
    artifact_counts = {name: sum(counts.get(name, 0) for counts in counts_by_channel.values())
                       for name in next(iter(counts_by_channel.values()), {})}
    by_channel_screen = {
        name: {"flagged_samples": int(np.count_nonzero(mask)),
               "flagged_percent": round(100.0 * float(np.mean(mask)), 2) if len(mask) else 0.0,
               "counts_by_rule": counts_by_channel[name]}
        for name, mask in masks_by_channel.items()
    }
    channel_names = [col[:-4] for col in data["channel_cols"]]
    unexpected = [name for name in channel_names if name.upper() not in EXPECTED_CHANNELS]
    missing_expected = [name for name in EXPECTED_CHANNELS if name not in [c.upper() for c in channel_names]]
    warnings = []
    if not sampling["rate_matches_250hz"]:
        warnings.append("Timestamp-derived sampling rate is outside 250 Hz ±2%.")
    if sampling["invalid_timestamps"] or sampling["nonmonotonic_steps"] or sampling["gaps_over_6ms"]:
        warnings.append("Timestamp sequence contains missing values, nonmonotonic steps, or gaps.")
    if any(missing.values()):
        warnings.append("One or more EEG channels contain missing or non-numeric samples.")
    if unexpected or missing_expected:
        warnings.append("Channel labels differ from the expected O1, O2, T3, T4 montage; no relabeling is applied.")
    artifact_screen = {"flagged_samples": int(np.count_nonzero(artifact_mask)),
                       "flagged_percent": round(100.0 * float(np.mean(artifact_mask)), 2) if len(artifact_mask) else 0.0,
                       "counts_by_rule": artifact_counts, "by_channel": by_channel_screen}
    # Give the reviewer concrete time intervals, especially for channels such
    # as T4 whose saturation/motion flags may dominate a recording.
    intervals_by_channel = {name: _mask_intervals(mask, labels_by_channel[name], data["timestamps"], float(screen_fs))
                            for name, mask in masks_by_channel.items()}
    artifact_screen["longest_intervals_by_channel"] = intervals_by_channel
    return {"filename": path.name, "headers": data["headers"], "channel_names": channel_names,
            "missing_values_by_channel": missing, "sampling": sampling, "warnings": warnings,
            "artifact_screen": artifact_screen,
            "preview": _preview(data, flagged=masks_by_channel) if "master" in path.name.lower() else None,
            "_data": data}


def inspect_session(folder: str) -> Dict[str, Any]:
    session = _safe_session(folder)
    files = []
    for path in _signal_csv_paths(session):
        try:
            entry = _inspect_file(path)
            entry.pop("_data")
            files.append(entry)
        except Exception as exc:
            files.append({"filename": path.name, "error": str(exc), "warnings": ["File could not be validated."]})
    if not files:
        raise ValueError("No EEG CSV files with four *_raw channels were found in this recording.")
    return {"folder_name": session.name, "file_count": len(files), "files": files,
            "filter_response_validation": _validate_filter_response(TARGET_SAMPLE_RATE),
            "signal_units": {"status": "UNCONFIRMED_PHYSICAL_UNIT",
                             "label": "Capsule SDK raw-value units; the local SDK bindings do not document a physical unit or conversion."},
            "previous_processing": _latest_processing_preview(session)}


def _latest_processing_preview(session: Path) -> Optional[Dict[str, Any]]:
    master_sources = [path for path in session.glob("*_master.csv")]
    if not master_sources:
        return None
    master_source = master_sources[0]
    for folder in sorted(session.glob("signal_processing_*"), key=lambda p: p.name, reverse=True):
        processed_master = folder / f"{master_source.stem}_filtered.csv"
        report_path = folder / "processing_report.json"
        if not processed_master.is_file():
            continue
        preview_channels: Dict[str, Dict[str, List[Optional[float]]]] = {}
        try:
            with processed_master.open("r", newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                headers = reader.fieldnames or []
                raw_columns = [h for h in headers if h.strip().lower().endswith("_raw")]
                has_generic_flag = "ArtifactFlag" in headers
                for raw_column in raw_columns:
                    channel = raw_column[:-4]
                    filtered_column = f"{channel}_filtered"
                    if filtered_column in headers:
                        preview_channels[channel] = {"raw": [], "filtered": []}
                if not preview_channels:
                    continue
                for row in reader:
                    try:
                        timestamp = float(row.get("Timestamp", ""))
                    except (TypeError, ValueError):
                        continue
                    for channel, series in preview_channels.items():
                        for key, col in (("raw", f"{channel}_raw"), ("filtered", f"{channel}_filtered")):
                            try:
                                value = float(row.get(col, ""))
                                series[key].append(value if math.isfinite(value) else None)
                            except (TypeError, ValueError):
                                series[key].append(None)
                        flag_column = f"{channel}_ArtifactFlag" if f"{channel}_ArtifactFlag" in headers else "ArtifactFlag" if has_generic_flag else None
                        if flag_column:
                            series.setdefault("flagged", []).append(str(row.get(flag_column, "0")).strip().lower() in ("1", "true", "yes"))
            # Focus the diagnostic on a flagged interval when possible. This
            # avoids presenting a quiet opening as a blank comparison.
            width = int(PREVIEW_SECONDS * TARGET_SAMPLE_RATE)
            focus = 0
            focus_flags = preview_channels.get("T4", {}).get("flagged", [])
            if len(focus_flags) >= width:
                counts = np.convolve(np.asarray(focus_flags, dtype=np.int32), np.ones(width, dtype=np.int32), mode="valid")
                if len(counts) and int(np.max(counts)) > 0:
                    focus = int(np.argmax(counts))
            for series in preview_channels.values():
                for key in ("raw", "filtered", "flagged"):
                    if key in series:
                        series[key] = series[key][focus:focus + width]
            report: Dict[str, Any] = {}
            if report_path.is_file():
                try:
                    with report_path.open("r", encoding="utf-8") as stream:
                        saved_report = json.load(stream)
                    report = {"created_at": saved_report.get("created_at"),
                              "settings": saved_report.get("settings", {}),
                              "files": saved_report.get("files", [])}
                except (OSError, json.JSONDecodeError):
                    pass
            settings = report.get("settings", {})
            return {"folder_name": folder.name, "preview": {"channels": preview_channels,
                    "sample_count": max((len(s["raw"]) for s in preview_channels.values()), default=0),
                    "seconds": PREVIEW_SECONDS, "start_sec": round(focus / TARGET_SAMPLE_RATE, 3),
                    "sample_rate_hz": TARGET_SAMPLE_RATE},
                    "report": report,
                    "unit_status": settings.get("unit_status", "NOT_RECORDED_IN_THIS_RUN"),
                    "has_filter_validation": bool(settings.get("filter_response_validation"))}
        except (OSError, UnicodeError, csv.Error):
            continue
    return None


def _write_outputs(data: Dict[str, Any], filtered: Dict[str, np.ndarray],
                   artifact_by_channel: Dict[str, np.ndarray],
                   reasons_by_channel: Dict[str, Dict[str, int]],
                   labels_by_channel: Dict[str, np.ndarray],
                   edge_by_channel: Dict[str, np.ndarray], output_dir: Path) -> Dict[str, Any]:
    source: Path = data["path"]
    row_count = data["row_count"]
    channel_names = list(data["channels"].keys())
    flag_headers = [column for name in channel_names for column in (f"{name}_ArtifactFlag", f"{name}_ArtifactReasons")]
    headers = list(data["headers"]) + [f"{name}_filtered" for name in channel_names] + flag_headers + ["AnyArtifactFlag"]
    clean_headers = [h for h in data["headers"] if h not in data["channel_cols"]]
    clean_headers += [f"{name}_filtered" for name in channel_names] + flag_headers + ["AnyArtifactFlag"]
    filtered_name = source.stem + "_filtered.csv"
    clean_name = source.stem + "_clean.csv"
    filtered_path = output_dir / filtered_name
    clean_path = output_dir / clean_name
    flagged_by_channel: Dict[str, np.ndarray] = {}
    clean_counts_by_channel: Dict[str, int] = {}
    for name in channel_names:
        artifact_mask = artifact_by_channel[name] | edge_by_channel[name]
        unfiltered = ~np.isfinite(filtered[name])
        flagged = artifact_mask | unfiltered
        reasons = reasons_by_channel[name]
        edge_added = edge_by_channel[name] & ~artifact_by_channel[name]
        reasons["filter_edge"] = int(np.count_nonzero(edge_added))
        reasons["unfiltered_or_too_short"] = int(np.count_nonzero(unfiltered & ~artifact_mask))
        for idx in np.flatnonzero(edge_by_channel[name]):
            labels_by_channel[name][idx] = f"{labels_by_channel[name][idx]};filter_edge".strip(";")
        for idx in np.flatnonzero(unfiltered):
            labels_by_channel[name][idx] = f"{labels_by_channel[name][idx]};unfiltered_or_too_short".strip(";")
        flagged_by_channel[name] = flagged
        clean_counts_by_channel[name] = int(row_count - np.count_nonzero(flagged))
    any_flagged = np.logical_or.reduce(list(flagged_by_channel.values()))
    clean_count = int(np.count_nonzero(~any_flagged))
    with source.open("r", newline="", encoding="utf-8-sig") as source_stream, filtered_path.open("w", newline="", encoding="utf-8") as f_all, clean_path.open("w", newline="", encoding="utf-8") as f_clean:
        all_writer = csv.writer(f_all)
        clean_writer = csv.writer(f_clean)
        source_reader = csv.DictReader(source_stream)
        all_writer.writerow(headers)
        clean_writer.writerow(clean_headers)
        for idx, row in enumerate(source_reader):
            out = [row.get(h, "") for h in data["headers"]]
            out.extend(float(filtered[name][idx]) if np.isfinite(filtered[name][idx]) else "" for name in channel_names)
            flags = [value for name in channel_names for value in
                     (int(bool(flagged_by_channel[name][idx])), str(labels_by_channel[name][idx]))]
            out.extend(flags)
            out.append(int(bool(any_flagged[idx])))
            all_writer.writerow(out)
            clean_out = [row.get(h, "") for h in data["headers"] if h not in data["channel_cols"]]
            clean_out.extend(float(filtered[name][idx]) if not flagged_by_channel[name][idx] else "" for name in channel_names)
            clean_out.extend(flags)
            clean_out.append(int(bool(any_flagged[idx])))
            clean_writer.writerow(clean_out)
    return {"source_file": source.name, "filtered_file": filtered_name, "clean_file": clean_name,
            "rows": row_count, "clean_rows": clean_count, "flagged_rows": int(np.count_nonzero(any_flagged)),
            "clean_samples_by_channel": clean_counts_by_channel,
            "flagged_samples_by_channel": {name: int(np.count_nonzero(mask)) for name, mask in flagged_by_channel.items()},
            "artifact_rules_by_channel": reasons_by_channel}


def _write_final_output(data: Dict[str, Any], filtered: Dict[str, np.ndarray],
                        artifact: Dict[str, np.ndarray], labels: Dict[str, np.ndarray],
                        edge: Dict[str, np.ndarray], output_dir: Path, fs: float) -> Dict[str, Any]:
    """Write one all-samples final export, retaining raw values and all flags."""
    source: Path = data["path"]
    channels = list(data["channels"])
    headers = ["Recording_Condition" if h == "Segment" else h for h in data["headers"]]
    added = [f"{name}_filtered" for name in channels]
    added += [column for name in channels for column in
              (f"{name}_ArtifactFlag", f"{name}_ArtifactReasons", f"{name}_FilterEdgeFlag")]
    added += ["AnyArtifactFlag"]
    output_name = f"{source.stem}_final_filtered.csv"
    output_path = output_dir / output_name
    filtered_masks: Dict[str, np.ndarray] = {}
    for name in channels:
        filtered_masks[name] = artifact[name] | edge[name] | ~np.isfinite(filtered[name])
        for idx in np.flatnonzero(edge[name]):
            labels[name][idx] = f"{labels[name][idx]};filter_edge".strip(";")
        for idx in np.flatnonzero(~np.isfinite(filtered[name])):
            labels[name][idx] = f"{labels[name][idx]};unfiltered_or_invalid".strip(";")
    any_flagged = np.logical_or.reduce(list(filtered_masks.values()))
    source_rows = 0
    with source.open("r", newline="", encoding="utf-8-sig") as source_stream, output_path.open("w", newline="", encoding="utf-8") as target_stream:
        reader = csv.DictReader(source_stream)
        writer = csv.writer(target_stream)
        writer.writerow(headers + added)
        for idx, row in enumerate(reader):
            # Raw values and original timestamps are copied from the source
            # row. Only the condition header is renamed in this export.
            row_values = [row.get("Segment", "") if h == "Recording_Condition" else row.get(h, "")
                          for h in headers]
            row_values += [float(filtered[name][idx]) if np.isfinite(filtered[name][idx]) else ""
                           for name in channels]
            for name in channels:
                row_values.extend((int(bool(filtered_masks[name][idx])), str(labels[name][idx]), int(bool(edge[name][idx]))))
            row_values.append(int(bool(any_flagged[idx])))
            writer.writerow(row_values)
            source_rows += 1

    # Re-read the actual CSV and validate preserved columns and row count.
    output_data = _read_signal_csv(output_path)
    if "Segment" in data["headers"]:
        condition_ok = "Recording_Condition" in output_data["headers"] and "Segment" not in output_data["headers"]
        if condition_ok:
            with source.open("r", newline="", encoding="utf-8-sig") as source_stream, output_path.open("r", newline="", encoding="utf-8-sig") as output_stream:
                for source_row, output_row in zip(csv.DictReader(source_stream), csv.DictReader(output_stream)):
                    if source_row.get("Segment", "") != output_row.get("Recording_Condition", ""):
                        condition_ok = False
                        break
    else:
        condition_ok = True
    row_count_ok = output_data["row_count"] == data["row_count"] == source_rows
    timestamps_equal = bool(np.array_equal(output_data["timestamps"], data["timestamps"], equal_nan=True))
    raw_values_equal = all(np.array_equal(output_data["channels"][name], data["channels"][name], equal_nan=True)
                           for name in channels)
    # _read_signal_csv reads *_raw columns only, so directly validate added
    # filtered columns using a small streaming pass.
    filtered_finite_counts = {name: 0 for name in channels}
    with output_path.open("r", newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            for name in channels:
                try:
                    value = float(row.get(f"{name}_filtered", ""))
                    filtered_finite_counts[name] += int(math.isfinite(value))
                except (TypeError, ValueError):
                    pass
    output_fs = _sampling_summary(output_data["timestamps"])["sampling_rate_hz"]
    validation = {"row_count_preserved": row_count_ok, "timestamps_preserved_exactly": timestamps_equal,
                  "original_raw_channel_values_preserved_exactly": raw_values_equal,
                  "recording_condition_renamed_and_values_preserved": condition_ok,
                  "timestamp_rate_hz": output_fs,
                  "filtered_finite_sample_counts": filtered_finite_counts,
                  "filtering_source_is_original_raw_csv": True,
                  "filter_applied_once_to_original_source": True}
    validation["passed"] = bool(row_count_ok and timestamps_equal and raw_values_equal and condition_ok
                                and output_fs is not None and abs(output_fs - fs) < 1e-6
                                and all(0 < count <= data["row_count"] for count in filtered_finite_counts.values()))
    return {"source_file": source.name, "final_filtered_file": output_name, "rows": source_rows,
            "channel_names": channels, "sample_rate_hz": fs, "quality_flagged_samples_by_channel": {
                name: int(np.count_nonzero(mask)) for name, mask in filtered_masks.items()},
            "quality_flagged_percent_by_channel": {
                name: round(100.0 * float(np.mean(mask)), 2) if len(mask) else 0.0
                for name, mask in filtered_masks.items()},
            "filter_edge_samples_by_channel": {name: int(np.count_nonzero(edge[name])) for name in channels},
            "validation": validation, "quality_concern": "Review channel artifact flags; flagged data are retained, not deleted."}


def process_all_available_final() -> Dict[str, Any]:
    """Create one final output and report per available participant recording."""
    root = RECORDINGS_DIR.resolve()
    sessions: List[Dict[str, Any]] = []
    batch_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for session in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name):
        sources = _signal_csv_paths(session)
        if not sources:
            continue
        output_dir = session / f"signal_processing_final_{batch_stamp}"
        output_dir.mkdir(parents=False, exist_ok=False)
        files: List[Dict[str, Any]] = []
        skipped: List[Dict[str, str]] = []
        validation_by_frequency = None
        for source in sources:
            try:
                inspection = _inspect_file(source)
                data = inspection["_data"]
                sampling = inspection["sampling"]
                fs = sampling["sampling_rate_hz"]
                if not fs or not sampling["rate_matches_250hz"]:
                    raise ValueError("Timestamp-derived sample rate is outside 250 Hz ±2%; not filtered.")
                response_check = _validate_filter_response(float(fs))
                if not response_check["passed"]:
                    raise ValueError("Synthetic Butterworth response validation failed; not filtered.")
                artifact, _counts, labels = _artifact_masks_by_channel(data, float(fs))
                filtered, edge = _filter_channels(data, float(fs))
                result = _write_final_output(data, filtered, artifact, labels, edge, output_dir, float(fs))
                result["sampling"] = sampling
                result["longest_flagged_intervals_by_channel"] = {
                    name: _mask_intervals(artifact[name] | edge[name] | ~np.isfinite(filtered[name]),
                                          labels[name], data["timestamps"], float(fs))
                    for name in data["channels"]}
                result["warnings"] = inspection["warnings"]
                if not result["validation"]["passed"]:
                    result["quality_concern"] = "TECHNICAL VALIDATION FAILED; do not use without investigation."
                elif any(value > 0 for value in result["quality_flagged_samples_by_channel"].values()):
                    result["quality_concern"] = "TECHNICAL VALIDATION PASSED; artifact/edge flags remain and require review."
                files.append(result)
                validation_by_frequency = validation_by_frequency or response_check
            except Exception as exc:
                skipped.append({"source_file": source.name, "error": str(exc)})
        report = {
            "participant_recording_folder": session.name,
            "participant_id": session.name.split("_")[0],
            "output_folder": output_dir.name,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "input_selection": "Original session-root CSVs with four *_raw channels and no *_filtered columns. Prior processing subfolders and filtered exports are excluded.",
            "filter": {"type": "4th-order Butterworth high-pass and low-pass magnitude responses combined as a 0.5–40 Hz bandpass",
                       "implementation": "Zero-phase FFT-domain application of the Butterworth magnitude response with 3-second reflection padding; each timestamp-contiguous valid span is filtered independently.",
                       "order_per_corner": FILTER_ORDER, "low_cutoff_hz": LOW_CUTOFF_HZ,
                       "high_cutoff_hz": HIGH_CUTOFF_HZ, "notch_50_hz": False,
                       "dc_offset_and_linear_detrend": "Removed per channel and per contiguous finite span before filtering, matching the existing signal-processing pipeline.",
                       "sample_rate_hz": "Verified independently from each file's timestamp median interval; expected about 250 Hz.",
                       "edge_handling": f"First/last {FILTER_EDGE_SEC:g} second of each filtered span flagged; spans shorter than 5 seconds are left unfiltered and their filtered values remain blank.",
                       "response_validation": validation_by_frequency},
            "column_handling": {"preserve_timestamp": True, "preserve_original_channel_values": True,
                                "rename_only_in_export": {"Segment": "Recording_Condition"},
                                "condition_values_unchanged": True, "retain_artifact_samples": True,
                                "filtered_channels": list(EXPECTED_CHANNELS)},
            "signal_units": {"status": "UNCONFIRMED_PHYSICAL_UNIT", "stored_values": "Native Capsule SDK raw-value units; no volts or microvolts conversion is documented or applied."},
            "quality_flag_rules": {"near_full_scale_candidate": "Absolute sample >=0.399 native units, provisionally flagged because it is numerically near the supplied +/-0.4 device range; physical unit is unconfirmed.",
                                   "large_amplitude": "More than 8 robust MAD standard deviations from the channel median.",
                                   "sudden_jump": "One-sample change more than 10 robust MAD standard deviations of first differences.",
                                   "flatline_over_1s": "Consecutive identical values for at least one second.",
                                   "timestamp_gap_or_order": "Nonpositive step or step exceeding 1.5/250 seconds.",
                                   "filter_edge": f"First/last {FILTER_EDGE_SEC:g} second of filtered span.",
                                   "unfiltered_or_invalid": "No filtered value for invalid or shorter-than-5-second spans."},
            "acceptance": "Technical file checks do not certify EEG as artifact-free or music-related. Physical units remain unconfirmed. Review flagged intervals, especially T4, before scientific interpretation or segmentation.",
            "files": files, "skipped_files": skipped,
            "technical_validation_passed_files": sum(bool(item["validation"]["passed"]) for item in files),
            "files_with_unresolved_quality_flags": sum(any(v > 0 for v in item["quality_flagged_samples_by_channel"].values()) for item in files),
        }
        with (output_dir / "processing_report.json").open("w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
        sessions.append({"participant_recording_folder": session.name, "output_folder": output_dir.name,
                         "report_file": "processing_report.json", "files": files,
                         "skipped_files": skipped})
    return {"created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "recordings_processed": len(sessions),
            "recordings": sessions}


def process_session(folder: str) -> Dict[str, Any]:
    session = _safe_session(folder)
    source_paths = _signal_csv_paths(session)
    if not source_paths:
        raise ValueError("No EEG CSV files with four *_raw channels were found in this recording.")
    filter_validation = _validate_filter_response(TARGET_SAMPLE_RATE)
    if not filter_validation["passed"]:
        raise ValueError("Filter response validation failed; processing was not started.")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_dir = session / f"signal_processing_{stamp}"
    output_dir.mkdir(parents=False, exist_ok=False)
    reports = []
    preview = None
    fatal = []
    for path in source_paths:
        try:
            report = _inspect_file(path)
            data = report.pop("_data")
            sampling = report["sampling"]
            fs = sampling["sampling_rate_hz"]
            if not sampling["rate_matches_250hz"] or not fs:
                raise ValueError("Filtering skipped: timestamps do not verify a 250 Hz sample rate within ±2%.")
            if sampling["invalid_timestamps"] or sampling["nonmonotonic_steps"]:
                raise ValueError("Filtering skipped: timestamps contain missing or nonmonotonic values.")
            artifact, rules, labels = _artifact_masks_by_channel(data, float(fs))
            filtered, edge_mask = _filter_channels(data, float(fs))
            file_result = _write_outputs(data, filtered, artifact, rules, labels, edge_mask, output_dir)
            file_result.update({"channel_names": report["channel_names"], "sampling": sampling,
                                "missing_values_by_channel": report["missing_values_by_channel"],
                                "warnings": report["warnings"],
                                "longest_artifact_intervals_by_channel": {
                                    name: _mask_intervals(artifact[name] | edge_mask[name], labels[name], data["timestamps"], float(fs))
                                    for name in data["channels"]}})
            reports.append(file_result)
            if preview is None and "master" in path.name.lower():
                preview_flags = {name: artifact[name] | edge_mask[name] | ~np.isfinite(filtered[name])
                                 for name in data["channels"]}
                preview = _preview(data, filtered, preview_flags)
        except Exception as exc:
            fatal.append({"filename": path.name, "error": str(exc)})

    if not reports:
        try:
            output_dir.rmdir()
        except OSError:
            pass
        raise ValueError("No files could be filtered. " + "; ".join(item["filename"] + ": " + item["error"] for item in fatal))

    settings = {
        "method": "Per-channel DC removal and linear detrending, then FFT-domain zero-phase Butterworth magnitude response with 3-second reflection padding",
        "order": FILTER_ORDER, "highpass_hz": LOW_CUTOFF_HZ, "lowpass_hz": HIGH_CUTOFF_HZ,
        "sample_rate_hz": TARGET_SAMPLE_RATE, "notch_filter": False,
        "dc_and_detrend": "Applied independently to each channel and valid span before filtering: subtract its mean DC offset and least-squares linear trend. The 0.5 Hz high-pass also attenuates remaining slow drift.",
        "signal_units": "Capsule SDK raw-value units; the local SDK API exposes float values but does not document a physical unit. No conversion to volts or microvolts is applied.",
        "unit_status": "UNCONFIRMED_PHYSICAL_UNIT",
        "acceptance_status": {"filter_response": "PASS", "signal_units": "UNCONFIRMED", "ready_for_segmentation": False},
        "filter_response_validation": filter_validation,
        "columnwise_processing": True,
        "artifact_rules": {
            "near_full_scale_candidate": "Absolute raw sample >=0.399 native units, numerically near the user-supplied ±0.4 range; raw SDK units are unconfirmed, so this is a candidate rail flag only.",
            "large_amplitude": "Absolute deviation greater than 8 robust MAD-based standard deviations from channel median.",
            "sudden_jump": "One-sample change greater than 10 robust MAD-based standard deviations of the first difference.",
            "flatline_over_1s": "Consecutive unchanged values lasting at least 1 second.",
            "timestamp_gap_or_order": "Nonpositive interval or timestamp gap above 1.5 / 250 seconds.",
            "filter_edge": f"First and last {FILTER_EDGE_SEC:g} second of each valid filtering span.",
            "unfiltered_or_too_short": "Samples that could not be filtered because the channel span was shorter than 5 seconds or contained invalid data.",
            "margin": f"Artifact flags expanded by ±{ARTIFACT_MARGIN_SEC:g} seconds.",
        },
        "note": "Artifact flags are screening aids, not proof that all artifacts or non-neural signals are removed. Music-related EEG cannot be isolated by filtering alone. Clean outputs retain every timestamp and blank only affected channel samples; unaffected channels and intervals are not discarded. Physical units remain unconfirmed, so outputs are not approved for segmentation."
    }
    result = {"source_folder": session.name, "processing_folder": output_dir.name,
              "created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "settings": settings,
              "files": reports, "skipped_files": fatal, "preview": preview}
    with (output_dir / "processing_report.json").open("w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    return result

