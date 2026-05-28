#!/usr/bin/env python3
"""
Wavedex MCP server — RTL-SDR radio birdwatching tools for Claude.

Tools exposed:
  get_aircraft          — ADS-B: list aircraft overhead (1090 MHz)
  predict_satellite_pass — next ISS/NOAA/etc pass + frequency hints
  scan_spectrum         — wideband power sweep, returns signal peaks
  lookup_frequency      — what's typically on a given frequency?
  list_signal_catalog   — browse the frequency database
"""

import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent))
from decoders import adsb, satellite, spectrum

mcp = FastMCP("Wavedex SDR")

_FREQ_DB = json.loads((Path(__file__).parent / "data" / "frequencies.json").read_text())


# ── Tool: ADS-B aircraft ───────────────────────────────────────────────────

@mcp.tool()
def get_aircraft(listen_seconds: int = 20) -> str:
    """
    Tune the RTL-SDR dongle to 1090 MHz and decode ADS-B transponder signals
    from aircraft currently overhead. Returns callsigns, positions, altitudes,
    and speeds. listen_seconds controls capture window (10–60, default 20).
    Note: occupies the radio for the full listen window.
    """
    listen_seconds = max(10, min(60, listen_seconds))
    result = adsb.scan(listen_seconds)

    if "error" in result:
        return f"Error: {result['error']}"

    aircraft = result["aircraft"]
    if not aircraft:
        return (
            f"No aircraft detected in {listen_seconds}s. "
            "Sky may be clear, or try listen_seconds=40 for a longer window."
        )

    lines = [
        f"Detected {result['total_detected']} aircraft "
        f"({result['with_position']} with GPS position) over {listen_seconds}s:\n"
    ]
    for a in aircraft:
        parts = [f"ICAO {a['icao']}"]
        if "callsign" in a:
            parts.append(f"callsign {a['callsign']}")
        if "lat" in a:
            parts.append(f"pos {a['lat']},{a['lon']}")
        if "altitude_ft" in a:
            parts.append(f"{a['altitude_ft']} ft")
        if "speed_kts" in a:
            parts.append(f"{a['speed_kts']} kts")
        if "heading_deg" in a:
            parts.append(f"hdg {a['heading_deg']}°")
        if "rssi_db" in a:
            parts.append(f"RSSI {a['rssi_db']} dB")
        lines.append("  • " + " | ".join(parts))

    return "\n".join(lines)


# ── Tool: Satellite pass prediction ────────────────────────────────────────

@mcp.tool()
def predict_satellite_pass(
    satellite_name: str,
    lat: float,
    lon: float,
    hours_ahead: int = 24,
) -> str:
    """
    Predict the next overhead pass of a satellite and get receive frequency hints.
    satellite_name: ISS, NOAA-15, NOAA-18, NOAA-19, METEOR-M2, FUNCUBE,
                    or any partial satellite name to fuzzy-search Celestrak.
    lat/lon: your location in decimal degrees (e.g. lat=47.6, lon=-122.3 for Seattle).
    hours_ahead: search window (default 24).
    Does NOT use the radio — pure orbital prediction.
    """
    try:
        result = satellite.next_pass(satellite_name, lat, lon, hours_ahead)
    except Exception as exc:
        return f"Error: {exc}"

    if "result" in result:
        return result["result"]

    p = result["next_pass"]
    lines = [
        f"Next pass of {result['satellite']}:",
        f"  Rise:  {p['rise']}  (azimuth {p.get('rise_azimuth_deg', '?')}°)",
        f"  Peak:  {p['peak']}  (max elevation {p.get('max_elevation_deg', '?')}°)",
        f"  Set:   {p['set']}",
    ]
    if p.get("duration_seconds"):
        m, s = divmod(p["duration_seconds"], 60)
        lines.append(f"  Duration: {m}m {s}s")
    lines.append(f"  Passes in next {hours_ahead}h: {result['passes_in_window']}")
    if result.get("tip"):
        lines.append(f"\nFrequency tip: {result['tip']}")

    return "\n".join(lines)


# ── Tool: Spectrum scan ─────────────────────────────────────────────────────

@mcp.tool()
def scan_spectrum(
    start_mhz: float,
    end_mhz: float,
    step_khz: float = 200,
    duration_seconds: int = 8,
) -> str:
    """
    Do a wideband power sweep across a frequency range and report signal peaks.
    Useful for discovering what's active in a band before tuning in.
    step_khz controls frequency resolution (default 200 kHz).
    duration_seconds controls how long to average (default 8, max 30).
    Note: occupies the radio for the full duration.

    Examples:
      scan_spectrum(88, 108)           — FM broadcast band
      scan_spectrum(136, 138, 25)      — weather satellites (25 kHz resolution)
      scan_spectrum(144, 148, 12.5)    — 2m amateur / APRS
      scan_spectrum(156, 163, 25)      — marine VHF / AIS
    """
    duration_seconds = max(4, min(30, duration_seconds))
    result = spectrum.scan(start_mhz, end_mhz, step_khz, duration_seconds)

    if "error" in result:
        return f"Error: {result['error']}"

    peaks = result["peaks"]
    if not peaks:
        return (
            f"Scan {start_mhz}–{end_mhz} MHz: no peaks found more than 10 dB above "
            f"noise floor ({result['noise_floor_db']} dB). Band appears quiet."
        )

    lines = [
        f"Spectrum scan {start_mhz}–{end_mhz} MHz "
        f"({step_khz} kHz steps, {duration_seconds}s):",
        f"  Noise floor: {result['noise_floor_db']} dB  |  "
        f"Threshold: {result['peak_threshold_db']} dB",
        f"  {len(peaks)} peak cluster(s) found:\n",
    ]
    for p in peaks:
        label = _freq_label(p["center_mhz"])
        bw = f" BW~{p['bandwidth_mhz']} MHz" if p["bandwidth_mhz"] > 0.05 else ""
        known = f"  ← {label}" if label else ""
        lines.append(
            f"  {p['center_mhz']:.3f} MHz  {p['peak_power_db']:+.1f} dB{bw}{known}"
        )

    return "\n".join(lines)


# ── Tool: Frequency lookup ─────────────────────────────────────────────────

@mcp.tool()
def lookup_frequency(freq_mhz: float) -> str:
    """
    Look up what signal(s) are typically found on or near a given frequency.
    Returns known allocations, signal types, and interesting notes.
    Does NOT use the radio.
    """
    matches = []
    for entry in _FREQ_DB:
        lo = entry["min_mhz"]
        hi = entry["max_mhz"]
        # Point frequencies stored as min==max
        if lo == hi:
            if abs(freq_mhz - lo) < 0.05:
                matches.append((0, entry))
        elif lo <= freq_mhz <= hi:
            matches.append((hi - lo, entry))

    if not matches:
        # Find nearest
        def dist(e):
            mid = (e["min_mhz"] + e["max_mhz"]) / 2
            return abs(mid - freq_mhz)
        nearest = min(_FREQ_DB, key=dist)
        return (
            f"{freq_mhz} MHz is not in the known frequency database.\n"
            f"Nearest known entry: {nearest['name']} "
            f"({nearest['min_mhz']}–{nearest['max_mhz']} MHz)"
        )

    lines = [f"Frequency lookup: {freq_mhz} MHz\n"]
    for _, e in sorted(matches, key=lambda x: x[0]):
        star = "★" if e["interesting"] else " "
        types = ", ".join(e["signal_types"])
        lines.append(f"{star} {e['name']}")
        lines.append(f"    {e['description']}")
        lines.append(f"    Signal types: {types}")
        lines.append(f"    Range: {e['min_mhz']}–{e['max_mhz']} MHz\n")

    return "\n".join(lines)


# ── Tool: Signal catalog ───────────────────────────────────────────────────

@mcp.tool()
def list_signal_catalog(interesting_only: bool = True) -> str:
    """
    Browse the Wavedex frequency catalog.
    Lists all known signal allocations with frequencies and descriptions.
    Set interesting_only=False to include mundane allocations like FM broadcast.
    Does NOT use the radio.
    """
    entries = _FREQ_DB if not interesting_only else [e for e in _FREQ_DB if e["interesting"]]

    lines = [
        f"Wavedex signal catalog ({'interesting signals' if interesting_only else 'all signals'}):\n"
    ]
    for e in entries:
        rng = f"{e['min_mhz']} MHz" if e["min_mhz"] == e["max_mhz"] else f"{e['min_mhz']}–{e['max_mhz']} MHz"
        types = ", ".join(e["signal_types"])
        lines.append(f"  {rng:>20}  {e['name']}")
        lines.append(f"    {e['description']}  [{types}]")

    lines.append(f"\nTotal: {len(entries)} entries.")
    return "\n".join(lines)


# ── Helpers ────────────────────────────────────────────────────────────────

def _freq_label(freq_mhz: float) -> str:
    for e in _FREQ_DB:
        lo, hi = e["min_mhz"], e["max_mhz"]
        if lo == hi and abs(freq_mhz - lo) < 0.1:
            return e["name"]
        if lo <= freq_mhz <= hi:
            return e["name"]
    return ""


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
