#!/usr/bin/env python3
# =============================================================================
#  sd_lineups_2026-06-21.py
#  One-time helper to set up Schedules Direct channels for the TV guide.
#  Modes:
#    headends <ZIP>        list lineups available for a postal code
#    add <LINEUP>          add a lineup to your SD account (e.g. USA-YOUTUBE-X)
#    remove <LINEUP>       remove a lineup
#    list [--filter a,b]   show stations in your lineups, write public/config.json
#  Credentials come from env SD_USERNAME / SD_PASSWORD (or you are prompted).
#  Internal timestamp banner: 2026-06-21
# =============================================================================
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys

SD_BASE = "https://json.schedulesdirect.org/20141201"
UA = "OnNow/2026-06-21 (github tvguide)"
HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(HERE, "public")


# ---- safe helpers (standalone; this script may run on its own) -------------
def s(x) -> str:
    try:
        if x is None:
            return ""
        if isinstance(x, (bytes, bytearray)):
            return bytes(x).decode("utf-8", "replace").strip()
        return str(x).strip()
    except Exception:
        return ""


def norm(x) -> str:
    return s(x).casefold()


# ---- pure parsers (unit-tested) --------------------------------------------
def parse_headends(data) -> list:
    """SD /headends response -> flat list of available lineups. NEVER raises."""
    out = []
    try:
        if not isinstance(data, list):
            return out
        for he in data:
            if not isinstance(he, dict):
                continue
            loc = s(he.get("location"))
            trans = s(he.get("transport"))
            for ln in he.get("lineups", []) or []:
                if isinstance(ln, dict):
                    out.append({"lineup": s(ln.get("lineup")),
                                "name": s(ln.get("name")),
                                "location": loc, "transport": trans})
        return out
    except Exception:
        return out


def parse_lineup(data, service="") -> list:
    """SD /lineups/{id} response -> channel rows. NEVER raises."""
    try:
        if not isinstance(data, dict):
            return []
        chan_by_station = {}
        for m in data.get("map", []) or []:
            if isinstance(m, dict):
                sid = s(m.get("stationID"))
                if sid and sid not in chan_by_station:
                    chan_by_station[sid] = s(m.get("channel"))
        rows = []
        for st in data.get("stations", []) or []:
            if not isinstance(st, dict):
                continue
            sid = s(st.get("stationID"))
            if not sid:
                continue
            rows.append({
                "station_id": sid,
                "number": chan_by_station.get(sid, ""),
                "name": s(st.get("name")) or s(st.get("callsign")),
                "callsign": s(st.get("callsign")),
                "service": s(service),
            })
        rows.sort(key=lambda r: (r["callsign"], r["station_id"]))
        return rows
    except Exception:
        return []


def filter_channels(rows, terms) -> list:
    """Keep rows whose callsign/name contains any term. NEVER raises."""
    try:
        safe_rows = list(rows) if isinstance(rows, (list, tuple)) else []
        wants = [norm(t) for t in terms if s(t)] if isinstance(terms, (list, tuple)) else []
        if not wants:
            return safe_rows
        out = []
        for r in safe_rows:
            if not isinstance(r, dict):
                continue
            hay = norm(r.get("callsign")) + " " + norm(r.get("name"))
            if any(w in hay for w in wants):
                out.append(r)
        return out
    except Exception:
        return []


def build_config(rows, days=14) -> dict:
    """Assemble public/config.json. NEVER raises."""
    try:
        d = 14
        try:
            d = max(1, min(14, int(days)))
        except Exception:
            d = 14
        seen, channels = set(), []
        for r in rows or []:
            sid = s(r.get("station_id"))
            if not sid or sid in seen:
                continue
            seen.add(sid)
            channels.append({"station_id": sid, "number": s(r.get("number")),
                             "name": s(r.get("name")), "callsign": s(r.get("callsign")),
                             "service": s(r.get("service"))})
        return {"channels": channels, "days": d}
    except Exception:
        return {"channels": [], "days": 14}


# ---- HTTP ------------------------------------------------------------------
def session_token():
    import requests
    user = os.environ.get("SD_USERNAME") or input("Schedules Direct username: ")
    pw = os.environ.get("SD_PASSWORD") or getpass.getpass("Schedules Direct password: ")
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Content-Type": "application/json"})
    h = hashlib.sha1(s(pw).encode("utf-8")).hexdigest()
    r = sess.post(SD_BASE + "/token", json={"username": s(user), "password": h}, timeout=30)
    data = r.json()
    if not isinstance(data, dict) or data.get("code") != 0 or not data.get("token"):
        print("Login failed:", s(data)); sys.exit(1)
    sess.headers.update({"token": s(data.get("token"))})
    return sess


def do_headends(sess, zip_):
    r = sess.get(SD_BASE + "/headends", params={"country": "USA", "postalcode": s(zip_)}, timeout=60)
    rows = parse_headends(r.json())
    if not rows:
        print("No lineups found for", zip_); return
    print("\nAvailable lineups for %s:\n" % zip_)
    for x in rows:
        print("  %-22s %s  [%s]" % (x["lineup"], x["name"], x["transport"]))
    print("\nTip: YouTube TV is usually 'USA-YOUTUBE-X'. Add one with:  add <LINEUP>")


def do_add(sess, lineup):
    r = sess.put(SD_BASE + "/lineups/" + s(lineup), timeout=60)
    d = r.json()
    print("Add %s -> %s (changes remaining: %s)" %
          (lineup, s(d.get("response")) or s(d.get("message")), s(d.get("changesRemaining"))))


def do_remove(sess, lineup):
    r = sess.delete(SD_BASE + "/lineups/" + s(lineup), timeout=60)
    d = r.json()
    print("Remove %s -> %s" % (lineup, s(d.get("response")) or s(d.get("message"))))


def do_list(sess, terms):
    acct = sess.get(SD_BASE + "/lineups", timeout=60).json()
    lineups = acct.get("lineups", []) if isinstance(acct, dict) else []
    if not lineups:
        print("No lineups on your account yet. Use:  headends <ZIP>  then  add <LINEUP>"); return
    all_rows = []
    for ln in lineups:
        lid = s(ln.get("lineup"))
        name = s(ln.get("name")) or lid
        if not lid:
            continue
        data = sess.get(SD_BASE + "/lineups/" + lid, timeout=120).json()
        rows = parse_lineup(data, service=name)
        all_rows.extend(rows)
        print("\n%s  (%d channels)" % (name, len(rows)))
    rows = filter_channels(all_rows, terms)
    print("\n%-6s %-10s %-26s %s" % ("CH", "CALLSIGN", "NAME", "STATION_ID"))
    for r in rows:
        print("%-6s %-10s %-26s %s" % (r["number"], r["callsign"], r["name"][:26], r["station_id"]))
    cfg = build_config(rows)
    os.makedirs(PUBLIC, exist_ok=True)
    with open(os.path.join(PUBLIC, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("\nWrote public/config.json with %d channels%s." %
          (len(cfg["channels"]), " (filtered)" if terms else ""))


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["headends", "add", "remove", "list"])
    p.add_argument("arg", nargs="?", default="")
    p.add_argument("--filter", default="")
    a = p.parse_args(argv[1:])
    sess = session_token()
    if a.mode == "headends":
        do_headends(sess, a.arg)
    elif a.mode == "add":
        do_add(sess, a.arg)
    elif a.mode == "remove":
        do_remove(sess, a.arg)
    elif a.mode == "list":
        terms = [t for t in a.filter.split(",") if t.strip()]
        do_list(sess, terms)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
