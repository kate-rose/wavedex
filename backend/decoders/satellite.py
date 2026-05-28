"""Satellite pass predictor using Skyfield + SatNOGS TLE API."""

import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from skyfield.api import EarthSatellite, load, wgs84

_cache_dir = Path.home() / ".cache" / "wavedex" / "tle"
_cache_dir.mkdir(parents=True, exist_ok=True)

# Friendly name → (NORAD cat ID, receive frequency tip)
SATELLITE_CATALOG: dict[str, tuple[int, str]] = {
    "ISS":       (25544, "Voice: 145.800 MHz FM. APRS: 437.550 MHz. Tune ±3 kHz for Doppler drift."),
    "NOAA-15":   (25338, "APT image: 137.620 MHz WFM (~40 kHz BW). Use WXtoImg or noaa-apt to decode."),
    "NOAA-18":   (28654, "APT image: 137.9125 MHz WFM (~40 kHz BW)."),
    "NOAA-19":   (33591, "APT image: 137.100 MHz WFM (~40 kHz BW)."),
    "METEOR-M2": (40069, "LRPT image: 137.900 MHz. Needs LRPT-decoder. Higher resolution than NOAA APT."),
    "FUNCUBE-1": (39444, "CW/telemetry: 145.935 MHz. Linear transponder uplink 435.150 MHz."),
}

_SATNOGS_URL = "https://db.satnogs.org/api/tle/?norad_cat_id={norad}&format=json"
_ts = None


def _timescale():
    global _ts
    if _ts is None:
        _ts = load.timescale()
    return _ts


def _fetch_tle(norad_id: int) -> tuple[str, str, str]:
    """Return (name, line1, line2) for a NORAD catalog ID, with 24h caching."""
    cache_file = _cache_dir / f"{norad_id}.json"
    now = time.time()

    if cache_file.exists() and now - cache_file.stat().st_mtime < 86400:
        entry = json.loads(cache_file.read_text())
        return entry["name"], entry["line1"], entry["line2"]

    url = _SATNOGS_URL.format(norad=norad_id)
    req = urllib.request.Request(url, headers={"User-Agent": "WavedexSDR/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        if cache_file.exists():
            entry = json.loads(cache_file.read_text())
            return entry["name"], entry["line1"], entry["line2"]
        raise RuntimeError(f"Could not fetch TLE for NORAD {norad_id}: {exc}") from exc

    if not data:
        raise ValueError(f"No TLE data returned for NORAD {norad_id}")

    entry = data[0]
    # SatNOGS returns tle0 with "0 NAME" prefix
    name = entry["tle0"].lstrip("0 ").strip()
    line1, line2 = entry["tle1"], entry["tle2"]
    cache_file.write_text(json.dumps({"name": name, "line1": line1, "line2": line2}))
    return name, line1, line2


def _resolve_satellite(name: str) -> tuple[EarthSatellite, str, str]:
    """Return (EarthSatellite, actual_name, frequency_tip) for a friendly name or NORAD ID."""
    name_upper = name.strip().upper()
    ts = _timescale()

    # Direct NORAD ID
    if name_upper.isdigit():
        norad = int(name_upper)
        sat_name, l1, l2 = _fetch_tle(norad)
        return EarthSatellite(l1, l2, sat_name, ts), sat_name, ""

    # Catalog lookup
    for key, (norad, tip) in SATELLITE_CATALOG.items():
        if key in name_upper or name_upper in key:
            sat_name, l1, l2 = _fetch_tle(norad)
            return EarthSatellite(l1, l2, sat_name, ts), sat_name, tip

    known = ", ".join(SATELLITE_CATALOG.keys())
    raise ValueError(f"Unknown satellite '{name}'. Known: {known}. Or pass a NORAD catalog number.")


def next_pass(satellite_name: str, lat: float, lon: float, hours_ahead: int = 24) -> dict:
    """
    Find the next pass of a satellite over the observer's location.
    Returns rise/peak/set times, max elevation, and receive frequency hints.
    """
    ts = _timescale()
    sat, actual_name, tip = _resolve_satellite(satellite_name)
    observer = wgs84.latlon(lat, lon)

    t0 = ts.now()
    t1 = ts.tt_jd(t0.tt + hours_ahead / 24.0)

    times, events = sat.find_events(observer, t0, t1, altitude_degrees=10.0)

    if len(times) == 0:
        return {
            "satellite": actual_name,
            "observer": {"lat": lat, "lon": lon},
            "result": f"No pass above 10° elevation in the next {hours_ahead} hours.",
        }

    # Group rise/peak/set triplets into passes
    passes = []
    current: dict = {}
    for t, ev in zip(times, events):
        dt = t.utc_datetime().replace(tzinfo=timezone.utc)
        if ev == 0:  # rise
            diff = sat - observer
            alt, az, _ = diff.at(t).altaz()
            current = {"rise": dt, "rise_azimuth_deg": round(az.degrees, 1)}
        elif ev == 1:  # peak
            diff = sat - observer
            alt, az, _ = diff.at(t).altaz()
            current["peak_time"] = dt
            current["peak_elevation_deg"] = round(alt.degrees, 1)
        elif ev == 2 and current:  # set
            current["set"] = dt
            if "rise" in current:
                current["duration_seconds"] = int((dt - current["rise"]).total_seconds())
            passes.append(current)
            current = {}

    if not passes:
        return {
            "satellite": actual_name,
            "observer": {"lat": lat, "lon": lon},
            "result": "Partial pass data — try extending hours_ahead.",
        }

    p = passes[0]

    def fmt(dt):
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC") if dt else "unknown"

    return {
        "satellite": actual_name,
        "observer": {"lat": lat, "lon": lon},
        "next_pass": {
            "rise": fmt(p.get("rise")),
            "peak": fmt(p.get("peak_time")),
            "set": fmt(p.get("set")),
            "max_elevation_deg": p.get("peak_elevation_deg"),
            "rise_azimuth_deg": p.get("rise_azimuth_deg"),
            "duration_seconds": p.get("duration_seconds"),
        },
        "passes_in_window": len(passes),
        "tip": tip,
    }
