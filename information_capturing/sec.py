"""SEC EDGAR: full-text search, company filings, filing documents and XBRL facts."""

import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from .common import DATA, SourceError, get, get_json, html_to_text, read_json, write_bytes, write_json, write_text

EFTS = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
THREADS = 8  # documents take ~3 s to arrive; several at once, never more than 6 requests started per second


def efts(query, start, end, forms):
    """Every hit of a full-text search, split into 30-day windows (one search returns at most 10,000)."""
    hits, d0 = [], start
    while d0 <= end:
        d1 = min(end, d0 + timedelta(days=29))
        n = 0
        while True:
            params = {"q": query, "forms": forms, "dateRange": "custom", "startdt": d0.isoformat(),
                      "enddt": d1.isoformat(), "from": n}
            for i in range(6):  # EFTS sometimes answers 200 with {"message": "Internal server error"}
                data = get_json(EFTS, params) or {}
                if "hits" in data:
                    break
                time.sleep(2 ** i)
            else:
                raise SourceError(f"EFTS does not answer: {query} {d0}..{d1}")
            page = data["hits"]["hits"]
            for h in page:
                s = h["_source"]
                adsh, file = h["_id"].split(":", 1)
                hits.append({"id": h["_id"], "adsh": adsh, "file": file, "cik": s["ciks"][0],
                             "name": (s.get("display_names") or [""])[0], "form": s.get("form"),
                             "file_type": s.get("file_type"), "filed": s["file_date"]})
            n += len(page)
            if not page or n >= min(data["hits"]["total"]["value"], 10000):
                break
        d0 = d1 + timedelta(days=1)
    return hits


def doc_url(cik, adsh, file):
    return f"{ARCHIVES}/{int(cik)}/{adsh.replace('-', '')}/{file}"


def tickers():
    """CIK (10 digits) -> {"tickers": [...], "name"}; SEC file refreshed at most once a week."""
    p = DATA / "sec" / "company_tickers.json"
    cache = read_json(p)
    if not cache or cache.get("fetched", "") < (date.today() - timedelta(days=7)).isoformat():
        raw = get_json("https://www.sec.gov/files/company_tickers.json")
        out = {}
        for r in raw.values():
            c = out.setdefault(str(r["cik_str"]).zfill(10), {"tickers": [], "name": r["title"]})
            c["tickers"].append(r["ticker"])
        cache = {"fetched": date.today().isoformat(), "by_cik": out}
        write_json(p, cache)
    return cache["by_cik"]


def cik_of_ticker(ticker):
    t = (ticker or "").upper()
    return next((cik for cik, c in tickers().items() if t in c["tickers"]), None)


def submissions(cik):
    """Company record and its recent filings (newest first) as a list of dicts."""
    d = get_json(f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json")
    if not d:
        raise SourceError(f"no submissions for CIK {cik}")
    r = d["filings"]["recent"]
    rows = [{k: r[k][i] for k in r} for i in range(len(r["accessionNumber"]))]
    return d, rows


def filing_documents(cik, accession):
    """Documents of a filing from its index page: [{"seq", "description", "file", "type", "size"}]."""
    body = get(f"{ARCHIVES}/{int(cik)}/{accession.replace('-', '')}/{accession}-index.htm")
    if not body:
        return []
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body.decode("utf-8", "ignore"), re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
        link = re.search(r'href="([^"]+)"', row)
        if len(cells) < 5 or not link:
            continue
        clean = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in cells]
        name = link.group(1).rsplit("/", 1)[-1]  # also for inline XBRL links (/ix?doc=/Archives/...)
        out.append({"seq": clean[0], "description": clean[1], "file": name, "type": clean[3], "size": clean[4]})
    return out


# Exhibits worth keeping: press releases and presentations (EX-99). Certifications, XBRL and graphics are not.
def wanted(doc, form):
    t = (doc["type"] or "").upper()
    if not doc["file"].lower().endswith((".htm", ".html", ".txt", ".pdf")):
        return False
    return t == form.upper() or t.split("/")[0] == form.upper().split("/")[0] or t.startswith("EX-99")


def download_filing(cik, accession, form, folder):
    """Downloads the main document and the EX-99 exhibits of a filing into `folder`, each with a .txt copy.

    Returns [(file name, type, text)]. Files already there are not downloaded again.
    """
    docs = [d for d in filing_documents(cik, accession) if wanted(d, form)]
    write_json(folder / "index.json", {"cik": cik, "accession": accession, "form": form,
                                        "documents": docs, "url": f"{ARCHIVES}/{int(cik)}/{accession.replace('-', '')}/"})

    def one(d):
        p = folder / d["file"]
        if not p.exists():
            body = get(doc_url(cik, accession, d["file"]))
            if body is None:
                return None
            write_bytes(p, body)
        if p.suffix.lower() == ".pdf":
            return (d["file"], d["type"], "")
        txt = p.with_name(p.name + ".txt")
        if not txt.exists():
            write_text(txt, html_to_text(p.read_bytes()) if p.suffix.lower() != ".txt" else p.read_text(errors="ignore"))
        return (d["file"], d["type"], txt.read_text(encoding="utf-8"))

    with ThreadPoolExecutor(THREADS) as pool:
        return [r for r in pool.map(one, docs) if r]


def download_many(jobs):
    """Runs (cik, accession, form, folder) downloads in parallel; returns {accession: [(file, type, text)] or None}.

    None means the download failed and should be tried again on the next run.
    """
    def one(j):
        try:
            return j[1], download_filing(*j)
        except SourceError as e:
            print(f"  ! {j[1]}: {e}", flush=True)
            return j[1], None
    with ThreadPoolExecutor(3) as pool:  # each filing also downloads its documents in parallel
        return dict(pool.map(one, jobs))


def company_facts(cik):
    return get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).zfill(10)}.json")


# Concepts summed or shown for cash and spending. Cash is spread over several concepts (Savara: cash 41.8M,
# short-term investments 131M), so they are kept separate and not added up here.
FACTS = ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
         "ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
         "NetIncomeLoss", "ResearchAndDevelopmentExpense", "GeneralAndAdministrativeExpense",
         "NetCashProvidedByUsedInOperatingActivities", "Revenues", "LongTermDebt"]


def facts_rows(facts):
    """One row per (concept, period end, form) from companyfacts, in USD, newest first."""
    rows = []
    gaap = (facts or {}).get("facts", {})
    for ns in ("us-gaap", "ifrs-full"):
        for concept in FACTS:
            for unit, vals in gaap.get(ns, {}).get(concept, {}).get("units", {}).items():
                for v in vals:
                    rows.append({"concept": concept, "unit": unit, "value": v.get("val"), "start": v.get("start", ""),
                                 "end": v.get("end"), "frame": v.get("frame", ""), "form": v.get("form"),
                                 "filed": v.get("filed"), "accession": v.get("accn")})
    shares = gaap.get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    for v in shares:
        rows.append({"concept": "EntityCommonStockSharesOutstanding", "unit": "shares", "value": v.get("val"),
                     "start": "", "end": v.get("end"), "frame": v.get("frame", ""), "form": v.get("form"),
                     "filed": v.get("filed"), "accession": v.get("accn")})
    rows.sort(key=lambda r: (r["end"] or "", r["filed"] or ""), reverse=True)
    return rows

