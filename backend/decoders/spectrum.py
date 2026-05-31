"""Spectrum scanner — rtl_power sweep (direct USB) or pyrtlsdr TCP sweep."""

import csv
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from decoders.config import RTL_TCP_HOST, RTL_TCP_PORT, using_tcp

RTL_POWER = "rtl_power"
RTL_BIAST = "rtl_biast"

# Samples per FFT chunk — balances resolution vs speed on Android CPU
_FFT_SIZE = 1024
_CHUNKS_PER_STEP = 32   # average this many chunks per frequency step


def scan(start_mhz: float, end_mhz: float, step_khz: float = 200, duration_seconds: int = 8) -> dict:
    if end_mhz <= start_mhz:
        return {"error": "end_mhz must be greater than start_mhz"}
    if end_mhz - start_mhz > 1000:
        return {"error": "Scan range capped at 1000 MHz per call"}

    if using_tcp():
        return _scan_tcp(start_mhz, end_mhz, step_khz, duration_seconds)
    else:
        return _scan_direct(start_mhz, end_mhz, step_khz, duration_seconds)


# ── Direct USB path (Mac) ──────────────────────────────────────────────────

def _enable_biast() -> None:
    try:
        subprocess.run([RTL_BIAST, "-d", "0", "-b", "1"], capture_output=True, timeout=5)
    except Exception:
        pass


def _scan_direct(start_mhz, end_mhz, step_khz, duration_seconds) -> dict:
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

    return _build_result(bins, start_mhz, end_mhz, step_khz, duration_seconds)


# ── TCP path (Tab / Termux) ────────────────────────────────────────────────

def _scan_tcp(start_mhz, end_mhz, step_khz, duration_seconds) -> dict:
    try:
        from rtlsdr import RtlSdrTcpClient
    except ImportError:
        return {"error": "pyrtlsdr not installed — run: pip install pyrtlsdr"}

    sample_rate = 2.048e6   # safe ceiling for Android
    step_hz = step_khz * 1e3
    freqs_hz = list(_freq_steps(start_mhz * 1e6, end_mhz * 1e6, sample_rate * 0.8))

    bins: dict[float, list[float]] = {}

    try:
        sdr = RtlSdrTcpClient(host=RTL_TCP_HOST, port=RTL_TCP_PORT)
        sdr.sample_rate = sample_rate
        sdr.gain = 33.8

        for center_hz in freqs_hz:
            sdr.center_freq = center_hz
            chunk_powers = []
            for _ in range(_CHUNKS_PER_STEP):
                samples = sdr.read_samples(_FFT_SIZE)
                fft = np.fft.fftshift(np.fft.fft(samples, _FFT_SIZE))
                power = 10 * np.log10(np.abs(fft) ** 2 + 1e-12)
                chunk_powers.append(power)

            avg_power = np.mean(chunk_powers, axis=0)
            freqs = np.fft.fftshift(np.fft.fftfreq(_FFT_SIZE, 1 / sample_rate)) + center_hz

            for freq_hz, pwr in zip(freqs, avg_power):
                if start_mhz * 1e6 <= freq_hz <= end_mhz * 1e6:
                    freq_mhz = round(freq_hz / 1e6, 4)
                    bins.setdefault(freq_mhz, []).append(float(pwr))

        sdr.close()

    except ConnectionRefusedError:
        return {"error": f"Cannot connect to rtl_tcp at {RTL_TCP_HOST}:{RTL_TCP_PORT} — is SDR Driver running?"}
    except Exception as exc:
        return {"error": f"TCP scan error: {exc}"}

    if not bins:
        return {"error": "No samples collected from TCP stream"}

    return _build_result(bins, start_mhz, end_mhz, step_khz, duration_seconds)


def _freq_steps(start_hz: float, end_hz: float, bandwidth_hz: float):
    """Yield center frequencies that cover start_hz to end_hz without gaps."""
    step = bandwidth_hz * 0.75   # 25% overlap between steps
    freq = start_hz + bandwidth_hz / 2
    while freq < end_hz + bandwidth_hz / 2:
        yield freq
        freq += step


# ── Shared result builder ──────────────────────────────────────────────────

def _build_result(bins: dict, start_mhz, end_mhz, step_khz, duration_seconds) -> dict:
    averaged = {f: sum(v) / len(v) for f, v in bins.items()}
    sorted_vals = sorted(averaged.values())
    noise_floor = sorted_vals[max(0, len(sorted_vals) // 10)]
    threshold = noise_floor + 10

    peaks = [
        {"freq_mhz": f, "power_db": round(p, 1)}
        for f, p in sorted(averaged.items())
        if p >= threshold
    ]
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
