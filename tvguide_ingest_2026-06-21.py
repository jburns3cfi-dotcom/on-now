#!/usr/bin/env python3
# =============================================================================
#  tvguide_ingest_2026-06-21.py
#  Reads one GitHub issue body, applies a TVGUIDE_PAYLOAD update to the
#  appropriate public/*.json file. The workflow commits the result.
#  Payload: a line  TVGUIDE_PAYLOAD:<base64-of-json>
#  JSON: {"type":"subscribe|watchlist|config", "data": ...}
#  Internal timestamp banner: 2026-06-21
# =============================================================================
from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(HERE, "public")


def _load_core():
    path = os.path.join(HERE, "tvguide_core_2026-06-21.py")
    spec = importlib.util.spec_from_file_location("tvguide_core", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load_core()


def read_json(name, default):
    try:
        with open(os.path.join(PUBLIC, name), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError):
        return default


def write_json(name, data):
    os.makedirs(PUBLIC, exist_ok=True)
    with open(os.path.join(PUBLIC, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_payload(body) -> dict | None:
    """Pull and decode the TVGUIDE_PAYLOAD from an issue body. NEVER raises."""
    try:
        text = core.safe_str(body)
        m = re.search(r"TVGUIDE_PAYLOAD:([A-Za-z0-9+/=_\-]+)", text)
        if not m:
            return None
        blob = m.group(1).replace("-", "+").replace("_", "/")
        pad = (-len(blob)) % 4
        blob += "=" * pad
        raw = base64.b64decode(blob, validate=False)
        data = json.loads(raw.decode("utf-8", "replace"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def apply_subscribe(data) -> bool:
    sub = data.get("data") if isinstance(data, dict) else None
    if not isinstance(sub, dict):
        return False
    endpoint = core.safe_str(sub.get("endpoint"))
    if not endpoint:
        return False
    subs = read_json("subscribers.json", [])
    if not isinstance(subs, list):
        subs = []
    kept = [s for s in subs
            if isinstance(s, dict)
            and core.safe_str((s.get("subscription") or {}).get("endpoint")) != endpoint]
    kept.append({"subscription": sub})
    write_json("subscribers.json", kept)
    return True


def apply_watchlist(data) -> bool:
    titles = data.get("data") if isinstance(data, dict) else None
    if not isinstance(titles, list):
        return False
    clean = []
    seen = set()
    for t in titles:
        s = core.safe_str(t)
        key = core.normalize_title(s)
        if s and key and key not in seen:
            seen.add(key)
            clean.append(s)
    write_json("watchlist.json", {"titles": clean})
    return True


def apply_config(data) -> bool:
    cfg = data.get("data") if isinstance(data, dict) else None
    if not isinstance(cfg, dict):
        return False
    channels_in = cfg.get("channels")
    channels = []
    if isinstance(channels_in, list):
        for c in channels_in:
            if not isinstance(c, dict):
                continue
            sid = core.safe_str(c.get("station_id"))
            if not sid:
                continue
            channels.append({
                "station_id": sid,
                "number": core.safe_str(c.get("number")),
                "name": core.safe_str(c.get("name")),
                "callsign": core.safe_str(c.get("callsign")),
                "service": core.safe_str(c.get("service")),
            })
    out = {"channels": channels,
           "days": max(1, min(core.MAX_GUIDE_DAYS, core.safe_int(cfg.get("days"), core.MAX_GUIDE_DAYS)))}
    write_json("config.json", out)
    return True


def main(argv):
    body = os.environ.get("ISSUE_BODY", "")
    if not body and len(argv) > 1:
        try:
            with open(argv[1], "r", encoding="utf-8") as f:
                body = f.read()
        except OSError:
            body = ""
    data = extract_payload(body)
    if not data:
        print("no valid payload")
        return 0
    kind = core.safe_str(data.get("type"))
    handler = {"subscribe": apply_subscribe, "watchlist": apply_watchlist,
               "config": apply_config}.get(kind)
    if not handler:
        print("unknown payload type: %s" % kind)
        return 0
    ok = handler(data)
    print("applied %s: %s" % (kind, ok))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
