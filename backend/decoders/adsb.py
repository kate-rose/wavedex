"""ADS-B decoder — readsb with direct USB or rtl_tcp client mode."""

import json
import subprocess
import tempfile
from pathlib import Path

from decoders.config import RTL_TCP_HOST, RTL_TCP_PORT, using_tcp

READSB = "readsb"
_json_dir = Path(tempfile.gettempdir()) / "wavedex-adsb"


def scan(listen_seconds: int = 20) -> dict:
    """Run readsb, collect aircraft.json, return structured results."""
    _json_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        READSB,
        "--gain", "auto",
        "--no-interactive",
        "--quiet",
        "--write-json", str(_json_dir),
        "--write-json-every", "2",
        "--auto-exit", str(listen_seconds),
    ]

    if using_tcp():
        cmd += ["--device-type", "rtltcp",
                "--rtlsdr-device", f"tcp://{RTL_TCP_HOST}:{RTL_TCP_PORT}"]
    else:
        cmd += ["--device-type", "rtlsdr"]

    try:
        subprocess.run(cmd, capture_output=True, timeout=listen_seconds + 15)
    except subprocess.TimeoutExpired:
        pass
    except FileNotFoundError:
        return {"error": "readsb not found. Install with: brew install readsb (Mac) or pkg install readsb (Termux)"}

    aircraft_file = _json_dir / "aircraft.json"
    if not aircraft_file.exists():
        return {"error": "No data written. Dongle may be in use by another process."}

    try:
        raw = json.loads(aircraft_file.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": str(exc)}

    aircraft = raw.get("aircraft", [])
    cleaned = []
    for a in aircraft:
        entry = {"icao": a.get("hex", "").upper()}
        if a.get("flight"):
            entry["callsign"] = a["flight"].strip()
        if a.get("lat") is not None and a.get("lon") is not None:
            entry["lat"] = round(a["lat"], 5)
            entry["lon"] = round(a["lon"], 5)
        if a.get("altitude"):
            entry["altitude_ft"] = a["altitude"]
        if a.get("gs"):
            entry["speed_kts"] = a["gs"]
        if a.get("track") is not None:
            entry["heading_deg"] = a["track"]
        if a.get("category"):
            entry["category"] = a["category"]
        if a.get("rssi") is not None:
            entry["rssi_db"] = a["rssi"]
        cleaned.append(entry)

    return {
        "listen_seconds": listen_seconds,
        "total_detected": len(aircraft),
        "with_position": sum(1 for a in aircraft if a.get("lat") is not None),
        "aircraft": cleaned,
    }
