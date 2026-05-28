"""Spectrum scanner — rtl_power sweep returning peaks above noise floor."""

import csv
import subprocess
import tempfile
from pathlib import Path


RTL_POWER = "rtl_power"
RTL_BIAST = "rtl_biast"


def _enable_biast() -> None:
    """Enable bias-T on the V4 dongle (powers external LNAs; harmless for passive antennas)."""
    try:
        subprocess.run([RTL_BIAST, "-d", "0", "-b", "1"], capture_output=True, timeout=5)
    except Exception:
        pass


def scan(start_mhz: float, end_mhz: float, step_khz: float = 200, duration_seconds: int = 8) -> dict:
    """
    Wideband power sweep using rtl_power.
    Returns a list of frequency bins and highlights peaks above the noise floor.
    """
    if end_mhz <= start_mhz:
        return {"error": "end_mhz must be greater than start_mhz"}
    if end_mhz - start_mhz > 1000:
        return {"error": "Scan range capped at 1000 MHz per call to keep it useful"}

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        out_path = Path(f.name)

    _enable_biast()

    cmd = [
        RTL_POWER,
        "-f", f"{start_mhz}M:{end_mhz}M:{step_khz}k",
        "-g", "33.8",
        "-i", "1",
        "-e", str(duration_seconds),
        str(out_path),
    ]

    try:
        subprocess.run(cmd, capture_output=True, timeout=duration_seconds + 10)
    except subprocess.TimeoutExpired:
        pass
    except FileNotFoundError:
        return {"error": "rtl_power not found — reinstall librtlsdr"}

    if not out_path.exists() or out_path.stat().st_size == 0:
        return {"error": "No data returned. Dongle may be in use."}

    # Parse CSV: date, time, start_hz, stop_hz, step_hz, samples, power...
    bins: dict[float, list[float]] = {}
    try:
        with out_path.open() as fh:
            for row in csv.reader(fh):
                if len(row) < 7:
                    continue
                try:
                    start_hz = float(row[2])
                    step_hz = float(row[4])
                    powers = [float(v) for v in row[6:] if v.strip()]
                    for i, p in enumerate(powers):
                        freq_mhz = round((start_hz + i * step_hz) / 1e6, 4)
                        bins.setdefault(freq_mhz, []).append(p)
                except ValueError:
                    continue
    finally:
        out_path.unlink(missing_ok=True)

    if not bins:
        return {"error": "CSV parse failed — unexpected rtl_power output format"}

    # Average across sweeps
    averaged = {f: sum(v) / len(v) for f, v in bins.items()}

    # Noise floor estimate: 10th percentile
    sorted_vals = sorted(averaged.values())
    noise_floor = sorted_vals[max(0, len(sorted_vals) // 10)]
    threshold = noise_floor + 10  # 10 dB above noise floor

    peaks = [
        {"freq_mhz": f, "power_db": round(p, 1)}
        for f, p in sorted(averaged.items())
        if p >= threshold
    ]
    # Merge adjacent bins into clusters
    clusters = _cluster_peaks(peaks, gap_mhz=step_khz / 1000 * 3)

    return {
        "start_mhz": start_mhz,
        "end_mhz": end_mhz,
        "step_khz": step_khz,
        "duration_seconds": duration_seconds,
        "noise_floor_db": round(noise_floor, 1),
        "peak_threshold_db": round(threshold, 1),
        "peaks": clusters,
        "total_bins": len(averaged),
    }


def _cluster_peaks(peaks: list[dict], gap_mhz: float) -> list[dict]:
    """Merge adjacent frequency peaks into single entries."""
    if not peaks:
        return []
    clusters = []
    group = [peaks[0]]
    for p in peaks[1:]:
        if p["freq_mhz"] - group[-1]["freq_mhz"] <= gap_mhz:
            group.append(p)
        else:
            clusters.append(_summarize_group(group))
            group = [p]
    clusters.append(_summarize_group(group))
    return clusters


def _summarize_group(group: list[dict]) -> dict:
    peak = max(group, key=lambda x: x["power_db"])
    return {
        "center_mhz": peak["freq_mhz"],
        "peak_power_db": peak["power_db"],
        "bandwidth_mhz": round(group[-1]["freq_mhz"] - group[0]["freq_mhz"], 3),
    }
