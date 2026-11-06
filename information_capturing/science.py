"""Science: ClinicalTrials.gov records (every version kept) and PubMed papers with their full text when it is open.

ClinicalTrials.gov does not give its change history through the API, so a copy is saved each time a trial's
`lastUpdatePostDate` changes and the key fields are compared with the previous copy. Papers without an open full
text are listed in papers/to_download.md so the user can add the PDF by hand.
"""

import re
import xml.etree.ElementTree as ET
from datetime import timedelta

from .common import (append_rows, contact_email, get, get_json, name_pattern, read_json, read_rows, today, write_bytes,
                     write_json, write_rows, write_text)

CT = "https://clinicaltrials.gov/api/v2/studies"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TRIAL_FIELDS = ["nct", "title", "phases", "status", "sponsor", "last_update", "matched_by", "first_seen", "versions"]
PAPER_FIELDS = ["pmid", "doi", "pmcid", "title", "journal", "pub_date", "pub_types", "matched_name", "status",
                "full_text", "oa_url", "checked", "first_seen"]
FULL = {"full_text_pmc", "full_text_pdf", "pdf_from_user"}
MAX_HITS = 300  # a name with more PubMed hits than this (an old generic) is narrowed with the indication


def _dig(d, *path):
    for k in path:
        d = (d or {}).get(k) if isinstance(d, dict) else None
    return d


def key_fields(study):
    """The fields whose change matters before a decision: status, size, dates, primary endpoint, results."""
    ps = study.get("protocolSection", {})
    return {
        "status": _dig(ps, "statusModule", "overallStatus"),
        "why_stopped": _dig(ps, "statusModule", "whyStopped"),
        "enrollment": _dig(ps, "designModule", "enrollmentInfo", "count"),
        "enrollment_type": _dig(ps, "designModule", "enrollmentInfo", "type"),
        "primary_completion": _dig(ps, "statusModule", "primaryCompletionDateStruct", "date"),
        "completion": _dig(ps, "statusModule", "completionDateStruct", "date"),
        "primary_outcomes": [o.get("measure") for o in _dig(ps, "outcomesModule", "primaryOutcomes") or []],
        "phases": _dig(ps, "designModule", "phases"),
        "has_results": study.get("hasResults"),
    }


def diff(old, new):
    return [f"{k}: {old.get(k)!r} -> {new.get(k)!r}" for k in new if old.get(k) != new.get(k)]


def _search(params):
    out, token = [], None
    fields = "NCTId,LastUpdatePostDate,BriefTitle,OfficialTitle,InterventionName,InterventionOtherName"
    while True:
        d = get_json(CT, params | {"pageSize": 100, "fields": fields} | ({"pageToken": token} if token else {})) or {}
        out += d.get("studies", [])
        token = d.get("nextPageToken")
        if not token or len(out) >= 500:
            return out


def trials(folder, sponsors, drug_names):
    """Updates trials/ for a company; returns the list of changes in key fields of trials already known."""
    pat = name_pattern(drug_names)
    found = {}
    for s in sponsors[:2]:
        for st in _search({"query.spons": s}):
            found.setdefault(_dig(st, "protocolSection", "identificationModule", "nctId"), (st, f"sponsor {s}"))
    for n in drug_names:
        for st in _search({"query.intr": n}):
            ps = st.get("protocolSection", {})
            text = " ".join([str(_dig(ps, "identificationModule", "briefTitle")), str(_dig(ps, "identificationModule", "officialTitle")),
                             str(_dig(ps, "armsInterventionsModule"))])
            if pat and pat.search(text):  # the registry also returns synonyms (molgramostim -> sargramostim)
                found.setdefault(_dig(ps, "identificationModule", "nctId"), (st, f"drug {n}"))
    index = {r["nct"]: r for r in read_rows(folder / "index.csv")}
    changes = []
    for nct, (st, by) in found.items():
        if not nct:
            continue
        upd = _dig(st, "protocolSection", "statusModule", "lastUpdatePostDateStruct", "date") or "unknown"
        prev = index.get(nct)
        if prev and prev["last_update"] == upd:
            continue
        full = get_json(f"{CT}/{nct}")
        if not full:
            continue
        write_json(folder / nct / f"{upd}.json", full)
        if prev:
            older = sorted((folder / nct).glob("*.json"))
            before = read_json(older[-2]) if len(older) >= 2 else None
            d = diff(key_fields(before), key_fields(full)) if before else []
            if d:
                changes.append((nct, upd, d))
        ps = full.get("protocolSection", {})
        index[nct] = {"nct": nct, "title": _dig(ps, "identificationModule", "briefTitle"),
                      "phases": ",".join(_dig(ps, "designModule", "phases") or []),
                      "status": _dig(ps, "statusModule", "overallStatus"),
                      "sponsor": _dig(ps, "sponsorCollaboratorsModule", "leadSponsor", "name"), "last_update": upd,
                      "matched_by": by, "first_seen": prev["first_seen"] if prev else today().isoformat(),
                      "versions": len(list((folder / nct).glob("*.json")))}
    write_rows(folder / "index.csv", sorted(index.values(), key=lambda r: r["nct"]), TRIAL_FIELDS)
    if changes:
        log = folder / "changes.md"
        old = log.read_text(encoding="utf-8") if log.exists() else "# Changes in key trial fields\n\n"
        new = "".join(f"## {nct} — registry update {upd} (seen {today().isoformat()})\n\n" + "".join(f"- {x}\n" for x in d) + "\n"
                      for nct, upd, d in changes)
        write_text(log, old + new)
    return changes


# ---------------------------------------------------------------- papers

GENERIC = {"treatment", "patients", "adults", "adult", "disease", "chronic", "severe", "advanced", "with", "and", "the",
           "associated", "syndrome", "disorder", "therapy", "pediatric", "years", "older", "moderate"}


def _esearch(term, retmax):
    d = get_json(f"{EUTILS}/esearch.fcgi", {"db": "pubmed", "term": term, "retmax": retmax, "retmode": "json",
                                             "sort": "pub_date", "tool": "biosignal"}) or {}
    r = d.get("esearchresult", {})
    return int(r.get("count", 0)), r.get("idlist", [])


def _articles(ids):
    """{pmid: (xml bytes, fields)} from PubMed efetch."""
    out = {}
    for i in range(0, len(ids), 100):
        body = get(f"{EUTILS}/efetch.fcgi", {"db": "pubmed", "id": ",".join(ids[i:i + 100]), "retmode": "xml", "tool": "biosignal"})
        if not body:
            continue
        for art in ET.fromstring(body).iter("PubmedArticle"):
            pmid = art.findtext(".//PMID")
            aid = {x.get("IdType"): x.text for x in art.findall(".//PubmedData/ArticleIdList/ArticleId")}
            title = art.find(".//ArticleTitle")
            pd = art.find(".//JournalIssue/PubDate")
            when = " ".join(filter(None, [pd.findtext("Year"), pd.findtext("Month"), pd.findtext("Day")])) if pd is not None else ""
            ad = art.find(".//ArticleDate")
            if ad is not None:
                when = f"{when} (online {ad.findtext('Year')}-{ad.findtext('Month')}-{ad.findtext('Day')})".strip()
            out[pmid] = (ET.tostring(art, encoding="utf-8"), {
                "pmid": pmid, "doi": aid.get("doi") or "", "pmcid": aid.get("pmc") or "",
                "title": "".join(title.itertext()).strip() if title is not None else "",
                "journal": art.findtext(".//Journal/Title") or "", "pub_date": when or (pd.findtext("MedlineDate") if pd is not None else ""),
                "pub_types": "; ".join(x.text or "" for x in art.findall(".//PublicationType"))})
    return out


def _full_text(folder, row):
    """Tries PubMed Central, then Unpaywall. Sets status: full_text_pmc, full_text_pdf, open_access_link, paywalled."""
    row["checked"] = today().isoformat()
    if row["pmcid"]:
        body = get(f"{EUTILS}/efetch.fcgi", {"db": "pmc", "id": row["pmcid"], "tool": "biosignal"})
        if body and b"<body" in body:
            write_bytes(folder / "fulltext" / f"{row['pmid']}.pmc.xml", body)
            row.update(status="full_text_pmc", full_text=f"fulltext/{row['pmid']}.pmc.xml")
            return
    email = contact_email()
    if row["doi"] and email:
        d = get_json(f"https://api.unpaywall.org/v2/{row['doi']}", {"email": email}) or {}
        loc = d.get("best_oa_location") or {}
        url = loc.get("url_for_pdf") or loc.get("url")
        if loc.get("url_for_pdf"):
            try:
                body = get(loc["url_for_pdf"], tries=2)
            except Exception:  # noqa: BLE001 - publishers often block scripts; the link is then given to the user
                body = None
            if body and body[:4] == b"%PDF":
                write_bytes(folder / "fulltext" / f"{row['pmid']}.pdf", body)
                row.update(status="full_text_pdf", full_text=f"fulltext/{row['pmid']}.pdf", oa_url=url)
                return
        if d.get("is_oa") and url:
            row.update(status="open_access_link", oa_url=url)
            return
    row["status"] = "paywalled" if row["doi"] else "no_link"


def _search_terms(name, indication):
    count, _ = _esearch(f'"{name}"[tiab]', 0)
    if count <= MAX_HITS:
        return f'"{name}"[tiab]', count
    words = sorted({w for w in re.findall(r"[A-Za-z][A-Za-z-]{4,}", indication or "") if w.lower() not in GENERIC}, key=len, reverse=True)[:2]
    if not words:
        return None, count
    term = f'"{name}"[tiab] AND ' + " AND ".join(f"{w}[tiab]" for w in words)
    n, _ = _esearch(term, 0)
    return (term, n) if n <= MAX_HITS else (None, n)


def papers(folder, drug_names, indication):
    """Updates papers/ for a company; returns the new rows that still need a PDF from the user."""
    index = {r["pmid"]: r for r in read_rows(folder / "index.csv")}
    log = []
    new_ids = {}
    for n in sorted({n for n in drug_names if len(n) >= 4}):
        term, count = _search_terms(n, indication)
        log.append({"date": today().isoformat(), "name": n, "term": term or "", "hits": count, "used": bool(term)})
        if not term:
            continue
        _, ids = _esearch(term, MAX_HITS)
        for i in ids:
            if i not in index:
                new_ids.setdefault(i, n)
    append_rows(folder / "search_log.csv", log, ["date", "name", "term", "hits", "used"])
    fresh = []
    for pmid, (xml, row) in _articles(list(new_ids)).items():
        write_bytes(folder / "pubmed" / f"{pmid}.xml", xml)
        row.update(matched_name=new_ids.get(pmid, ""), first_seen=today().isoformat(), status="", full_text="", oa_url="", checked="")
        _full_text(folder, row)
        index[pmid] = row
        fresh.append(row)
    stale = (today() - timedelta(days=30)).isoformat()
    for row in index.values():
        if (folder / "pdf" / f"{row['pmid']}.pdf").exists() and row["status"] not in FULL:
            row.update(status="pdf_from_user", full_text=f"pdf/{row['pmid']}.pdf")
        elif row["status"] in ("paywalled", "open_access_link") and (row.get("checked") or "") < stale:
            _full_text(folder, row)  # embargoes end: look again once a month
    rows = sorted(index.values(), key=lambda r: r["pmid"], reverse=True)
    write_rows(folder / "index.csv", rows, PAPER_FIELDS)
    (folder / "pdf").mkdir(parents=True, exist_ok=True)
    write_to_download(folder, rows)
    return [r for r in fresh if r["status"] not in FULL]


def write_to_download(folder, rows):
    need = [r for r in rows if r["status"] not in FULL]
    out = ["# Papers to download", "",
           f"{len(need)} papers without a full text we could download. Save each PDF as `papers/pdf/<PMID>.pdf` "
           "(for example `papers/pdf/41742124.pdf`); the next run picks it up.", ""]
    for r in need:
        link = f"https://doi.org/{r['doi']}" if r["doi"] else f"https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/"
        extra = f" — open-access copy (download failed): {r['oa_url']}" if r["status"] == "open_access_link" else ""
        out.append(f"- [ ] **{r['pmid']}** {r['title']} — *{r['journal']}*, {r['pub_date']} — {link}{extra}")
    write_text(folder / "to_download.md", "\n".join(out) + "\n")
