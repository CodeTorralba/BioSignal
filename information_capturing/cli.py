"""Command line: `uv run capture <command>`. The schedule is in information_capturing/SCHEDULE.md."""

import argparse
import sys

from . import batches, companies, fda, market
from . import events as ev
from .common import DATA, RunLock, now, read_json, render_notices, run_step, today, write_text

# ---------------------------------------------------------------- FDA feeds joined to events


def fda_feeds(active):
    events = ev.load_events()
    pending = [e for e in events.values() if e["status"] == "pending"]
    for item, hits in fda.rss(pending):
        text = f"{item['title']}. {item['description']}"
        for e in hits:
            if e.get("tracked"):
                companies.timeline(companies.folder(e["ticker"]), [{
                    "published": item["date"], "kind": f"FDA {item['feed']}", "title": item["title"],
                    "path": f"../../fda/rss/{today().isoformat()}_{item['feed']}.xml", "url": item["link"]}])
        if fda.DECISION_WORDS.search(text):
            batches.queue_item("decision", cik=hits[0].get("cik"), company=hits[0].get("company"),
                               tickers=sorted({e.get("ticker") or "" for e in hits}), form=f"FDA RSS {item['feed']}",
                               filed=today().isoformat(), url=item["link"], excerpts=[text[:1500]], events=events, known=hits)


def federal_register(active):
    events = ev.load_events()
    pending = [e for e in events.values() if e["status"] == "pending"]
    for doc, hits in fda.federal_register(pending, lambda e: companies.company_names(e.get("company"))):
        for e in hits:
            if not e.get("tracked"):
                continue
            f = companies.folder(e["ticker"])
            src = DATA / doc["path"]
            write_text(f / "fda" / "federal_register" / src.name, src.read_text(encoding="utf-8"))
            companies.timeline(f, [{"published": doc["published"], "kind": "Federal Register", "title": doc["title"],
                                    "path": f"fda/federal_register/{src.name}", "url": doc["url"]}])
            fda.notify_adcomm(e, f"{ev.describe(e)}: {doc['title']} — meeting {doc['meeting'] or 'date in the notice'} — {doc['url']}")


def adcomm_pdufa_bio(active):
    for r in fda.adcomm_from_pdufa_bio():
        t = (r.get("ticker") or "").upper()
        if t in active and r.get("status") != "Held":
            e = active[t][0]
            fda.notify_adcomm(e, f"{t}: pdufa.bio lists an advisory committee on {r.get('date') or r.get('date_month')} "
                                 f"for {r.get('name')} ({r.get('url')})")


# ---------------------------------------------------------------- commands


def collect_new(active):
    """First collection for companies that have no folder content yet (after `merge` added events)."""
    events = ev.load_events()
    for t, evs in active.items():
        if not (companies.folder(t) / "sec" / "filings.csv").exists():
            print(f"- new company {t}", flush=True)
            companies.daily(t, evs, events, new=True)


def finish():
    run_step("prepare batches", batches.prepare)
    waiting = batches.pending_summary()
    md = render_notices()
    print("")
    if waiting:
        print(f"AGENT: {len(waiting)} batch(es) to read, following information_capturing/instructions/extraction.md:")
        for p in waiting:
            print(f"  {p}  ->  {p.with_suffix('.out.jsonl')}")
        print("AGENT: then run `uv run capture merge`.")
    else:
        print("AGENT: no batches to read.")
    print(f"NOTICES: {md}" if md else "NOTICES: none")


def daily(args):
    with RunLock():
        print(f"daily {now()}", flush=True)
        run_step("merge agent answers", batches.merge)
        run_step("pdufa.bio", ev.pdufa_bio)  # first, so the agent sees pdufa.bio's events as known
        run_step("EDGAR discovery", ev.discover, 3)
        active = run_step("select companies", companies.select) or {}
        run_step("XBI prices", market.prices, DATA / "market" / "XBI.csv", "XBI")
        events = ev.load_events()
        for t, evs in sorted(active.items()):
            new = not (companies.folder(t) / "sec" / "filings.csv").exists()
            print(f"- {t}{' (new)' if new else ''}", flush=True)
            companies.daily(t, evs, events, new)
        run_step("FDA RSS", fda_feeds, active)
        run_step("Federal Register", federal_register, active)
        run_step("pdufa.bio advisory committees", adcomm_pdufa_bio, active)
        for t, evs in active.items():
            run_step(f"{t}: pack", companies.pack, t, evs)
        run_step("close finished", companies.close_finished, active)
        run_step("papers to download", companies.to_download_all, active)
        finish()


def merge(args):
    with RunLock():
        applied, rejected = batches.merge()
        print(f"merge: {applied} answers applied, {rejected} parts rejected (see batches/rejected.csv)")
        active = run_step("select companies", companies.select) or {}
        collect_new(active)
        for t, evs in active.items():
            run_step(f"{t}: pack", companies.pack, t, evs)
        run_step("papers to download", companies.to_download_all, active)
        finish()


def weekly(args):
    with RunLock():
        print(f"weekly {now()}", flush=True)
        events = ev.load_events()
        tickers = {e["ticker"] for e in events.values() if e.get("ticker") and e["status"] == "pending"}
        run_step("market values", market.refresh_caps, tickers)
        active = run_step("select companies", companies.select) or {}
        names = {t: companies.drug_names(evs) + companies.company_names(evs[0].get("company")) for t, evs in active.items()}
        run_step("Kalshi series", market.kalshi_discover, names)
        for t, evs in sorted(active.items()):
            print(f"- {t}", flush=True)
            companies.weekly(t, evs)
        run_step("papers to download", companies.to_download_all, active)
        finish()


def monthly(args):
    with RunLock():
        print(f"monthly {now()}", flush=True)
        # Safety net for days missed or documents indexed late by EDGAR full-text search.
        run_step("EDGAR discovery (45 days)", ev.discover, 45)
        finish()


def init(args):
    with RunLock():
        print(f"init {now()}", flush=True)
        run_step("pdufa.bio", ev.pdufa_bio)
        # Acceptance press releases set the date ~10 months ahead; every company restates its dates each quarter.
        run_step("EDGAR discovery: press releases, 300 days", ev.discover, 300, ev.FORMS_RELEASES)
        run_step("EDGAR discovery: all forms, 120 days", ev.discover, 120, ev.FORMS_ALL)
        finish()


def status(args):
    st = read_json(DATA / "status.json", {})
    events = ev.load_events()
    pending = [e for e in events.values() if e["status"] == "pending"]
    tracked = sorted({e["ticker"] for e in events.values() if e.get("tracked")})
    print(f"data: {DATA}")
    print(f"events: {len(events)} ({len(pending)} pending); companies followed: {len(tracked)} {' '.join(tracked)}")
    print(f"batches waiting for the agent: {len(batches.pending_summary())}")
    failing = {k: v for k, v in st.items() if v.get("error")}
    for k, v in sorted(st.items()):
        flag = "FAIL" if v.get("error") else "ok  "
        print(f"  {flag} {k}: last ok {v.get('last_ok') or '-'}" + (f" | {v['error'][:120]}" if v.get("error") else ""))
    if failing:
        sys.exit(1)


def company(args):
    with RunLock():
        active = companies.select()
        t = args.ticker.upper()
        if t not in active:
            sys.exit(f"{t} is not followed (not pending, outside the window, or market value >= $2B)")
        companies.daily(t, active[t], ev.load_events(), new=True)
        companies.pack(t, active[t])
        finish()


def main():
    p = argparse.ArgumentParser(prog="capture", description="BioSignal information capturing")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in [("daily", daily, "after the US close: filings, calendar, prices, options, feeds, packs"),
                            ("weekly", weekly, "trials, papers, Drugs@FDA, CRLs, Kalshi series, market values"),
                            ("monthly", monthly, "EDGAR safety-net search over 45 days"),
                            ("init", init, "first install: build the calendar from EDGAR and pdufa.bio"),
                            ("merge", merge, "apply the agent's answers and open folders for new companies"),
                            ("status", status, "state of every step; exit code 1 if one is failing")]:
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("company", help="collect everything for one followed company now")
    sp.add_argument("ticker")
    sp.set_defaults(fn=company)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
