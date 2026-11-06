"""Shared helpers: settings, data paths, HTTP with per-source limits, files, text and notices."""

import csv
import gzip
import html
import json
import os
import re
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_env():
    """Read KEY=value lines from the repository's .env without overriding the real environment."""
    p = REPO / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_env()
DATA = Path(os.environ.get("BIOSIGNAL_DATA") or REPO / "data_collection").expanduser()


class SourceError(Exception):
    """A source failed; the step that uses it stops, the other steps go on."""


def today():
    return date.today()


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def contact():
    c = os.environ.get("BIOSIGNAL_CONTACT")
    if not c:
        raise SourceError("BIOSIGNAL_CONTACT is not set (name and email): the SEC rejects requests without a contact")
    return c


def contact_email():
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", contact())
    return m.group(0) if m else None


# ---------------------------------------------------------------- HTTP

# Seconds between two requests to the same service. The SEC allows 10 per second in total; NCBI 3 without a key;
# ClinicalTrials.gov about 50 per minute; pdufa.bio 10 per minute without a key.
INTERVAL = {
    "sec.gov": 1 / 6, "ncbi.nlm.nih.gov": 0.4, "clinicaltrials.gov": 1.3, "pdufa.bio": 6.5, "api.fda.gov": 0.3,
    "fda.gov": 1.0, "federalregister.gov": 0.5, "kalshi.com": 0.3, "polymarket.com": 0.3, "unpaywall.org": 0.2,
}
_guard = threading.Lock()
_locks, _last = {}, {}


def _wait(host):
    key = next((k for k in INTERVAL if host == k or host.endswith("." + k)), host)
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        gap = _last.get(key, 0) + INTERVAL.get(key, 1.0) - time.monotonic()
        if gap > 0:
            time.sleep(gap)
        _last[key] = time.monotonic()


def get(url, params=None, tries=5, timeout=60, headers=None):
    """Body of the response, or None if the server answers 404. Retries throttling and server errors."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    host = urllib.parse.urlsplit(url).hostname or ""
    sec = host.endswith("sec.gov")
    h = {"User-Agent": contact() if sec else f"BioSignal/0.1 (research; {contact_email() or 'no email'})",
         "Accept-Encoding": "gzip"} | (headers or {})
    wait = 1
    for i in range(tries):
        _wait(host)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                body = r.read()
                return gzip.decompress(body) if r.headers.get("Content-Encoding") == "gzip" else body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            # The SEC answers 403 when it throttles; elsewhere a 403 is a real refusal.
            if e.code not in (429, 500, 502, 503, 504) and not (e.code == 403 and sec):
                raise SourceError(f"HTTP {e.code} for {url}") from None
            wait = float(e.headers.get("Retry-After") or 2 ** i) if e.headers else 2 ** i
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            wait = 2 ** i
        time.sleep(min(wait, 60))
    raise SourceError(f"no answer after {tries} tries: {url}")


def get_json(url, params=None, **kw):
    body = get(url, params, **kw)
    return None if body is None else json.loads(body)


# ---------------------------------------------------------------- files


def write_bytes(p, body):
    """Atomic write: a run cut in the middle never leaves half a file."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(body)
    tmp.replace(p)


def write_text(p, s):
    write_bytes(p, s.encode("utf-8"))


def write_json(p, obj, gz=False):
    body = json.dumps(obj, indent=None if gz else 1, ensure_ascii=False, default=str).encode("utf-8")
    write_bytes(p, gzip.compress(body) if gz else body)


def read_json(p, default=None):
    p = Path(p)
    if not p.exists():
        return default
    body = p.read_bytes()
    return json.loads(gzip.decompress(body) if p.suffix == ".gz" else body)


def read_rows(p):
    p = Path(p)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(p, rows, fields):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(p)


def append_rows(p, rows, fields):
    if not rows:
        return
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- text


def html_to_text(body):
    raw = body.decode("utf-8", "ignore") if isinstance(body, bytes) else body
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(?:p|div|tr|li|h\d)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    t = html.unescape(raw).replace("\xa0", " ")
    t = re.sub("[‐-―−]", "-", t)
    t = re.sub("[“”]", '"', t)
    t = re.sub("[‘’]", "'", t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def flat(t):
    """Text on one line, for searching sentences."""
    return re.sub(r"\s+", " ", t)


def letters(s):
    """Only letters and digits, lower case: to check that a quote appears in a text despite spacing or quotes."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def slug(s, n=40):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:n] or "x"


def name_pattern(names):
    """Regex that finds any of the names as a whole word (case-insensitive); None if there are no names."""
    names = sorted({n for n in names if n and len(n) >= 4}, key=len, reverse=True)
    if not names:
        return None
    return re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(n) for n in names) + r")(?![\w-])", re.I)


# ---------------------------------------------------------------- notices and status

NOTICE_ORDER = ["Decisions", "Date changes", "New events", "Packs ready", "Advisory committees", "Company movements",
                "Trial changes", "Papers to download", "pdufa.bio comparison", "Source failures"]


def notice(section, text, key=None):
    """Something that matters for the user. With a key, the same notice is given only once."""
    sent_p = DATA / "notices" / "sent_keys.json"
    if key:
        sent = read_json(sent_p, {})
        if key in sent:
            return
        sent[key] = now()
        write_json(sent_p, sent)
    p = DATA / "notices" / f"{today().isoformat()}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"section": section, "text": text, "at": now()}, ensure_ascii=False) + "\n")


def render_notices(day=None):
    """Writes notices/<day>.md from that day's notices; returns its path, or None if there is nothing to say."""
    day = (day or today()).isoformat()
    p = DATA / "notices" / f"{day}.jsonl"
    if not p.exists():
        return None
    items = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not items:
        return None
    by = {}
    for it in items:
        by.setdefault(it["section"], [])
        if it["text"] not in by[it["section"]]:
            by[it["section"]].append(it["text"])
    out = [f"# BioSignal notices {day}", ""]
    for s in sorted(by, key=lambda s: NOTICE_ORDER.index(s) if s in NOTICE_ORDER else 99):
        out += [f"## {s}", ""] + [f"- {t}" for t in by[s]] + [""]
    md = DATA / "notices" / f"{day}.md"
    write_text(md, "\n".join(out))
    return md


def run_step(name, fn, *args):
    """Runs one step. A failure is recorded and notified, and does not stop the other steps."""
    st_p = DATA / "status.json"
    st = read_json(st_p, {})
    s = st.setdefault(name, {})
    t0 = time.monotonic()
    try:
        result = fn(*args)
        s.update(last_ok=now(), seconds=round(time.monotonic() - t0, 1), error=None)
        return result
    except Exception as e:  # noqa: BLE001 - one source failing must not stop the run
        s.update(last_error=now(), error=f"{type(e).__name__}: {e}")
        log = DATA / "logs" / f"{today().isoformat()}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"--- {now()} {name}\n{traceback.format_exc()}\n")
        notice("Source failures", f"{name}: {type(e).__name__}: {str(e)[:300]} (details in logs/{log.name})",
               key=f"fail:{name}:{today().isoformat()}")
        print(f"  ! {name} failed: {e}", flush=True)
        return None
    finally:
        st = read_json(st_p, {}) | {name: s}
        write_json(st_p, st)


class RunLock:
    """Only one run at a time: a second run started while another is working does nothing."""

    def __init__(self):
        self.p = DATA / ".lock"

    def __enter__(self):
        self.p.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(self.p.read_text().strip() or 0)
                os.kill(pid, 0)
                raise SystemExit(f"another run is working (pid {pid}); nothing done")
            except PermissionError:
                raise SystemExit("another run is working; nothing done") from None
            except (ValueError, ProcessLookupError):
                self.p.unlink(missing_ok=True)  # the previous run died: take the lock
                return self.__enter__()
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        self.p.unlink(missing_ok=True)
