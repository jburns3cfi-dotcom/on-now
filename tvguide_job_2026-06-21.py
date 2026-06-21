#!/usr/bin/env python3
# =============================================================================
#  tvguide_job_2026-06-21.py
#  GitHub Actions runner. Three modes:
#    build         -> pull Schedules Direct, write public/schedule.json + meta
#    notify-digest -> send the morning digest push
#    notify-soon   -> send "starting soon" pings
#  Schedules Direct + Web Push are isolated here; all logic lives in core.
#  Internal timestamp banner: 2026-06-21
# =============================================================================
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(HERE, "public")
SD_BASE = "https://json.schedulesdirect.org/20141201"
CHUNK = 500


def _load_core():
    path = os.path.join(HERE, "tvguide_core_2026-06-21.py")
    spec = importlib.util.spec_from_file_location("tvguide_core", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load_core()


# ----------------------------------------------------------------------------
# Small filesystem helpers
# ----------------------------------------------------------------------------
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
    tmp = os.path.join(PUBLIC, name + ".tmp")
    final = os.path.join(PUBLIC, name)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, final)


# ----------------------------------------------------------------------------
# Schedules Direct client (only reached in build mode)
# ----------------------------------------------------------------------------
class SDError(RuntimeError):
    pass


def sd_token(session, username, password):
    pw = hashlib.sha1(core.safe_str(password).encode("utf-8")).hexdigest()
    r = session.post(SD_BASE + "/token",
                     json={"username": core.safe_str(username), "password": pw},
                     timeout=30)
    data = r.json()
    if not isinstance(data, dict) or data.get("code") != 0 or not data.get("token"):
        raise SDError("token request failed: %s" % core.safe_str(data))
    return core.safe_str(data.get("token"))


def sd_get(session, token, path):
    r = session.get(SD_BASE + path, headers={"token": token}, timeout=60)
    return r.json()


def sd_post(session, token, path, payload):
    r = session.post(SD_BASE + path, headers={"token": token}, json=payload, timeout=120)
    return r.json()


def sd_fetch_schedule(session, token, channels, days):
    station_ids = []
    for c in channels:
        sid = core.safe_str(c.get("station_id"))
        if sid:
            station_ids.append(sid)
    station_ids = sorted(set(station_ids))
    today = datetime.now(timezone.utc).date()
    dates = [(today + timedelta(days=i)).isoformat()
             for i in range(max(1, min(core.MAX_GUIDE_DAYS, days)))]

    raw_schedules = []
    program_ids = set()
    for i in range(0, len(station_ids), CHUNK):
        req = [{"stationID": sid, "date": dates} for sid in station_ids[i:i + CHUNK]]
        resp = sd_post(session, token, "/schedules", req)
        if isinstance(resp, list):
            for block in resp:
                if isinstance(block, dict):
                    raw_schedules.append(block)
                    progs = block.get("programs")
                    for a in (progs if isinstance(progs, list) else []):
                        if isinstance(a, dict):
                            pid = core.safe_str(a.get("programID"))
                            if pid:
                                program_ids.add(pid)

    program_index = {}
    pid_list = sorted(program_ids)
    for i in range(0, len(pid_list), CHUNK):
        resp = sd_post(session, token, "/programs", pid_list[i:i + CHUNK])
        if isinstance(resp, list):
            for p in resp:
                if isinstance(p, dict):
                    pid = core.safe_str(p.get("programID"))
                    if pid:
                        program_index[pid] = p
        time.sleep(0.2)
    return raw_schedules, program_index


def run_build():
    import requests
    config = read_json("config.json", {})
    channels = config.get("channels", []) if isinstance(config, dict) else []
    if not channels:
        write_json("schedule.json", [])
        write_json("meta.json", {"updated": datetime.now(timezone.utc).isoformat(),
                                 "channels": 0, "airings": 0, "note": "no channels configured"})
        print("no channels configured; wrote empty schedule")
        return 0
    days = core.safe_int((config or {}).get("days"), core.MAX_GUIDE_DAYS)
    session = requests.Session()
    session.headers.update({"User-Agent": "OnNow/2026-06-21 (github tvguide)",
                            "Content-Type": "application/json"})
    token = sd_token(session, os.environ.get("SD_USERNAME"), os.environ.get("SD_PASSWORD"))
    raw, prog = sd_fetch_schedule(session, token, channels, days)
    schedule = core.build_schedule(raw, prog, channels)
    write_json("schedule.json", core.serialize_schedule(schedule))
    write_json("meta.json", {"updated": datetime.now(timezone.utc).isoformat(),
                             "channels": len(channels), "airings": len(schedule)})
    print("built schedule: %d channels, %d airings" % (len(channels), len(schedule)))
    return 0


# ----------------------------------------------------------------------------
# Push delivery
# ----------------------------------------------------------------------------
def _deserialize(rows):
    out = []
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        rec = dict(r)
        rec["start"] = core.parse_utc(r.get("start"))
        rec["end"] = core.parse_utc(r.get("end"))
        out.append(rec)
    return out


def send_push(payload):
    from pywebpush import webpush, WebPushException
    subs = read_json("subscribers.json", [])
    if not isinstance(subs, list) or not subs:
        print("no subscribers")
        return 0
    priv = os.environ.get("VAPID_PRIVATE_KEY")
    subject = os.environ.get("VAPID_SUBJECT", "mailto:tv@example.com")
    if not priv:
        print("VAPID_PRIVATE_KEY missing; cannot send")
        return 1
    alive, sent = [], 0
    body = json.dumps(payload)
    for sub in subs:
        info = sub.get("subscription") if isinstance(sub, dict) else None
        if not isinstance(info, dict):
            continue
        try:
            webpush(subscription_info=info, data=body,
                    vapid_private_key=priv, vapid_claims={"sub": subject})
            alive.append(sub)
            sent += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                continue  # drop dead endpoint
            alive.append(sub)
        except Exception:
            alive.append(sub)
    if len(alive) != len(subs):
        write_json("subscribers.json", alive)
    print("push sent to %d endpoints" % sent)
    return 0


def run_notify(mode):
    schedule = _deserialize(read_json("schedule.json", []))
    watchlist = read_json("watchlist.json", [])
    if isinstance(watchlist, dict):
        watchlist = watchlist.get("titles", [])
    tz = core.safe_int(os.environ.get("TZ_OFFSET_MIN"), 0)
    now = datetime.now(timezone.utc)
    if mode == "notify-digest":
        day_end = now + timedelta(hours=24)
        wl_hits = [r for r in core.annotate_watchlist(schedule, watchlist, now)
                   if r.get("next") and r["next"]["start"] <= day_end]
        wl_recs = [r["next"] for r in wl_hits]
        new_today = [r for r in core.upcoming_new_episodes(schedule, now)
                     if r["start"] <= day_end]
        return send_push(core.build_digest(wl_recs, new_today, tz))
    soon = core.starting_soon(schedule, watchlist, now)
    if not soon:
        print("nothing starting soon")
        return 0
    rc = 0
    for rec in soon:
        rc |= send_push(core.build_soon_alert(rec, tz))
    return rc


def main(argv):
    mode = argv[1] if len(argv) > 1 else "build"
    if mode == "build":
        return run_build()
    if mode in ("notify-digest", "notify-soon"):
        return run_notify(mode)
    print("unknown mode: %s" % mode)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
