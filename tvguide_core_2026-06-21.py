# =============================================================================
#  tvguide_core_2026-06-21.py
#  Pure logic for the family live-TV guide. No network, no filesystem, no I/O.
#  Every public function is defensive: it either returns a documented value or
#  raises only the documented exception. String helpers NEVER raise.
#  Internal timestamp banner: 2026-06-21
# =============================================================================
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

BANNER = "tvguide_core 2026-06-21"

# Guide horizon Schedules Direct realistically provides.
MAX_GUIDE_DAYS = 14
# How far ahead a "starting soon" ping looks, in minutes.
SOON_WINDOW_MIN = 30


# ----------------------------------------------------------------------------
# Safe coercion helpers — these NEVER raise for ANY input.
# ----------------------------------------------------------------------------
def safe_str(x) -> str:
    """Coerce anything to a clean str. NEVER raises.

    bytes -> utf-8 (errors replaced); None -> ""; everything else -> str(x).
    Leading/trailing whitespace and C0 control chars are stripped.
    """
    try:
        if x is None:
            return ""
        if isinstance(x, str):
            s = x
        elif isinstance(x, (bytes, bytearray)):
            try:
                s = bytes(x).decode("utf-8", "replace")
            except Exception:
                return ""
        else:
            s = str(x)
        # strip dangerous control + bidi/zero-width trickery, but KEEP \t \n \r
        s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u200e\u200f\u2066-\u2069]", "", s)
        return s.strip()
    except Exception:
        return ""


def normalize_title(x) -> str:
    """Casefolded, punctuation-light key for matching titles. NEVER raises."""
    try:
        s = safe_str(x).casefold()
        s = re.sub(r"[^0-9a-z\u00c0-\uffff ]+", " ", s)
        s = re.sub(r"\s+", " ", s)
        return s.strip()
    except Exception:
        return ""


def safe_int(x, default: int = 0) -> int:
    """Coerce to int. NEVER raises. Returns default on failure."""
    try:
        if isinstance(x, bool):
            return int(x)
        if isinstance(x, (int, float)):
            return int(x)
        s = safe_str(x)
        if not s:
            return default
        return int(float(s))
    except Exception:
        return default


# ----------------------------------------------------------------------------
# Time helpers
# ----------------------------------------------------------------------------
def parse_utc(x) -> datetime | None:
    """Parse a Schedules Direct ISO-8601 UTC stamp to aware datetime.

    Returns None on any unparseable input. NEVER raises.
    """
    try:
        s = safe_str(x)
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def fmt_local(dt: datetime | None, tz_offset_min: int = 0) -> str:
    """Render an aware datetime in the viewer's local zone. NEVER raises.

    tz_offset_min is minutes east of UTC (e.g. US Central DST = -300).
    """
    try:
        if not isinstance(dt, datetime):
            return ""
        off = safe_int(tz_offset_min, 0)
        # clamp to a sane range so a hostile value can't overflow timedelta
        off = max(-1440, min(1440, off))
        local = dt.astimezone(timezone(timedelta(minutes=off)))
        return local.strftime("%a %-I:%M %p").replace("AM", "AM").replace("PM", "PM")
    except Exception:
        return ""


# ----------------------------------------------------------------------------
# Schedules Direct payload parsing
# ----------------------------------------------------------------------------
def sd_program_title(program: dict) -> str:
    """Extract a display title from a SD /programs entry. NEVER raises."""
    try:
        if not isinstance(program, dict):
            return ""
        titles = program.get("titles")
        if isinstance(titles, list):
            for t in titles:
                if isinstance(t, dict):
                    val = safe_str(t.get("title120"))
                    if val:
                        return val
        return safe_str(program.get("title"))
    except Exception:
        return ""


def sd_episode_label(program: dict) -> str:
    """Return 'SxEy' or the episode title, whichever is available. NEVER raises."""
    try:
        if not isinstance(program, dict):
            return ""
        meta = program.get("metadata")
        if isinstance(meta, list):
            for m in meta:
                if not isinstance(m, dict):
                    continue
                for src in m.values():
                    if isinstance(src, dict):
                        se = safe_int(src.get("season"), 0)
                        ep = safe_int(src.get("episode"), 0)
                        if se and ep:
                            return "S%dE%d" % (se, ep)
        return safe_str(program.get("episodeTitle150"))
    except Exception:
        return ""


def is_new_airing(airing: dict) -> bool:
    """True iff this airing is a first-run (new) broadcast. NEVER raises.

    Schedules Direct marks first-run airings with new=true. Reruns omit it.
    """
    try:
        if not isinstance(airing, dict):
            return False
        return airing.get("new") is True
    except Exception:
        return False


def parse_airing(airing: dict, program_index: dict | None = None) -> dict | None:
    """Normalize one SD airing into a flat record. NEVER raises.

    Returns None when the airing lacks a usable start time or program id.
    """
    try:
        if not isinstance(airing, dict):
            return None
        pid = safe_str(airing.get("programID"))
        start = parse_utc(airing.get("airDateTime"))
        if not pid or start is None:
            return None
        dur = safe_int(airing.get("duration"), 0)
        dur = max(0, min(24 * 3600, dur))
        program = {}
        if isinstance(program_index, dict):
            cand = program_index.get(pid)
            if isinstance(cand, dict):
                program = cand
        return {
            "program_id": pid,
            "title": sd_program_title(program),
            "episode": sd_episode_label(program),
            "start": start,
            "end": start + timedelta(seconds=dur),
            "is_new": is_new_airing(airing),
            "station_id": safe_str(airing.get("_station_id")),
        }
    except Exception:
        return None


def build_schedule(raw_schedules, program_index: dict, channels) -> list:
    """Flatten SD /schedules + /programs + channel map into sorted airings.

    raw_schedules: list of {"stationID", "programs":[airing,...]}.
    channels: list of {"station_id","number","name","callsign","service"}.
    Returns airings sorted by start time, each carrying channel context.
    NEVER raises; malformed entries are skipped.
    """
    out: list = []
    try:
        chan_by_station: dict = {}
        if isinstance(channels, list):
            for c in channels:
                if isinstance(c, dict):
                    sid = safe_str(c.get("station_id"))
                    if sid:
                        chan_by_station[sid] = c
        if not isinstance(raw_schedules, list):
            return out
        for block in raw_schedules:
            if not isinstance(block, dict):
                continue
            sid = safe_str(block.get("stationID"))
            if sid not in chan_by_station:
                continue
            chan = chan_by_station[sid]
            programs = block.get("programs")
            if not isinstance(programs, list):
                continue
            for airing in programs:
                if isinstance(airing, dict):
                    airing = dict(airing)
                    airing["_station_id"] = sid
                rec = parse_airing(airing, program_index)
                if rec is None:
                    continue
                rec["channel_number"] = safe_str(chan.get("number"))
                rec["channel_name"] = safe_str(chan.get("name")) or safe_str(chan.get("callsign"))
                svcs = chan.get("services")
                if isinstance(svcs, list):
                    services = [safe_str(s) for s in svcs if safe_str(s)]
                else:
                    one = safe_str(chan.get("service"))
                    services = [one] if one else []
                rec["service"] = services[0] if services else ""
                rec["services"] = services
                out.append(rec)
        out.sort(key=lambda r: (r["start"], r["channel_name"]))
        return out
    except Exception:
        return out


# ----------------------------------------------------------------------------
# Views: now / next, next airing for a title, upcoming new episodes
# ----------------------------------------------------------------------------
def now_and_next(schedule, now: datetime | None = None) -> list:
    """Per channel: the airing on now and the one immediately after. NEVER raises."""
    try:
        if now is None:
            now = datetime.now(timezone.utc)
        by_chan: dict = {}
        if not isinstance(schedule, list):
            return []
        for rec in schedule:
            if not isinstance(rec, dict):
                continue
            key = rec.get("channel_name") or rec.get("channel_number")
            by_chan.setdefault(key, []).append(rec)
        result = []
        for key, recs in by_chan.items():
            recs = [r for r in recs if isinstance(r.get("start"), datetime)]
            recs.sort(key=lambda r: r["start"])
            current = None
            nxt = None
            for r in recs:
                end = r.get("end")
                if r["start"] <= now and isinstance(end, datetime) and now < end:
                    current = r
                elif r["start"] > now and nxt is None:
                    nxt = r
            if current or nxt:
                result.append({
                    "channel_name": safe_str(key),
                    "channel_number": safe_str((current or nxt).get("channel_number")),
                    "service": safe_str((current or nxt).get("service")),
                    "now": current,
                    "next": nxt,
                })
        result.sort(key=lambda x: x["channel_name"])
        return result
    except Exception:
        return []


def next_airing_for_title(schedule, title, now: datetime | None = None,
                          new_only: bool = False) -> dict | None:
    """Soonest future airing whose title matches. NEVER raises; None if absent."""
    try:
        if now is None:
            now = datetime.now(timezone.utc)
        want = normalize_title(title)
        if not want or not isinstance(schedule, list):
            return None
        best = None
        for rec in schedule:
            if not isinstance(rec, dict):
                continue
            start = rec.get("start")
            if not isinstance(start, datetime) or start < now:
                continue
            if new_only and not rec.get("is_new"):
                continue
            if normalize_title(rec.get("title")) != want:
                continue
            if best is None or start < best["start"]:
                best = rec
        return best
    except Exception:
        return None


def annotate_watchlist(schedule, watchlist, now: datetime | None = None) -> list:
    """For each watched title attach its next airing and next NEW airing.

    NEVER raises. Returns one row per input title (order preserved, dupes kept).
    """
    out = []
    try:
        if not isinstance(watchlist, list):
            return out
        for title in watchlist:
            t = safe_str(title)
            if not t:
                continue
            out.append({
                "title": t,
                "next": next_airing_for_title(schedule, t, now, new_only=False),
                "next_new": next_airing_for_title(schedule, t, now, new_only=True),
            })
        return out
    except Exception:
        return out


def upcoming_new_episodes(schedule, now: datetime | None = None, limit: int = 200) -> list:
    """First-run airings ahead, one row per series (its soonest new airing).

    NEVER raises. Sorted by start time. Covers ALL channels, not just watched.
    """
    try:
        if now is None:
            now = datetime.now(timezone.utc)
        if not isinstance(schedule, list):
            return []
        best_by_series: dict = {}
        for rec in schedule:
            if not isinstance(rec, dict) or not rec.get("is_new"):
                continue
            start = rec.get("start")
            if not isinstance(start, datetime) or start < now:
                continue
            key = normalize_title(rec.get("title"))
            if not key:
                continue
            cur = best_by_series.get(key)
            if cur is None or start < cur["start"]:
                best_by_series[key] = rec
        rows = sorted(best_by_series.values(), key=lambda r: r["start"])
        cap = max(0, min(10000, safe_int(limit, 200)))
        return rows[:cap]
    except Exception:
        return []


def starting_soon(schedule, watchlist, now: datetime | None = None,
                  window_min: int = SOON_WINDOW_MIN, new_only: bool = True) -> list:
    """Watched titles starting within the window. NEVER raises."""
    try:
        if now is None:
            now = datetime.now(timezone.utc)
        win = max(1, min(720, safe_int(window_min, SOON_WINDOW_MIN)))
        horizon = now + timedelta(minutes=win)
        wanted = set()
        if isinstance(watchlist, list):
            for t in watchlist:
                n = normalize_title(t)
                if n:
                    wanted.add(n)
        if not wanted or not isinstance(schedule, list):
            return []
        hits = []
        for rec in schedule:
            if not isinstance(rec, dict):
                continue
            start = rec.get("start")
            if not isinstance(start, datetime) or start < now or start > horizon:
                continue
            if new_only and not rec.get("is_new"):
                continue
            if normalize_title(rec.get("title")) in wanted:
                hits.append(rec)
        hits.sort(key=lambda r: r["start"])
        return hits
    except Exception:
        return []


# ----------------------------------------------------------------------------
# Notification payload building (pure; the send happens in the job runner)
# ----------------------------------------------------------------------------
def _airing_line(rec: dict, tz_offset_min: int) -> str:
    try:
        title = safe_str(rec.get("title")) or "Untitled"
        when = fmt_local(rec.get("start"), tz_offset_min)
        chan = safe_str(rec.get("channel_name"))
        tag = "NEW " if rec.get("is_new") else ""
        parts = [p for p in [tag + title, when, chan] if p]
        return " · ".join(parts)
    except Exception:
        return ""


def build_digest(watchlist_hits, new_today, tz_offset_min: int = 0) -> dict:
    """Build the morning digest push payload. NEVER raises."""
    try:
        lines = []
        wl = watchlist_hits if isinstance(watchlist_hits, list) else []
        nt = new_today if isinstance(new_today, list) else []
        for rec in wl:
            if isinstance(rec, dict):
                ln = _airing_line(rec, tz_offset_min)
                if ln:
                    lines.append(ln)
        body_wl = "\n".join(lines) if lines else "Nothing from your list today."
        new_lines = []
        for rec in nt:
            if isinstance(rec, dict):
                ln = _airing_line(rec, tz_offset_min)
                if ln:
                    new_lines.append(ln)
        body_new = "\n".join(new_lines[:20])
        body = "On your list today:\n" + body_wl
        if body_new:
            body += "\n\nNew episodes today:\n" + body_new
        return {"title": "Today on TV", "body": body, "tag": "tv-digest"}
    except Exception:
        return {"title": "Today on TV", "body": "", "tag": "tv-digest"}


def build_soon_alert(rec: dict, tz_offset_min: int = 0) -> dict:
    """Build a 'starting soon' push payload for one airing. NEVER raises."""
    try:
        title = safe_str(rec.get("title")) or "A show"
        when = fmt_local(rec.get("start"), tz_offset_min)
        chan = safe_str(rec.get("channel_name"))
        new = "New episode" if rec.get("is_new") else "Starting soon"
        body = "%s on %s" % (when, chan) if chan else when
        return {"title": "%s: %s" % (new, title), "body": body,
                "tag": "tv-soon-" + safe_str(rec.get("program_id"))}
    except Exception:
        return {"title": "Starting soon", "body": "", "tag": "tv-soon"}


def serialize_schedule(schedule) -> list:
    """Convert in-memory airings (with datetimes) to JSON-safe dicts. NEVER raises."""
    out = []
    try:
        if not isinstance(schedule, list):
            return out
        for rec in schedule:
            if not isinstance(rec, dict):
                continue
            start = rec.get("start")
            end = rec.get("end")
            out.append({
                "program_id": safe_str(rec.get("program_id")),
                "title": safe_str(rec.get("title")),
                "episode": safe_str(rec.get("episode")),
                "start": start.isoformat() if isinstance(start, datetime) else "",
                "end": end.isoformat() if isinstance(end, datetime) else "",
                "is_new": bool(rec.get("is_new")),
                "channel_number": safe_str(rec.get("channel_number")),
                "channel_name": safe_str(rec.get("channel_name")),
                "service": safe_str(rec.get("service")),
                "services": [safe_str(s) for s in rec.get("services")] if isinstance(rec.get("services"), list) else ([safe_str(rec.get("service"))] if safe_str(rec.get("service")) else []),
            })
        return out
    except Exception:
        return out


def _rec_services(rec) -> list:
    """Service names a record belongs to (list, with single-service fallback). NEVER raises."""
    try:
        if not isinstance(rec, dict):
            return []
        rsv = rec.get("services")
        if isinstance(rsv, list):
            return [safe_str(s) for s in rsv if safe_str(s)]
        one = safe_str(rec.get("service"))
        return [one] if one else []
    except Exception:
        return []


def filter_schedule_by_services(schedule, services) -> list:
    """Keep airings on any of the selected services. Empty/None selection => all.

    NEVER raises.
    """
    try:
        if not isinstance(schedule, list):
            return []
        if isinstance(services, (list, tuple, set)):
            sel = set(safe_str(s).casefold() for s in services if safe_str(s))
        else:
            sel = set()
        if not sel:
            return list(schedule)
        out = []
        for rec in schedule:
            names = _rec_services(rec)
            if any(safe_str(n).casefold() in sel for n in names):
                out.append(rec)
        return out
    except Exception:
        return []


def services_universe(schedule) -> list:
    """Distinct service names present in the guide, in first-seen order. NEVER raises."""
    try:
        seen, keys = [], set()
        for rec in (schedule if isinstance(schedule, list) else []):
            for n in _rec_services(rec):
                k = safe_str(n).casefold()
                if k and k not in keys:
                    keys.add(k)
                    seen.append(safe_str(n))
        return seen
    except Exception:
        return []
