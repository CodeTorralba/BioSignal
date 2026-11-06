"""Offline tests of the rules that protect the calendar: dates, mentions, the agent's answers and selection."""

import json
from datetime import date, timedelta

from information_capturing import batches, companies, events, market, science
from information_capturing.common import DATA, read_rows, write_json
from information_capturing.mentions import find_mentions, parse_date

TODAY = date.today()


def test_dates_keep_their_precision():
    assert parse_date("on March 14, 2027") == {"precision": "day", "start": "2027-03-14", "end": "2027-03-14"}
    assert parse_date("in the first quarter of 2027")["precision"] == "quarter"
    assert parse_date("in the first quarter of 2027")["end"] == "2027-03-31"
    assert parse_date("1H 2027") == {"precision": "half", "start": "2027-01-01", "end": "2027-06-30"}
    assert parse_date("in January 2027") == {"precision": "month", "start": "2027-01-01", "end": "2027-01-31"}
    assert parse_date("late 2027")["start"] == "2027-07-01"
    assert parse_date("no date here") is None


def test_mentions_skip_release_dates_fees_and_past_dates():
    y = TODAY.year + 1
    text = (f"BOSTON, January 5, {y} -- (GLOBE NEWSWIRE) -- Acme Bio announced today that the FDA accepted its NDA. "
            f"The FDA assigned a PDUFA target action date of September 30, {y}. "
            f"We paid PDUFA fees of $4.3 million in {y}. "
            f"The PDUFA date of March 1, {TODAY.year - 2} was met.")
    ms = find_mentions(text, TODAY, TODAY - timedelta(days=45))
    assert [m["date"]["start"] for m in ms] == [f"{y}-09-30"]
    assert "September 30" in ms[0]["excerpt"]


def _item(excerpt, known=None):
    evs = events.load_events()
    iid = batches.queue_item("date", cik="0000000001", company="Acme Bio Inc.", tickers=["ACME"], form="8-K",
                             filed=TODAY.isoformat(), url="https://www.sec.gov/x.htm", excerpts=[excerpt], events=evs, known=known)
    batches.prepare()
    return iid, sorted((DATA / "batches" / "pending").glob("*.md"))[-1]


def _answer(md, lines):
    md.with_suffix(".out.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return batches.merge()


def test_answers_are_checked_against_the_excerpts():
    excerpt = "The FDA assigned a PDUFA target action date of September 30, 2027 for ACM-101 in gout."
    iid, md = _item(excerpt)
    good = {"known": None, "drug": "ACM-101", "other_names": [], "indication": "gout", "application": "NDA",
            "date_text": "September 30, 2027", "own": True, "quote": excerpt}
    invented = good | {"drug": "ACM-202", "quote": "The FDA assigned a PDUFA date of June 1, 2027 for ACM-202."}
    wrong_date = good | {"drug": "ACM-303", "date_text": "October 1, 2027"}
    applied, rejected = _answer(md, [{"item": iid, "events": [good, invented, wrong_date]}])
    assert (applied, rejected) == (1, 2)
    evs = list(events.load_events().values())
    assert [(e["drug"], e["date_start"], e["precision"]) for e in evs] == [("ACM-101", "2027-09-30", "day")]
    reasons = [r["reason"] for r in read_rows(DATA / "batches" / "rejected.csv")]
    assert reasons == ["quote not found in the excerpts", "date_text not found in the quote"]


def test_extension_keeps_history_and_older_news_does_not_undo_it():
    first = "The FDA assigned a PDUFA target action date of September 30, 2027 for ACM-101 in gout."
    iid, md = _item(first)
    _answer(md, [{"item": iid, "events": [{"known": None, "drug": "ACM-101", "other_names": [], "indication": "gout",
                                           "application": "NDA", "date_text": "September 30, 2027", "own": True, "quote": first}]}])
    e = next(iter(events.load_events().values()))
    ext = "The FDA extended the PDUFA target action date for ACM-101 to December 30, 2027 after a major amendment."
    iid, md = _item(ext, known=[e])
    _answer(md, [{"item": iid, "events": [{"known": "K1", "drug": "ACM-101", "other_names": [], "indication": None,
                                           "application": None, "date_text": "December 30, 2027", "own": True, "quote": ext}]}])
    e = events.load_events()[e["id"]]
    assert e["date_start"] == "2027-12-30"
    assert [h["start"] for h in e["date_history"]] == ["2027-09-30", "2027-12-30"]
    # A document filed earlier that still gives the old date must not bring it back.
    events.set_date(e, parse_date("September 30, 2027"), "September 30, 2027",
                    {"kind": "edgar", "url": "u", "filed": (TODAY - timedelta(days=60)).isoformat(), "quote": first})
    assert e["date_start"] == "2027-12-30"


def test_batches_read_in_parallel_still_give_one_event_per_application():
    evs = events.load_events()
    texts = ["On January 10, 2027 the FDA accepted the NDA for ACM-101 in gout with a PDUFA date of September 30, 2027.",
             "The FDA extended the PDUFA date for ACM-101 in gout to December 30, 2027.",
             "The FDA accepted the sNDA for ACM-101 in psoriasis with a PDUFA date of October 15, 2027."]
    ids = [batches.queue_item("date", cik="0000000001", company="Acme Bio Inc.", tickers=["ACME"], form="8-K",
                              filed=f"2027-0{i + 1}-01", url="https://www.sec.gov/x.htm", excerpts=[t], events=evs)
           for i, t in enumerate(texts)]
    batches.prepare()
    md = sorted((DATA / "batches" / "pending").glob("*.md"))[-1]
    dates = ["September 30, 2027", "December 30, 2027", "October 15, 2027"]
    lines = [{"item": i, "events": [{"known": None, "drug": "ACM-101", "other_names": [], "indication": ind,
                                     "application": None, "date_text": d, "own": True, "quote": t}]}
             for i, t, d, ind in zip(ids, texts, dates, ["gout", "gout", "plaque psoriasis"], strict=True)]
    _answer(md, list(reversed(lines)))  # answers in any order: applied by filing date
    got = sorted((e["indication"], e["date_start"], len(e["date_history"])) for e in events.load_events().values())
    assert got == [("gout", "2027-12-30", 2), ("plaque psoriasis", "2027-10-15", 1)]


def test_decision_needs_a_quote_and_none_changes_nothing():
    e = events.new_event("0000000001", "Acme Bio Inc.", "ACME", "ACM-101", [], "gout", "NDA", True,
                         parse_date("September 30, 2027"), "September 30, 2027", {"kind": "edgar", "url": "u", "filed": "2027-01-01"})
    evs = {e["id"]: e}
    events.save_events(evs)
    text = "Acme Bio today announced that the U.S. FDA has approved ACM-101 for the treatment of gout on September 29, 2027."
    iid = batches.queue_item("decision", cik="0000000001", company="Acme Bio Inc.", tickers=["ACME"], form="8-K",
                             filed="2027-09-29", url="https://www.sec.gov/y.htm", excerpts=[text], events=evs, known=[e])
    batches.prepare()
    md = sorted((DATA / "batches" / "pending").glob("*.md"))[-1]
    _answer(md, [{"item": iid, "decisions": [{"known": "K1", "outcome": "none", "date_text": None, "quote": text}]}])
    assert events.load_events()[e["id"]]["status"] == "pending"
    iid = batches.queue_item("decision", cik="0000000001", company="Acme Bio Inc.", tickers=["ACME"], form="8-K",
                             filed="2027-09-29", url="https://www.sec.gov/y.htm", excerpts=[text], events=evs, known=[e])
    batches.prepare()
    md = sorted((DATA / "batches" / "pending").glob("*.md"))[-1]
    _answer(md, [{"item": iid, "decisions": [{"known": "K1", "outcome": "approved", "date_text": "September 29, 2027", "quote": text}]}])
    got = events.load_events()[e["id"]]
    assert (got["status"], got["outcome"], got["decision"]["date"]) == ("decided", "approved", "2027-09-29")


def test_unanswered_items_go_into_a_new_batch():
    evs = events.load_events()
    ids = [batches.queue_item("date", cik="0000000001", company="Acme Bio Inc.", tickers=["ACME"], form="8-K",
                              filed=TODAY.isoformat(), url="https://www.sec.gov/x.htm", excerpts=[x], events=evs)
           for x in ("PDUFA date of September 30, 2027 for ACM-101.", "PDUFA date of October 30, 2027 for ACM-202.")]
    batches.prepare()
    md = sorted((DATA / "batches" / "pending").glob("*.md"))[-1]
    _answer(md, [{"item": ids[0], "events": []}])
    q = json.loads((DATA / "batches" / "queue.json").read_text())
    assert list(q["items"]) == [ids[1]]
    batches.prepare()
    assert len(batches.pending_summary()) == 1


def test_pdufa_bio_names_match_the_edgar_event():
    assert events.split_names("Veligrotug (VRDN-001) - (THRIVE-2)") == ["Veligrotug", "VRDN-001"]
    e = {"drug": "tebipenem pivoxil hydrobromide", "aliases": ["SPR994"]}
    assert events.same_product(e, events.split_names("Tebipenem HBr (SPR994) - (PIVOT-PO)"))
    assert not events.same_product(e, events.split_names("Olezarsen - (CORE)"))
    # Indication, application type and combination partners are not names of the product.
    assert events.split_names("ARIKAYCE (amikacin liposome inhalation suspension) - MAC lung disease (sNDA)") == ["ARIKAYCE", "amikacin liposome"]
    assert events.split_names("Mezigdomide + carfilzomib + dexamethasone - RRMM (SUCCESSOR-2)") == ["Mezigdomide"]
    assert events.split_names("Yeztugo (lenacapavir) once-weekly oral") == ["Yeztugo", "lenacapavir"]
    arikayce = {"drug": "ARIKAYCE", "aliases": ["amikacin liposome"]}
    assert not events.same_product(arikayce, events.split_names("VOXZOGO (vosoritide) - hypochondroplasia (sNDA)"))


def test_only_small_companies_inside_the_window_are_followed(monkeypatch):
    def ev_(ticker, days):
        d = (TODAY + timedelta(days=days)).isoformat()
        return events.new_event("1", f"{ticker} Inc.", ticker, f"{ticker}-1", [], "x", "NDA", True,
                                {"precision": "day", "start": d, "end": d}, d, {"kind": "edgar", "url": "u", "filed": "x"})
    evs = [ev_("SMAL", 30), ev_("BIGG", 30), ev_("LATE", 300)]
    events.save_events({e["id"]: e for e in evs})
    write_json(market.CAPS, {"SMAL": {"market_cap": 5e8}, "BIGG": {"market_cap": 9e9}, "LATE": {"market_cap": 1e8}})
    monkeypatch.setattr(market, "refresh_caps", lambda t: market.caps())
    active = companies.select()
    assert list(active) == ["SMAL"]
    assert (DATA / "companies" / "SMAL" / "company.json").exists()


def test_trial_changes_are_found_in_key_fields():
    def study(status, n):
        return {"protocolSection": {"statusModule": {"overallStatus": status}, "designModule": {"enrollmentInfo": {"count": n}}},
                "hasResults": False}
    d = science.diff(science.key_fields(study("RECRUITING", 300)), science.key_fields(study("TERMINATED", 120)))
    assert d == ["status: 'RECRUITING' -> 'TERMINATED'", "enrollment: 300 -> 120"]
