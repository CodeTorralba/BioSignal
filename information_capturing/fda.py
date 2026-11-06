"""FDA sources: RSS feeds, advisory committee notices (Federal Register), Drugs@FDA and published CRLs.

Every feed or notice downloaded is kept under fda/. A match with an event is copied to the company folder. Text that
may announce a decision is queued for the agent, which confirms it with a quote; nothing here closes an event alone.
"""

import re
import urllib.parse
from datetime import timedelta

from .common import (DATA, get, get_json, html_to_text, name_pattern, notice, read_json, today, write_bytes,
                     write_json, write_text)
from .mentions import DAY

FEEDS = {k: f"https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/{k}/rss.xml"
         for k in ("press-releases", "drugs", "biologics")}
FR = "https://www.federalregister.gov/api/v1/documents.json"
OPENFDA = "https://api.fda.gov"
DECISION_WORDS = re.compile(r"approv|complete response|\bCRL\b|withdr|refus", re.I)
F = DATA / "fda"


def _seen(name):
    p = F / name
    return set(p.read_text().split("\n")) if p.exists() else set()


def _remember(name, values):
    if values:
        p = F / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write("\n".join(values) + "\n")


def event_pattern(e, company_names):
    return name_pattern([e.get("drug", "")] + e.get("aliases", []) + company_names)


def rss(pending):
    """New FDA RSS items that name a pending event; returns [(item, [events])] for the caller to file and queue."""
    seen, new_seen, out = _seen("rss/seen.txt"), [], []
    pats = [(e, name_pattern([e.get("drug", "")] + e.get("aliases", []))) for e in pending]
    for feed, url in FEEDS.items():
        body = get(url)
        if not body:
            continue
        write_bytes(F / "rss" / f"{today().isoformat()}_{feed}.xml", body)
        for raw in re.findall(r"<item>(.*?)</item>", body.decode("utf-8", "ignore"), re.S):
            link = (re.search(r"<link>(.*?)</link>", raw, re.S) or [None, ""])[1].strip()
            if not link or link in seen:
                continue
            new_seen.append(link)
            item = {"feed": feed, "link": link,
                    "title": html_to_text((re.search(r"<title>(.*?)</title>", raw, re.S) or [None, ""])[1]),
                    "description": html_to_text((re.search(r"<description>(.*?)</description>", raw, re.S) or [None, ""])[1]),
                    "date": (re.search(r"<pubDate>(.*?)</pubDate>", raw, re.S) or [None, ""])[1].strip()}
            text = f"{item['title']} {item['description']}"
            hit = [e for e, p in pats if p and p.search(text)]
            if hit:
                out.append((item, hit))
    _remember("rss/seen.txt", new_seen)
    return out


def federal_register(pending, company_names_of):
    """New FDA advisory committee notices (kept as text) and the pending events they name."""
    d = get_json(FR, {"per_page": 100, "order": "newest", "conditions[agencies][]": "food-and-drug-administration",
                      "conditions[type][]": "NOTICE", "conditions[term]": '"advisory committee"',
                      "conditions[publication_date][gte]": (today() - timedelta(days=10)).isoformat(),
                      "fields[]": ["title", "abstract", "document_number", "html_url", "raw_text_url", "publication_date"]})
    seen, new_seen, out = _seen("federal_register/seen.txt"), [], []
    for doc in (d or {}).get("results", []):
        num = doc["document_number"]
        if num in seen or "meeting" not in (doc.get("title") or "").lower():
            continue
        new_seen.append(num)
        body = get(doc["raw_text_url"]) if doc.get("raw_text_url") else None
        text = html_to_text(body) if body else (doc.get("abstract") or "")
        write_text(F / "federal_register" / f"{num}.txt", f"{doc['title']}\n{doc['html_url']}\npublished {doc['publication_date']}\n\n{text}")
        when = re.search(r"will be held (?:on|virtually on)?\s*(?:[A-Z][a-z]+day,\s*)?(" + DAY.pattern + ")", text)
        hit = [e for e in pending if (p := event_pattern(e, company_names_of(e))) and p.search(text)]
        if hit:
            out.append(({"number": num, "title": doc["title"], "url": doc["html_url"], "published": doc["publication_date"],
                         "meeting": when.group(1) if when else None, "path": f"fda/federal_register/{num}.txt"}, hit))
    _remember("federal_register/seen.txt", new_seen)
    return out


def drugsfda(folder, names):
    """Drugs@FDA records for the product names (kept as JSON); returns approval actions as text lines."""
    results = {}
    for n in sorted({re.sub(r"[™®©]", "", n).strip() for n in names}, key=len, reverse=True)[:4]:
        q = f'openfda.brand_name:"{n}"+openfda.generic_name:"{n}"+products.brand_name:"{n}"+products.active_ingredients.name:"{n}"'
        d = get_json(f"{OPENFDA}/drug/drugsfda.json?search={urllib.parse.quote(q, safe=':+')}&limit=20")
        for r in (d or {}).get("results", []):
            results[r["application_number"]] = r
    write_json(folder / "drugsfda" / f"{today().isoformat()}.json", list(results.values()))
    lines = []
    for app, r in results.items():
        brand = ", ".join(sorted({p.get("brand_name", "") for p in r.get("products", [])}))
        for s in r.get("submissions", []):
            if s.get("submission_status") == "AP":
                st = s.get("submission_status_date", "")
                lines.append((f"{st[:4]}-{st[4:6]}-{st[6:]}", f"Drugs@FDA: application {app} ({brand}), submission "
                              f"{s.get('submission_type')} {s.get('submission_number')} "
                              f"({s.get('submission_class_code_description') or s.get('submission_class_code') or ''}), "
                              f"status approved (AP) on {st[:4]}-{st[4:6]}-{st[6:]}, review priority {s.get('review_priority')}."))
    return lines


def crl(folder, company_names):
    """Published Complete Response Letters of the company (openFDA, kept as JSON); returns the letters."""
    letters = {}
    for n in company_names[:2]:
        d = get_json(f"{OPENFDA}/transparency/crl.json?search={urllib.parse.quote(f'company_name:\"{n}\"', safe=':')}&limit=100")
        for r in (d or {}).get("results", []):
            letters[r.get("file_name") or r.get("letter_date")] = r
    if letters:
        write_json(folder / "crl" / f"{today().isoformat()}.json", list(letters.values()))
    return list(letters.values())


def adcomm_from_pdufa_bio():
    """Advisory committees listed by pdufa.bio today (saved by the calendar step)."""
    raw = read_json(DATA / "calendar" / "pdufa_bio" / f"{today().isoformat()}_adcomm.json.gz", {}) or {}
    return raw.get("data", [])


def notify_adcomm(e, meeting):
    notice("Advisory committees", meeting, key=f"adcomm:{e['id']}:{meeting[:80]}")
