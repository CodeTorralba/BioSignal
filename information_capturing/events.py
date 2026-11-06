"""Calendar of FDA decisions: discovery in EDGAR, the event list, and the comparison with pdufa.bio.

An event is one application waiting for an FDA decision. Its id never changes, even if the date does. Every
date has a source with a quote; a date change keeps the earlier date in `date_history`.
"""

import gzip
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from . import sec
from .common import (DATA, append_rows, get_json, html_to_text, letters, notice, now, read_json, slug, today,
                     write_bytes, write_json, write_rows, write_text)
from .mentions import find_mentions

CAL = DATA / "calendar"
QUERIES = ['"PDUFA"', '"target action date"', '"goal date"']
# An amendment code in the list ("8-K/A") makes EDGAR return only amendments, so none is listed.
FORMS_ALL = "8-K,6-K,10-Q,10-K,20-F,40-F,424B3,424B4,424B5,S-1,F-1"
FORMS_RELEASES = "8-K,6-K"
KEEP_DAYS = 45  # a mention of a date older than this is a past decision and is not followed
CAP_LIMIT = 2e9  # companies under this market value get a folder (micro + small, as in the backtest)

# ---------------------------------------------------------------- event store


def load_events():
    return read_json(CAL / "events.json", {})


def save_events(events):
    write_json(CAL / "events.json", events)
    caps = read_json(CAL / "market_caps.json", {})
    rows = []
    for e in sorted(events.values(), key=lambda e: (e.get("date_start") or "9999", e["id"])):
        cap = caps.get(e.get("ticker") or "", {}).get("market_cap")
        rows.append(e | {"market_cap": cap, "n_sources": len(e.get("sources", [])), "aliases": "; ".join(e.get("aliases", []))})
    write_rows(CAL / "calendar.csv", rows, ["id", "date_start", "date_end", "precision", "ticker", "company", "drug",
                                             "aliases", "indication", "application", "own", "status", "outcome",
                                             "market_cap", "tracked", "edgar_confirmed", "pdufa_bio_id", "n_sources",
                                             "first_seen", "last_seen"])


DOSAGE = re.compile(r"\b(?:injection|tablets?|capsules?|cream|gel|ointment|oral|solution|suspension|for|extended[- ]release|"
                    r"autoinjector|subcutaneous|intravenous|ophthalmic|nasal|spray|film|patch|\d+(?:\.\d+)?\s?%|\d+\s?mg)\b", re.I)


def split_names(s):
    """Names of a product as written by a source: "Veligrotug (VRDN-001) - (THRIVE-2)" -> ["Veligrotug", "VRDN-001"]."""
    s = re.sub(r"\s+-\s+\([^)]*\)\s*$", "", s or "")  # trial name at the end in pdufa.bio
    parts = re.split(r"[()\[\]]|\s\+\s|\swith\s|/|;|,|\s—\s|\s-\s", s)
    out = []
    for p in parts:
        p = DOSAGE.sub(" ", p)
        p = re.sub(r"[™®]", "", re.sub(r"\s+", " ", p)).strip(" .-")
        if len(p) >= 3 and p.lower() not in {"and", "the", "formerly", "also known as"}:
            out.append(p)
    return out


def keys(names):
    """Comparable keys of names: the letters and digits of each name and of its first word (5+ letters)."""
    out = set()
    for n in names:
        k = letters(n)
        if len(k) >= 4:
            out.add(k)
        first = letters(n.split()[0]) if n.split() else ""
        if len(first) >= 5:
            out.add(first)
    return out


def same_product(e, names):
    return bool(keys([e.get("drug", "")] + e.get("aliases", [])) & keys(names))


def is_small(e, caps=None):
    caps = caps if caps is not None else read_json(CAL / "market_caps.json", {})
    cap = caps.get(e.get("ticker") or "", {}).get("market_cap")
    return cap is None or cap < CAP_LIMIT


def describe(e):
    when = e.get("date_start") if e.get("precision") == "day" else f"{e.get('date_text')} ({e.get('precision')})"
    return f"{e.get('ticker') or e.get('company')} {e.get('drug')} PDUFA {when}"


def new_event(cik, company, ticker, drug, aliases, indication, application, own, d, date_text, src):
    eid = f"{int(cik) if cik else slug(ticker or company)}_{slug(drug, 30)}_{d['start'][:7]}"
    return {"id": eid, "cik": cik, "company": company, "ticker": ticker, "drug": drug,
            "aliases": sorted(set(aliases) - {drug}), "indication": indication, "application": application,
            "own": own, "date_text": date_text, "precision": d["precision"], "date_start": d["start"],
            "date_end": d["end"], "status": "pending", "outcome": None, "decision": None,
            "date_history": [{"precision": d["precision"], "start": d["start"], "end": d["end"],
                              "date_text": date_text, "seen": today().isoformat()} | src],
            "sources": [src], "pdufa_bio_id": None, "edgar_confirmed": src["kind"] == "edgar",
            "tracked": False, "first_seen": today().isoformat(), "last_seen": today().isoformat()}


def add_event(events, e):
    base, n = e["id"], 2
    while e["id"] in events:
        e["id"] = f"{base}_{n}"
        n += 1
    events[e["id"]] = e
    return e


def set_date(e, d, date_text, src, caps=None):
    """Adds a source and, if its date is different and not older news, changes the date and keeps the old one."""
    e["sources"].append(src)
    e["last_seen"] = today().isoformat()
    if src["kind"] == "edgar":
        e["edgar_confirmed"] = True
    if (d["start"], d["end"]) == (e["date_start"], e["date_end"]):
        return False
    newest = max((h.get("filed") or h.get("seen") or "" for h in e["date_history"]), default="")
    if (src.get("filed") or "") < newest:
        return False  # an older document repeating an earlier date does not undo a newer one
    old = describe(e)
    e["date_history"].append({"precision": d["precision"], "start": d["start"], "end": d["end"],
                              "date_text": date_text, "seen": today().isoformat()} | src)
    e.update(precision=d["precision"], date_start=d["start"], date_end=d["end"], date_text=date_text)
    if e.get("status") == "pending" and is_small(e, caps):
        notice("Date changes", f"{old} -> {d['start'] if d['precision'] == 'day' else date_text} "
                               f"(source: {src.get('form', src['kind'])} {src.get('filed', '')} {src.get('url', '')})")
    return True


def decide(e, outcome, when, src):
    e.update(status="withdrawn" if outcome == "withdrawn" else "decided", outcome=outcome,
             decision={"date": when, "seen": now()} | src)
    if e.get("tracked") or is_small(e):
        notice("Decisions", f"{describe(e)}: {outcome.upper()} on {when} — \"{src.get('quote', '')[:200]}\" ({src.get('url', '')})")


# ---------------------------------------------------------------- discovery in EDGAR


def _doc_path(h):
    return CAL / "docs" / h["adsh"] / (h["file"] + ".gz")


def _download(h):
    p = _doc_path(h)
    if not p.exists():
        body = sec.get(sec.doc_url(h["cik"], h["adsh"], h["file"]))
        write_bytes(p, gzip.compress(body or b""))
    return h, html_to_text(gzip.decompress(p.read_bytes()))


def _seen(name):
    p = CAL / name
    return set(p.read_text().split()) if p.exists() else set()


def _remember(name, values):
    if values:
        with open(CAL / name, "a") as f:
            f.write("\n".join(values) + "\n")


def discover(days, forms=FORMS_ALL):
    """Searches EDGAR for PDUFA mentions filed in the last `days` days and queues new ones for the agent.

    Every downloaded document is kept (gzip) in calendar/docs. A mention whose exact day matches a pending event of
    the same company is attached to it directly; anything else goes to the agent with the company's known events.
    """
    from .batches import queue_item
    end = today()
    seen_hits = _seen("seen_hits.txt")
    hits = {}
    for q in QUERIES:
        for h in sec.efts(q, end - timedelta(days=days), end, forms):
            if h["id"] not in seen_hits and h["file"].lower().endswith((".htm", ".html", ".txt")):
                hits[h["id"]] = h
    print(f"  EDGAR: {len(hits)} new documents with PDUFA terms in {days} days", flush=True)
    events = load_events()
    seen_ex = _seen("seen_excerpts.txt")
    names = sec.tickers()
    new_seen, new_ex, queued, attached = [], [], 0, 0
    with ThreadPoolExecutor(sec.THREADS) as pool:
        for h, text in pool.map(_download, sorted(hits.values(), key=lambda h: h["filed"])):
            new_seen.append(h["id"])
            filed = date.fromisoformat(h["filed"])
            cik = h["cik"].zfill(10)
            fresh = []
            for m in find_mentions(text, filed, today() - timedelta(days=KEEP_DAYS)):
                k = f"{cik}:{hashlib.sha1(letters(m['excerpt']).encode()).hexdigest()[:16]}"
                if k in seen_ex:
                    continue
                seen_ex.add(k)
                new_ex.append(k)
                fresh.append(m)
            url = sec.doc_url(cik, h["adsh"], h["file"])
            src = {"kind": "edgar", "url": url, "filed": h["filed"], "form": h["form"]}
            rest = []
            for m in fresh:
                d = m["date"]
                match = [e for e in events.values() if e.get("cik") == cik and e["status"] == "pending"
                         and e["precision"] == "day" and d["precision"] == "day" and e["date_start"] == d["start"]]
                if len(match) == 1:
                    set_date(match[0], d, match[0]["date_text"], src | {"quote": m["excerpt"][:400]})
                    attached += 1
                else:
                    rest.append(m["excerpt"])
            if rest:
                info = names.get(cik, {})
                queue_item("date", cik=cik, company=info.get("name") or h["name"], tickers=info.get("tickers", []),
                           form=h["form"], filed=h["filed"], url=url, excerpts=rest[:6], events=events)
                queued += 1
    _remember("seen_hits.txt", new_seen)
    _remember("seen_excerpts.txt", new_ex)
    save_events(events)
    print(f"  EDGAR: {attached} mentions attached to known events, {queued} documents queued for the agent", flush=True)


# ---------------------------------------------------------------- pdufa.bio

PDUFA_BIO = "https://www.pdufa.bio/api/v1"


def _bio_date(r):
    """Date of a pdufa.bio record as {"precision", "start", "end"}; None if it is vaguer than a month."""
    if r.get("date") and r.get("date_precision") == "day":
        return {"precision": "day", "start": r["date"], "end": r["date"]}
    m = re.fullmatch(r"(\d{4})-(\d\d)", r.get("date_month") or "")
    if r.get("date_precision") == "month" and m:
        y, mo = int(m.group(1)), int(m.group(2))
        end = (date(y + mo // 12, mo % 12 + 1, 1) - timedelta(days=1)).isoformat()
        return {"precision": "month", "start": f"{y}-{mo:02d}-01", "end": end}
    return None


def pdufa_bio():
    """Daily copy of pdufa.bio (kept), the events it has and EDGAR does not, and the comparison with EDGAR."""
    raw = get_json(f"{PDUFA_BIO}/pdufa", {"limit": 1000})
    write_json(CAL / "pdufa_bio" / f"{today().isoformat()}.json.gz", raw, gz=True)
    adcomm = get_json(f"{PDUFA_BIO}/adcomm", {"limit": 1000})
    write_json(CAL / "pdufa_bio" / f"{today().isoformat()}_adcomm.json.gz", adcomm, gz=True)
    events = load_events()
    recent = (today() - timedelta(days=120)).isoformat()
    rows = raw.get("data", [])
    for r in rows:
        names = split_names(r.get("name"))
        d = _bio_date(r)
        cik = sec.cik_of_ticker(r.get("ticker"))
        mine = next((e for e in events.values() if e.get("pdufa_bio_id") == r["id"]), None)
        if not mine:
            # The ticker in pdufa.bio can be the partner (GSK for Spero's tebipenem): match by product, same company first.
            near = [e for e in events.values() if same_product(e, names)
                    and (e["status"] == "pending" or ((e.get("decision") or {}).get("date") or "") >= recent)]
            near.sort(key=lambda e: e.get("cik") != cik)
            mine = near[0] if near else None
        if not mine and r.get("status") == "Upcoming" and d and names:
            src = {"kind": "pdufa.bio", "url": r.get("url"), "filed": None, "quote": r.get("name"),
                   "primary_source": r.get("source_url")}
            date_text = r.get("date") or r.get("date_month")
            mine = add_event(events, new_event(cik, r.get("company"), r.get("ticker"), names[0], names,
                                               r.get("indication"), None, None, d, date_text, src))
        if mine:
            mine["pdufa_bio_id"] = r["id"]
            mine["pdufa_bio"] = {k: r.get(k) for k in ("id", "ticker", "name", "date", "date_precision", "date_month",
                                                        "status", "outcome", "decision_date", "decision_source_url",
                                                        "source_url", "market_cap_usd", "goal_date_held", "url")}
            mine["pdufa_bio"]["period"] = d
            if not mine.get("ticker") and r.get("ticker"):
                mine["ticker"] = r["ticker"]
    save_events(events)
    _compare(events, read_json(CAL / "market_caps.json", {}))
    print(f"  pdufa.bio: {len(rows)} PDUFA records", flush=True)


def _compare(events, caps):
    """calendar/pdufa_bio_comparison.md: what each source has that the other does not, and where they disagree."""
    horizon = (today() + timedelta(days=183)).isoformat()
    only_bio, only_edgar, dates, outcomes = [], [], [], []
    for e in events.values():
        b = e.get("pdufa_bio")
        if e["status"] == "pending" and not e.get("edgar_confirmed") and b:
            only_bio.append(e)
        if e["status"] == "pending" and e.get("edgar_confirmed") and not b and (e.get("date_start") or "") <= horizon:
            only_edgar.append(e)
        p = (b or {}).get("period")
        if p and e["status"] == "pending" and b.get("status") == "Upcoming" and (p["end"] < e["date_start"] or p["start"] > e["date_end"]):
            dates.append((e, b.get("date") or b.get("date_month")))
        if b and b.get("outcome") and e["status"] == "pending":
            outcomes.append((e, b))
    out = [f"# EDGAR vs pdufa.bio — {today().isoformat()}", "",
           "Built every day. EDGAR events come from company filings with a quote; pdufa.bio is a secondary source.", ""]
    out += [f"## Only in pdufa.bio, not confirmed by EDGAR ({len(only_bio)})", ""]
    out += [f"- {describe(e)} — pdufa.bio {e['pdufa_bio']['url']} (its source: {e['pdufa_bio'].get('source_url')})" for e in only_bio]
    out += ["", f"## Only in EDGAR, PDUFA in the next 6 months ({len(only_edgar)})", ""]
    out += [f"- {describe(e)} — {e['sources'][-1].get('url')}" for e in only_edgar]
    out += ["", f"## Different date ({len(dates)})", ""]
    out += [f"- {describe(e)} — pdufa.bio says {bd}" for e, bd in dates]
    out += ["", f"## pdufa.bio already has an outcome, EDGAR not yet ({len(outcomes)})", ""]
    out += [f"- {describe(e)} — pdufa.bio: {b['outcome']} on {b.get('decision_date')} ({b.get('decision_source_url')})" for e, b in outcomes]
    write_text(CAL / "pdufa_bio_comparison.md", "\n".join(out) + "\n")
    for e in only_bio:
        if is_small(e, caps):
            notice("pdufa.bio comparison", f"only in pdufa.bio: {describe(e)} ({e['pdufa_bio']['url']})", key=f"bio-only:{e['id']}")
    for e, bd in dates:
        if is_small(e, caps):
            notice("pdufa.bio comparison", f"different date: {describe(e)}; pdufa.bio says {bd}", key=f"bio-date:{e['id']}:{bd}:{e['date_start']}")
    for e, b in outcomes:
        if is_small(e, caps):
            notice("pdufa.bio comparison", f"pdufa.bio says {b['outcome']} on {b.get('decision_date')} for {describe(e)}; "
                                           f"not yet seen in a company filing ({b.get('decision_source_url')})", key=f"bio-outcome:{e['id']}")


def log_rejected(rows):
    append_rows(DATA / "batches" / "rejected.csv", rows, ["at", "batch", "item", "reason", "line"])
