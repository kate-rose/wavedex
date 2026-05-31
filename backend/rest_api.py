#!/usr/bin/env python3
"""
Wavedex REST API + Chat UI — exposes MCP tools over HTTP for the Galaxy Tab,
and serves a Claude-powered assistant chat interface.

Endpoints:
  GET  /                  — chat UI (open in Tab browser)
  GET  /status
  GET  /catalog?interesting_only=true
  GET  /frequency?freq_mhz=162.4
  POST /aircraft          {"listen_seconds": 20}
  POST /satellite         {"satellite_name": "ISS", "lat": 45.7, "lon": -121.5, "hours_ahead": 24}
  POST /scan              {"start_mhz": 144, "end_mhz": 148, "step_khz": 200, "duration_seconds": 8}
  POST /chat              {"message": "...", "history": [...]}

Run: python rest_api.py
     Listens on 0.0.0.0:5001 — reachable from Tab at http://100.121.225.40:5001
"""

import json
import os
import sys
from pathlib import Path

from flask import Flask, request, jsonify, Response
import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from decoders import adsb, satellite, spectrum

app = Flask(__name__)

_FREQ_DB = json.loads((Path(__file__).parent / "data" / "frequencies.json").read_text())
_CLIENT = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

_CATALOG_TEXT = "\n".join(
    f"  {e['min_mhz']}–{e['max_mhz']} MHz  {e['name']}: {e['description']}"
    for e in _FREQ_DB
)

_SYSTEM_PROMPT = f"""You are WaveDex, a conversational SDR (software-defined radio) assistant running on a Galaxy Tab Active 3 in the field. You help the user tune, scan, identify, and decode radio signals using an RTL-SDR Blog V4 dongle.

Your personality: knowledgeable radio enthusiast, concise and practical. You love esoteric signals — ISS SSTV, train ATCS data, ADS-B aircraft, APRS, marine VHF, drone RF. You're familiar with the Columbia River Gorge area (PNW, lat ~45.7, lon ~-121.5).

You have access to these tools via the WaveDex backend (already called for you when relevant):
- /aircraft — scan 1090 MHz for ADS-B aircraft overhead
- /satellite — predict next pass of ISS, NOAA sats, etc.
- /scan — wideband power sweep to find active signals
- /frequency — look up what's on a given frequency

When the user asks you to scan, check aircraft, or predict a satellite pass, tell them to tap the quick-action button or you can trigger it. Keep responses short and radio-focused. If you don't know something, say so — don't invent frequencies or signal details.

Known frequency catalog:
{_CATALOG_TEXT}"""


def _freq_label(freq_mhz: float) -> str:
    for e in _FREQ_DB:
        lo, hi = e["min_mhz"], e["max_mhz"]
        if lo == hi and abs(freq_mhz - lo) < 0.1:
            return e["name"]
        if lo <= freq_mhz <= hi:
            return e["name"]
    return ""


# ── Tool endpoints ─────────────────────────────────────────────────────────

@app.get("/status")
def status():
    return jsonify({"status": "ok", "tools": ["aircraft", "satellite", "scan", "frequency", "catalog"]})


@app.get("/catalog")
def catalog():
    interesting_only = request.args.get("interesting_only", "true").lower() != "false"
    entries = _FREQ_DB if not interesting_only else [e for e in _FREQ_DB if e["interesting"]]
    return jsonify({"entries": entries, "count": len(entries)})


@app.get("/frequency")
def frequency():
    freq_mhz = request.args.get("freq_mhz", type=float)
    if freq_mhz is None:
        return jsonify({"error": "freq_mhz parameter required"}), 400

    matches = []
    for entry in _FREQ_DB:
        lo, hi = entry["min_mhz"], entry["max_mhz"]
        if lo == hi:
            if abs(freq_mhz - lo) < 0.05:
                matches.append(entry)
        elif lo <= freq_mhz <= hi:
            matches.append(entry)

    if not matches:
        def dist(e):
            mid = (e["min_mhz"] + e["max_mhz"]) / 2
            return abs(mid - freq_mhz)
        nearest = min(_FREQ_DB, key=dist)
        return jsonify({"freq_mhz": freq_mhz, "matches": [], "nearest": nearest})

    return jsonify({"freq_mhz": freq_mhz, "matches": matches})


@app.post("/aircraft")
def aircraft():
    body = request.get_json(silent=True) or {}
    listen_seconds = max(10, min(60, int(body.get("listen_seconds", 20))))
    result = adsb.scan(listen_seconds)
    return jsonify(result)


@app.post("/satellite")
def satellite_pass():
    body = request.get_json(silent=True) or {}
    sat_name = body.get("satellite_name", "ISS")
    lat = float(body.get("lat", 45.7))
    lon = float(body.get("lon", -121.5))
    hours_ahead = int(body.get("hours_ahead", 24))
    try:
        result = satellite.next_pass(sat_name, lat, lon, hours_ahead)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(result)


@app.post("/scan")
def scan():
    body = request.get_json(silent=True) or {}
    start_mhz = float(body.get("start_mhz", 144))
    end_mhz = float(body.get("end_mhz", 148))
    step_khz = float(body.get("step_khz", 200))
    duration_seconds = max(4, min(30, int(body.get("duration_seconds", 8))))
    result = spectrum.scan(start_mhz, end_mhz, step_khz, duration_seconds)
    return jsonify(result)


# ── Chat endpoint ──────────────────────────────────────────────────────────

@app.post("/chat")
def chat():
    body = request.get_json(silent=True) or {}
    message = body.get("message", "").strip()
    history = body.get("history", [])

    if not message:
        return jsonify({"error": "message required"}), 400

    messages = history + [{"role": "user", "content": message}]

    try:
        response = _CLIENT.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
        reply = response.content[0].text
        return jsonify({"reply": reply})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Chat UI ────────────────────────────────────────────────────────────────

@app.get("/")
def ui():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>WaveDex</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0a0e14; color: #c5d0e0; font-family: 'Courier New', monospace; height: 100dvh; display: flex; flex-direction: column; }

  header { background: #0d1520; border-bottom: 1px solid #1e3a5f; padding: 10px 14px; display: flex; align-items: center; gap: 10px; }
  header h1 { font-size: 1.1rem; color: #4fc3f7; letter-spacing: 2px; text-transform: uppercase; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #4caf50; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

  .quick-actions { background: #0d1520; border-bottom: 1px solid #1e3a5f; padding: 8px 10px; display: flex; gap: 6px; overflow-x: auto; flex-shrink: 0; }
  .quick-actions::-webkit-scrollbar { display: none; }
  .qa-btn { background: #0a2540; border: 1px solid #1e3a5f; color: #4fc3f7; padding: 6px 12px; border-radius: 16px; font-size: 0.75rem; cursor: pointer; white-space: nowrap; font-family: inherit; transition: background 0.15s; }
  .qa-btn:active { background: #1e3a5f; }

  #messages { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }

  .msg { max-width: 88%; padding: 10px 13px; border-radius: 12px; font-size: 0.85rem; line-height: 1.5; word-break: break-word; white-space: pre-wrap; }
  .msg.user { align-self: flex-end; background: #1a3a5c; border-bottom-right-radius: 3px; color: #e0eeff; }
  .msg.assistant { align-self: flex-start; background: #0d2035; border: 1px solid #1e3a5f; border-bottom-left-radius: 3px; color: #c5d0e0; }
  .msg.system { align-self: center; background: transparent; color: #4a6080; font-size: 0.75rem; border: none; padding: 2px 0; }
  .msg.error { background: #2a0d0d; border: 1px solid #5f1e1e; color: #ff6b6b; }

  .typing { display: flex; gap: 4px; padding: 10px 13px; }
  .typing span { width: 6px; height: 6px; background: #4fc3f7; border-radius: 50%; animation: bounce 1s infinite; }
  .typing span:nth-child(2) { animation-delay: 0.15s; }
  .typing span:nth-child(3) { animation-delay: 0.3s; }
  @keyframes bounce { 0%,80%,100%{transform:translateY(0)} 40%{transform:translateY(-6px)} }

  .input-row { background: #0d1520; border-top: 1px solid #1e3a5f; padding: 10px; display: flex; gap: 8px; align-items: flex-end; }
  #input { flex: 1; background: #0a2540; border: 1px solid #1e3a5f; border-radius: 20px; padding: 10px 14px; color: #e0eeff; font-family: inherit; font-size: 0.9rem; resize: none; max-height: 120px; outline: none; line-height: 1.4; }
  #input:focus { border-color: #4fc3f7; }
  #send { background: #1565c0; border: none; color: white; width: 40px; height: 40px; border-radius: 50%; cursor: pointer; font-size: 1.1rem; flex-shrink: 0; transition: background 0.15s; }
  #send:active { background: #0d47a1; }
  #send:disabled { background: #1e3a5f; cursor: default; }

  .result-card { background: #051525; border: 1px solid #1e3a5f; border-radius: 8px; padding: 10px; font-size: 0.78rem; color: #90a8c0; margin-top: 4px; }
  .result-card .label { color: #4fc3f7; font-size: 0.7rem; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 1px; }
</style>
</head>
<body>

<header>
  <div class="dot"></div>
  <h1>WaveDex</h1>
</header>

<div class="quick-actions">
  <button class="qa-btn" onclick="quickAction('aircraft')">✈ Aircraft</button>
  <button class="qa-btn" onclick="quickAction('iss')">🛰 ISS Pass</button>
  <button class="qa-btn" onclick="quickAction('aprs')">📡 APRS Scan</button>
  <button class="qa-btn" onclick="quickAction('marine')">⚓ Marine VHF</button>
  <button class="qa-btn" onclick="quickAction('noaa')">🌤 NOAA Sats</button>
  <button class="qa-btn" onclick="quickAction('catalog')">📖 Catalog</button>
  <button class="qa-btn" onclick="quickAction('drone')">🚁 Drone RF</button>
</div>

<div id="messages">
  <div class="msg system">WaveDex connected · MacBook Pro via Tailscale</div>
</div>

<div class="input-row">
  <textarea id="input" rows="1" placeholder="Ask about a signal, frequency, or what to listen for..." oninput="autoResize(this)" onkeydown="handleKey(event)"></textarea>
  <button id="send" onclick="sendMessage()">↑</button>
</div>

<script>
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('send');
let history = [];

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

function addMsg(role, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function addTyping() {
  const div = document.createElement('div');
  div.className = 'msg assistant typing';
  div.innerHTML = '<span></span><span></span><span></span>';
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function addCard(label, content) {
  const div = document.createElement('div');
  div.className = 'result-card';
  div.innerHTML = '<div class="label">' + label + '</div>' + '<pre style="white-space:pre-wrap">' + content + '</pre>';
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function sendMessage(text) {
  const message = text || inputEl.value.trim();
  if (!message) return;

  inputEl.value = '';
  inputEl.style.height = 'auto';
  sendBtn.disabled = true;

  addMsg('user', message);
  const typing = addTyping();

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message, history })
    });
    const data = await res.json();
    typing.remove();

    if (data.error) {
      addMsg('error', 'Error: ' + data.error);
    } else {
      addMsg('assistant', data.reply);
      history.push({ role: 'user', content: message });
      history.push({ role: 'assistant', content: data.reply });
      if (history.length > 20) history = history.slice(-20);
    }
  } catch (e) {
    typing.remove();
    addMsg('error', 'Connection error — is the Mac online?');
  }

  sendBtn.disabled = false;
  inputEl.focus();
}

async function quickAction(action) {
  const actions = {
    aircraft: async () => {
      addMsg('system', 'Scanning 1090 MHz for ADS-B... (20s)');
      const r = await fetch('/aircraft', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({listen_seconds: 20}) });
      const d = await r.json();
      const aircraft = d.aircraft || [];
      if (aircraft.length === 0) {
        addCard('ADS-B Scan', 'No aircraft detected.');
      } else {
        const lines = aircraft.map(a => {
          let s = a.callsign || a.icao;
          if (a.altitude_ft) s += ' @ ' + a.altitude_ft + 'ft';
          if (a.speed_kts) s += ' ' + a.speed_kts + 'kts';
          return s;
        }).join('\\n');
        addCard('ADS-B · ' + aircraft.length + ' aircraft', lines);
      }
    },
    iss: async () => {
      addMsg('system', 'Predicting ISS pass...');
      const r = await fetch('/satellite', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({satellite_name:'ISS', lat:45.7, lon:-121.5}) });
      const d = await r.json();
      if (d.result) { addCard('ISS Pass', d.result); }
      else if (d.next_pass) {
        const p = d.next_pass;
        addCard('ISS · Next Pass', 'Rise: ' + p.rise + '\\nPeak: ' + p.peak + ' (' + (p.max_elevation_deg||'?') + '° max)\\nSet:  ' + p.set + (d.tip ? '\\n\\n' + d.tip : ''));
      } else { addCard('ISS Pass', JSON.stringify(d, null, 2)); }
    },
    aprs: async () => {
      addMsg('system', 'Scanning 144–148 MHz for APRS...');
      const r = await fetch('/scan', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({start_mhz:144, end_mhz:148, step_khz:12.5, duration_seconds:8}) });
      const d = await r.json();
      const peaks = d.peaks || [];
      addCard('APRS Band Scan', peaks.length ? peaks.map(p => p.center_mhz.toFixed(3) + ' MHz  ' + p.peak_power_db.toFixed(1) + ' dB').join('\\n') : 'No peaks detected above noise floor.');
    },
    marine: async () => {
      addMsg('system', 'Scanning 156–163 MHz marine VHF...');
      const r = await fetch('/scan', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({start_mhz:156, end_mhz:163, step_khz:25, duration_seconds:8}) });
      const d = await r.json();
      const peaks = d.peaks || [];
      addCard('Marine VHF Scan', peaks.length ? peaks.map(p => p.center_mhz.toFixed(3) + ' MHz  ' + p.peak_power_db.toFixed(1) + ' dB').join('\\n') : 'No peaks detected.');
    },
    noaa: async () => {
      addMsg('system', 'Predicting NOAA-19 pass...');
      const r = await fetch('/satellite', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({satellite_name:'NOAA-19', lat:45.7, lon:-121.5}) });
      const d = await r.json();
      if (d.next_pass) {
        const p = d.next_pass;
        addCard('NOAA-19 · Next Pass', 'Rise: ' + p.rise + '\\nPeak: ' + p.peak + ' (' + (p.max_elevation_deg||'?') + '° max)\\n' + (d.tip||''));
      } else { addCard('NOAA-19', d.result || JSON.stringify(d)); }
    },
    catalog: async () => {
      const r = await fetch('/catalog?interesting_only=true');
      const d = await r.json();
      const lines = (d.entries||[]).map(e => e.min_mhz + (e.min_mhz!==e.max_mhz?'–'+e.max_mhz:'') + ' MHz  ' + e.name).join('\\n');
      addCard('Signal Catalog · ' + d.count + ' interesting signals', lines);
    },
    drone: () => {
      sendMessage("I'm in the Columbia River Gorge and want to look for drone RF signals. What frequencies should I scan and what am I looking for?");
    }
  };

  if (actions[action]) {
    try { await actions[action](); }
    catch(e) { addMsg('error', 'Action failed: ' + e.message); }
  }
}

// Greet on load
window.addEventListener('load', () => {
  sendMessage("Hi! I just opened WaveDex. Give me a quick one-sentence status and tell me one interesting thing I could be listening for right now near the Columbia River Gorge.");
});
</script>
</body>
</html>"""
    return Response(html, mimetype="text/html")


if __name__ == "__main__":
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY not set — chat endpoint will fail")
    print("Wavedex REST API + Chat UI starting on 0.0.0.0:5001")
    print("Open on Tab: http://100.121.225.40:5001")
    app.run(host="0.0.0.0", port=5001, debug=False)
