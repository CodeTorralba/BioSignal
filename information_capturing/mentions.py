"""Find PDUFA date mentions in a document and read dates of any precision (day, month, quarter, half, year)."""

import bisect
import calendar
import re
from datetime import date, timedelta

MONTH_NAMES = ("January February March April May June July August September October November December").split()
MONTHS = {m[:3].lower(): i for i, m in enumerate(MONTH_NAMES, 1)}
_M = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?"
DAY = re.compile(_M + r"\s+(\d{1,2})(?:\s?(?:st|nd|rd|th))?,?\s+(\d{4})\b")
NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b")
MONTH = re.compile(r"\b" + _M + r"\s+(?:of\s+)?(20\d\d)\b")
_ORD = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}
QUARTER = re.compile(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+(?:calendar\s+)?quarter\s+(?:of\s+)?(?:calendar\s+)?(?:year\s+)?(20\d\d)\b"
                     r"|\bQ([1-4])\s*'?(20\d\d|\d\d)\b|\b([1-4])Q\s*'?(20\d\d|\d\d)\b", re.I)
HALF = re.compile(r"\b(first|second|1st|2nd)\s+half\s+(?:of\s+)?(?:calendar\s+)?(?:year\s+)?(20\d\d)\b"
                  r"|\bH([12])\s*'?(20\d\d|\d\d)\b|\b([12])H\s*'?(20\d\d|\d\d)\b", re.I)
YEAR = re.compile(r"\b(?:(early|mid|late|end of|year-end)[\s-]+)?(20\d\d)\b", re.I)


def _year(y):
    y = int(y)
    return y + 2000 if y < 100 else y


def _end_of_month(y, m):
    return date(y, m, calendar.monthrange(y, m)[1])


def parse_date(text):
    """Reads the first date in the text and returns {"precision", "start", "end"} (ISO dates), or None.

    A day has start == end. "first quarter of 2027" is 2027-01-01..2027-03-31; "early 2027" is the first half.
    The most precise reading wins, so "March 14, 2027" is a day, never a month.
    """
    t = text or ""
    m = DAY.search(t)
    if m:
        try:
            d = date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
            return {"precision": "day", "start": d.isoformat(), "end": d.isoformat()}
        except ValueError:
            pass
    m = NUMERIC.search(t)
    if m:
        try:
            d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            return {"precision": "day", "start": d.isoformat(), "end": d.isoformat()}
        except ValueError:
            pass
    m = QUARTER.search(t)
    if m:
        q = _ORD[m.group(1).lower()] if m.group(1) else int(m.group(3) or m.group(5))
        y = _year(m.group(2) or m.group(4) or m.group(6))
        return {"precision": "quarter", "start": date(y, 3 * q - 2, 1).isoformat(), "end": _end_of_month(y, 3 * q).isoformat()}
    m = HALF.search(t)
    if m:
        h = _ORD[m.group(1).lower()] if m.group(1) else int(m.group(3) or m.group(5))
        y = _year(m.group(2) or m.group(4) or m.group(6))
        return {"precision": "half", "start": date(y, 6 * h - 5, 1).isoformat(), "end": _end_of_month(y, 6 * h).isoformat()}
    m = MONTH.search(t)
    if m:
        y, mo = int(m.group(2)), MONTHS[m.group(1)[:3].lower()]
        return {"precision": "month", "start": date(y, mo, 1).isoformat(), "end": _end_of_month(y, mo).isoformat()}
    m = YEAR.search(t)
    if m:
        y, w = int(m.group(2)), (m.group(1) or "").lower()
        if w == "early":
            return {"precision": "half", "start": date(y, 1, 1).isoformat(), "end": date(y, 6, 30).isoformat()}
        if w in ("late", "end of", "year-end"):
            return {"precision": "half", "start": date(y, 7, 1).isoformat(), "end": date(y, 12, 31).isoformat()}
        return {"precision": "year", "start": date(y, 1, 1).isoformat(), "end": date(y, 12, 31).isoformat()}
    return None


# ---------------------------------------------------------------- mentions

KEY = re.compile(r"PDUFA|Prescription Drug User Fee Act|target action date|action date|goal date", re.I)
NOT_A_DATE_KEY = re.compile(r"\s*(?:fees?|payments?|user fees?|reauthori|program|VI|VII|VIII)\b", re.I)
# A date followed by this is the date of a press release ("March 3, 2027 -- (GLOBE NEWSWIRE)"), not a PDUFA date.
RELEASE_DATE = re.compile(r"\s*(?:-{1,2}\s|/\s?PRNewswire|\((?:GLOBE NEWSWIRE|BUSINESS WIRE|ACCESSWIRE|Marketwired|PRNewswire)\))", re.I)
ANY_DATE = re.compile("|".join(p.pattern for p in (DAY, NUMERIC, QUARTER, HALF, MONTH)) + r"|\b(?:early|mid|late|end of|year-end)[\s-]+20\d\d\b", re.I)


ABBREVIATIONS = {"u.s", "inc", "corp", "ltd", "co", "no", "nos", "dr", "mr", "ms", "jan", "feb", "mar", "apr", "jun", "jul",
                 "aug", "sep", "sept", "oct", "nov", "dec", "vs", "approx", "e.g", "i.e", "st", "fig"}
SENTENCE_END = re.compile(r"\.\s+(?=[A-Z(\"])|\n\n")


def _sentence_ends(t):
    out = []
    for m in SENTENCE_END.finditer(t):
        word = re.search(r"([A-Za-z.]+)$", t[max(0, m.start() - 12):m.start()])
        if m.group(0).startswith(".") and word and word.group(1).lower().strip(".") in ABBREVIATIONS:
            continue
        out.append(m.start())
    return out


def find_mentions(text, filed, keep_after):
    """Sentences that tie a PDUFA-type key to a date, with the date read from the same sentence.

    `filed` is the filing date and `keep_after` the oldest date still of interest (a sentence whose dates are all
    older is dropped: that decision is past). Returns [{"excerpt", "date": parse_date result}], without repeats.
    """
    t = re.sub(r"[ \t]+", " ", text)
    ends = _sentence_ends(t)
    out, seen = [], set()
    for k in KEY.finditer(t):
        if NOT_A_DATE_KEY.match(t, k.end()):
            continue
        i = bisect.bisect_left(ends, k.start())
        a = max(ends[i - 1] + 1 if i else 0, k.start() - 600)
        b = min(ends[i] + 1 if i < len(ends) else len(t), k.end() + 600)
        sentence = t[a:b]
        dates = [m for m in ANY_DATE.finditer(sentence) if not RELEASE_DATE.match(sentence, m.end())]
        if len(sentence) > 900:
            near = k.start() - a
            dates = [m for m in dates if abs(m.start() - near) <= 450]
        parsed = [p for p in (parse_date(m.group(0)) for m in dates) if p
                  and date.fromisoformat(p["end"]) >= keep_after
                  and date.fromisoformat(p["start"]) <= filed + timedelta(days=900)]
        if not parsed:
            continue
        if len(sentence) > 900:  # a long risk-factor paragraph: keep the part around the key
            a, b = max(a, k.start() - 450), min(b, k.end() + 450)
            sentence = t[a:b]
        # The sentence before often names the product ("ENFLONSIA was accepted ... The FDA set a PDUFA date of ...").
        before = t[(ends[i - 2] + 1 if i >= 2 else 0):a] if i >= 1 and a == ends[i - 1] + 1 else ""
        excerpt = re.sub(r"\s+", " ", (before if len(before) <= 400 else "") + sentence).strip()
        if excerpt in seen:
            continue
        seen.add(excerpt)
        best = min(parsed, key=lambda p: ["day", "month", "quarter", "half", "year"].index(p["precision"]))
        out.append({"excerpt": excerpt, "date": best})
    return out


def earliest(event):
    """First day the decision can come: the PDUFA day, or the start of its period."""
    return date.fromisoformat(event["date_start"]) if event.get("date_start") else None
