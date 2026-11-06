"""One folder per small company waiting for an FDA decision: which companies, what is collected, and the pack.

A company is followed while it has an event that is pending, owned by it, with the decision expected in the next
6 months, and a market value under $2B. After the decision it is followed 10 more trading sessions (to record the
price reaction) and then closed. Folder layout: see information_capturing/README.md.
"""

import re
from datetime import date, timedelta

from . import events as ev
from . import fda, market, science, sec
from .batches import queue_item
from .common import (DATA, append_rows, flat, notice, now, read_json, read_rows, run_step, today, write_json,
                     write_rows, write_text)

COMP = DATA / "companies"
WINDOW_DAYS = 183  # start following 6 months before the earliest possible decision date
PACK_DAYS = 7  # the pack for our analysis is ready 7 days before
AFTER_SESSIONS = 10  # trading sessions recorded after the decision
NO_NEWS_DAYS = 45  # a pending event this long past its date with no decision seen stops being followed
BACKFILL_DAYS = 730  # documents downloaded when a company starts being followed
TIMELINE = ["published", "captured_at", "kind", "title", "path", "url"]
FILING_FIELDS = ["accession", "form", "filed", "accepted", "items", "description", "primary", "size", "folder"]
DOC_FORMS = {"8-K", "8-K/A", "6-K", "6-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "20-F", "20-F/A", "40-F", "S-1",
             "S-1/A", "F-1", "F-1/A"}
FINANCING = re.compile(r"^(?:424B\d|S-1|S-3|F-1|F-3)")
DECISION_SENTENCE = re.compile(r"[^.]{0,400}\b(?:FDA|Food and Drug Administration)\b[^.]{0,300}"
                               r"(?:approv(?:ed|es|al of)|complete response|\bCRL\b|withdr[ae]w|refus)[^.]{0,400}\.?"
                               r"|[^.]{0,400}(?:complete response letter|approved by the (?:U\.S\. )?(?:FDA|Food and Drug Administration))[^.]{0,400}\.?", re.I)
SUFFIX = re.compile(r",?\s*\b(?:Inc|Incorporated|Corp|Corporation|Ltd|Limited|plc|PLC|N\.V|S\.A|SE|AG|Co|LLC|Holdings|Group)\b\.?", re.I)


def doc_form(form):
    return form in DOC_FORMS or form.startswith("424B")


def company_names(name):
    """Names to search a company by: "Savara Inc." -> ["Savara"]; "Capricor Therapeutics, Inc." -> both forms."""
    base = SUFFIX.sub("", name or "").strip(" ,.")
    short = re.sub(r"\s+(?:Therapeutics|Pharmaceuticals|Pharma|Biosciences|Bio|Biotherapeutics|Biopharma)$", "", base, flags=re.I)
    return [n for n in dict.fromkeys([base, short]) if len(n) >= 4]


def folder(ticker):
    return COMP / ticker.upper()


def timeline(f, rows):
    append_rows(f / "timeline.csv", [r | {"captured_at": now()} for r in rows], TIMELINE)


def drug_names(evs):
    names = set()
    for e in evs:
        names |= {e.get("drug", "")} | set(e.get("aliases", []))
    names = {re.sub(r"[™®©]", "", n).strip() for n in names}  # openFDA rejects "REZZAYO®"
    return sorted(n for n in names if n and len(n) >= 3)


# ---------------------------------------------------------------- which companies


def select():
    """Marks the events to follow and opens folders for new companies; returns the companies to collect."""
    events = ev.load_events()
    horizon = (today() + timedelta(days=WINDOW_DAYS)).isoformat()
    stale = (today() - timedelta(days=NO_NEWS_DAYS)).isoformat()
    cand = [e for e in events.values() if e.get("ticker") and e.get("own") is not False and e["status"] == "pending"
            and e["date_start"] <= horizon and e["date_end"] >= stale]
    caps = market.caps()
    missing = [e["ticker"] for e in cand if e["ticker"] not in caps]
    if missing:
        caps = market.refresh_caps(missing)
    cand_ids = {e["id"] for e in cand}
    for e in events.values():
        cap = caps.get(e.get("ticker") or "", {}).get("market_cap")
        want = e["id"] in cand_ids and cap is not None and cap < ev.CAP_LIMIT
        if e.get("tracked") and e["status"] == "pending" and e["date_end"] < stale:
            notice("Decisions", f"{ev.describe(e)}: no decision seen {NO_NEWS_DAYS} days after the date; no longer followed. Check it by hand.",
                   key=f"stale:{e['id']}")
            e["tracked"], e["closed"] = False, today().isoformat()
        elif want and not e.get("tracked") and not e.get("closed"):
            e["tracked"], e["tracking_since"] = True, today().isoformat()
            notice("New events", f"{ev.describe(e)} — {e.get('indication') or 'indication not stated'}; market value "
                                 f"${cap / 1e6:,.0f}M; folder companies/{e['ticker']}/", key=f"track:{e['id']}")
    ev.save_events(events)
    active = {}
    for e in events.values():
        if e.get("tracked"):
            active.setdefault(e["ticker"].upper(), []).append(e)
    for t, evs in active.items():
        f = folder(t)
        info = read_json(f / "company.json", {})
        info.update(ticker=t, cik=evs[0].get("cik"), name=evs[0].get("company"), events=[e["id"] for e in evs],
                    status="active", started=info.get("started") or today().isoformat())
        write_json(f / "company.json", info)
        write_json(f / "events.json", evs)
    return active


# ---------------------------------------------------------------- SEC documents


def sec_update(t, evs, events):
    """Lists every filing of the company, downloads the documents of the useful forms and queues possible decisions."""
    f = folder(t)
    info = read_json(f / "company.json", {})
    cik = info.get("cik")
    if not cik:
        return
    raw, rows = sec.submissions(cik)
    write_json(f / "sec" / "submissions.json", raw)
    known = {r["accession"]: r for r in read_rows(f / "sec" / "filings.csv")}
    first = not known
    since = (date.fromisoformat(info["started"]) - timedelta(days=BACKFILL_DAYS)).isoformat()
    jobs, new_rows = [], []
    for r in rows:
        acc, form = r["accessionNumber"], r["form"]
        if acc in known:
            continue
        d = f"sec/{r['filingDate']}_{form.replace('/', '-').replace(' ', '')}_{acc}"
        row = {"accession": acc, "form": form, "filed": r["filingDate"], "accepted": r.get("acceptanceDateTime"),
               "items": r.get("items"), "description": r.get("primaryDocDescription"), "primary": r.get("primaryDocument"),
               "size": r.get("size"), "folder": ""}
        if doc_form(form) and r["filingDate"] >= since:
            row["folder"] = d
            jobs.append((cik, acc, form, f / d))
        new_rows.append(row)
        known[acc] = row
    got = sec.download_many(jobs) if jobs else {}
    for acc in [a for a, docs in got.items() if docs is None]:
        del known[acc]  # not recorded: tried again on the next run
        new_rows = [r for r in new_rows if r["accession"] != acc]
    write_rows(f / "sec" / "filings.csv", sorted(known.values(), key=lambda r: r["filed"], reverse=True), FILING_FIELDS)
    pending = [e for e in evs if e["status"] == "pending"]
    tl = []
    refresh_facts = first
    for row in new_rows:
        docs = got.get(row["accession"]) or []
        for name, typ, _ in docs:
            tl.append({"published": row["filed"], "kind": f"SEC {row['form']}", "title": f"{typ} {row['description'] or ''}".strip(),
                       "path": f"{row['folder']}/{name}", "url": sec.doc_url(cik, row["accession"], name)})
        if first:
            continue  # the backfill is history, not news
        if FINANCING.match(row["form"]):
            notice("Company movements", f"{t}: {row['form']} filed {row['filed']} (share or debt offering) — "
                                        f"{sec.doc_url(cik, row['accession'], row['primary'] or '')}")
        if row["form"].startswith(("10-Q", "10-K", "20-F", "40-F")):
            refresh_facts = True
        if row["form"].startswith(("8-K", "6-K")) and pending:
            sentences = []
            for _, _, text in docs:
                sentences += [m.group(0).strip() for m in DECISION_SENTENCE.finditer(flat(text))]
            if sentences:
                queue_item("decision", cik=cik, company=info.get("name"), tickers=[t], form=row["form"], filed=row["filed"],
                           url=sec.doc_url(cik, row["accession"], row["primary"] or ""), excerpts=sentences[:8],
                           events=events, accepted=row["accepted"], known=pending)
    timeline(f, tl)
    if refresh_facts:
        facts = sec.company_facts(cik)
        if facts:
            write_json(f / "sec" / "companyfacts" / f"{today().isoformat()}.json.gz", facts, gz=True)
            write_rows(f / "sec" / "financials.csv", sec.facts_rows(facts),
                       ["concept", "unit", "value", "start", "end", "frame", "form", "filed", "accession"])


# ---------------------------------------------------------------- collection per company


def daily(t, evs, events, new):
    f = folder(t)
    run_step(f"{t}: SEC", sec_update, t, evs, events)
    run_step(f"{t}: prices", market.prices, f / "market" / "prices.csv", t)
    run_step(f"{t}: options", market.options, f / "market", t)
    run_step(f"{t}: Kalshi", market.kalshi_daily, f / "market", t)
    run_step(f"{t}: Polymarket", market.polymarket_daily, f / "market", drug_names(evs))
    if new:
        weekly(t, evs)


def weekly(t, evs):
    f = folder(t)
    info = read_json(f / "company.json", {})
    names = drug_names(evs)
    indication = " ".join(e.get("indication") or "" for e in evs)
    changes = run_step(f"{t}: trials", science.trials, f / "trials", company_names(info.get("name")), names) or []
    for nct, upd, d in changes:
        notice("Trial changes", f"{t} {nct} (registry update {upd}): " + "; ".join(d)[:500] + f" — companies/{t}/trials/changes.md")
        timeline(f, [{"published": upd, "kind": "Trial change", "title": f"{nct}: " + "; ".join(d)[:200],
                      "path": f"trials/{nct}/{upd}.json", "url": f"https://clinicaltrials.gov/study/{nct}"}])
    need = run_step(f"{t}: papers", science.papers, f / "papers", names, indication) or []
    if need:
        notice("Papers to download", f"{t}: {len(need)} new papers without open full text — companies/{t}/papers/to_download.md")
    fda_seen = set(info.get("drugsfda_seen", []))
    for line_date, line in run_step(f"{t}: Drugs@FDA", fda.drugsfda, f / "fda", names) or []:
        if line in fda_seen:
            continue
        fda_seen.add(line)
        pending = [e for e in evs if e["status"] == "pending" and line_date >= (date.fromisoformat(e["date_start"]) - timedelta(days=120)).isoformat()]
        if pending:
            queue_item("decision", cik=info.get("cik"), company=info.get("name"), tickers=[t], form="Drugs@FDA", filed=line_date,
                       url="https://www.accessdata.fda.gov/scripts/cder/daf/", excerpts=[line], events={}, known=pending)
    letters = run_step(f"{t}: CRL database", fda.crl, f / "fda", company_names(info.get("name"))) or []
    seen = set(info.get("crl_seen", []))
    for r in letters:
        k = r.get("file_name") or r.get("letter_date")
        if k in seen:
            continue
        seen.add(k)
        timeline(f, [{"published": r.get("letter_date"), "kind": "FDA CRL letter", "title": r.get("application_number"),
                      "path": f"fda/crl/{today().isoformat()}.json", "url": ""}])
        pending = [e for e in evs if e["status"] == "pending"]
        if pending and info.get("crl_seen") is not None:
            queue_item("decision", cik=info.get("cik"), company=info.get("name"), tickers=[t], form="FDA CRL database",
                       filed=r.get("letter_date") or "", url="https://open.fda.gov/apis/transparency/completeresponseletters/",
                       excerpts=[flat(r.get("text") or "")[:1500]], events={}, known=pending)
    info["crl_seen"], info["drugsfda_seen"] = sorted(seen), sorted(fda_seen)
    write_json(f / "company.json", info)


# ---------------------------------------------------------------- pack and closing


def _sessions_after(f, day):
    return sum(1 for r in read_rows(f / "market" / "prices.csv") if r["date"] > day)


def close_finished(active):
    """An event decided AFTER_SESSIONS trading sessions ago stops being followed; so does its company if it was the last."""
    events = ev.load_events()
    for t, evs in active.items():
        f = folder(t)
        for e in evs:
            d = (e.get("decision") or {}).get("date")
            if e["status"] != "pending" and d and _sessions_after(f, d) >= AFTER_SESSIONS:
                events[e["id"]].update(tracked=False, closed=today().isoformat())
        if not any(events[e["id"]].get("tracked") for e in evs):
            info = read_json(f / "company.json", {})
            write_json(f / "company.json", info | {"status": "closed", "closed": today().isoformat()})
    ev.save_events(events)


def _fmt_money(v):
    try:
        return f"${float(v) / 1e6:,.1f}M"
    except (TypeError, ValueError):
        return "-"


def pack(t, evs):
    """Writes pack/PACK.md (a map of everything collected) from 7 days before the date until the decision."""
    due = [e for e in evs if e["status"] == "pending"
           and (date.fromisoformat(e["date_start"]) - today()).days <= PACK_DAYS]
    if not due:
        return
    f = folder(t)
    info = read_json(f / "company.json", {})
    prices = read_rows(f / "market" / "prices.csv")
    caps = market.caps().get(t, {})
    out = [f"# Pack {t} — {info.get('name')}", "", f"Built {now()} UTC. Everything listed is in this folder; paths are relative to it.", ""]
    for e in due:
        out += [f"## Event {e['id']}", "",
                f"- Drug: **{e['drug']}**" + (f" (other names: {', '.join(e['aliases'])})" if e.get("aliases") else ""),
                f"- Indication: {e.get('indication') or 'not stated'}; application: {e.get('application') or 'not stated'}",
                f"- PDUFA: **{e['date_text']}** ({e['precision']}); confirmed by EDGAR: {e.get('edgar_confirmed')}",
                "- Date history:"]
        out += [f"  - {h.get('seen')}: {h.get('date_text')} ({h.get('precision')}) — {h.get('form') or h.get('kind')} {h.get('filed') or ''} {h.get('url') or ''}"
                for h in e.get("date_history", [])]
        b = e.get("pdufa_bio")
        if b:
            out.append(f"- pdufa.bio: date {b.get('date') or b.get('date_month')}, status {b.get('status')}, {b.get('url')}")
        out.append("")
    if prices:
        last = prices[-1]
        def close(i):
            try:
                return float(prices[i]["close"])
            except (IndexError, ValueError):
                return None
        c0, c20 = close(-1), close(-21)
        vol = [float(r["close"]) * float(r["volume"]) for r in prices[-20:] if r["close"] not in ("", "nan") and r["volume"] not in ("", "nan")]
        out += ["## Market", "", f"- Last close {last['date']}: {last['close']}; market value {_fmt_money(caps.get('market_cap'))}",
                "- Change over the last 20 sessions: " + (f"{(c0 / c20 - 1) * 100:+.1f}%" if c0 and c20 else "-"),
                f"- Average daily traded value (20 sessions): {_fmt_money(sum(vol) / len(vol)) if vol else '-'}",
                f"- Options snapshots: {len(list((f / 'market' / 'options').glob('*.json.gz')))} days in market/options/",
                "- Prediction markets: market/prediction_markets.csv", ""]
    fin = [r for r in read_rows(f / "sec" / "financials.csv") if r["concept"] in
           ("CashAndCashEquivalentsAtCarryingValue", "ShortTermInvestments", "NetCashProvidedByUsedInOperatingActivities")][:6]
    if fin:
        out += ["## Cash (XBRL, latest periods)", ""] + [f"- {r['concept']} {r['end']} ({r['form']}): {_fmt_money(r['value'])}" for r in fin] + [""]
    trials = read_rows(f / "trials" / "index.csv")
    out += [f"## Trials ({len(trials)})", "", "Every version is in trials/<NCT>/; key-field changes in trials/changes.md.", ""]
    out += [f"- {r['nct']} | {r['phases']} | {r['status']} | {r['title']} | versions {r['versions']}" for r in trials] + [""]
    papers = read_rows(f / "papers" / "index.csv")
    have = sum(r["status"] in science.FULL for r in papers)
    out += [f"## Papers ({len(papers)}; full text for {have})", "", "Abstract records in papers/pubmed/, full texts in papers/fulltext/ and papers/pdf/; missing ones in papers/to_download.md.", ""]
    tl = sorted(read_rows(f / "timeline.csv"), key=lambda r: r["published"] or "", reverse=True)
    out += [f"## Timeline ({len(tl)} items, newest first)", ""]
    out += [f"- {r['published']} | {r['kind']} | {r['title'][:120]} | {r['path']}" for r in tl[:300]]
    write_text(f / "pack" / "PACK.md", "\n".join(out) + "\n")
    for e in due:
        notice("Packs ready", f"{ev.describe(e)}: companies/{t}/pack/PACK.md", key=f"pack:{e['id']}:{e['date_start']}")


def to_download_all(active):
    """data_collection/to_download.md: every paper missing a PDF, by company, nearest PDUFA date first."""
    order = sorted(active.items(), key=lambda kv: min(e["date_start"] for e in kv[1]))
    out = ["# Papers to download (all companies)", "", "Save each PDF as `companies/<TICKER>/papers/pdf/<PMID>.pdf`.", ""]
    for t, evs in order:
        p = folder(t) / "papers" / "to_download.md"
        if not p.exists():
            continue
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.startswith("- [ ]")]
        if lines:
            out += [f"## {t} — PDUFA {min(e['date_start'] for e in evs)} ({len(lines)} papers)", ""] + lines + [""]
    write_text(DATA / "to_download.md", "\n".join(out) + "\n")
