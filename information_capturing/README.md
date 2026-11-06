# information_capturing

Module 1 of BioSignal. It finds the companies waiting for an FDA decision, and for each **small** one (market value
under $2B, decision expected in the next 6 months) it keeps a folder with everything public: SEC filings in full,
prices, options, prediction markets, clinical trials with every version, and papers with their full text. Seven
days before the date it writes a pack for our analysis. It does not analyse or predict anything.

An agent runs it on a schedule ([AGENT.md](AGENT.md)); the frequencies and their reasons are in
[SCHEDULE.md](SCHEDULE.md).

## Setup

```bash
uv sync
cp .env.example .env    # set BIOSIGNAL_CONTACT (name and email; the SEC requires it)
uv run capture init     # first time: builds the calendar
# the agent reads the batches it lists, then:
uv run capture merge
```

| Command | What it does |
|---|---|
| `capture daily` | Calendar (EDGAR + pdufa.bio), company filings, prices, options, prediction markets, FDA feeds, packs |
| `capture weekly` | Trials, papers, Drugs@FDA, CRLs, market values, Kalshi series |
| `capture monthly` | EDGAR search over 45 days, as a safety net |
| `capture init` | First calendar: 300 days of press releases and 120 days of all forms |
| `capture merge` | Applies the agent's answers; opens folders for new companies |
| `capture company <TICKER>` | Collects everything for one followed company now |
| `capture status` | State of every step |

Tests (offline): `uv run pytest`.

## How the calendar is built

1. **EDGAR** full-text search finds filings that say "PDUFA", "target action date" or "goal date". The sentences
   with a date (day, month, quarter or half) are kept. Every document downloaded is kept in `calendar/docs/`.
2. A sentence that gives the exact day of a known event is attached to it. The rest go to the **agent** in
   batches ([instructions/extraction.md](instructions/extraction.md)): drug, indication, application, date and a
   literal quote. The script rejects any answer whose quote is not in the text or whose date is not in the quote.
3. **pdufa.bio** is copied every day. Events it has and EDGAR does not are added (marked as not confirmed by
   EDGAR). `calendar/pdufa_bio_comparison.md` lists what is only in one source, different dates, and outcomes
   pdufa.bio has that the filings do not show yet.
4. A date change keeps the earlier date in `date_history`. An older document that repeats an earlier date never
   undoes a newer one. A quarter never becomes an invented day.
5. **Decisions** are read by the agent from new 8-K/6-K press releases, FDA RSS items, Drugs@FDA and the CRL
   database. Nothing is marked approved without a quote.

## Data folder

Everything goes to `data_collection/` (ignored by git; another path with `BIOSIGNAL_DATA`). Documents are kept in
full, as downloaded, with a `.txt` copy of each HTML filing.

```
data_collection/
  calendar/        events.json, calendar.csv, pdufa_bio_comparison.md, pdufa_bio/<date>.json.gz, docs/ (EDGAR hits)
  companies/<TICKER>/
    company.json, events.json
    timeline.csv              every item captured: published date, capture time, kind, title, path, link
    sec/filings.csv           every filing of the company (all forms)
    sec/<date>_<form>_<accession>/   main document and EX-99 exhibits, original + .txt
    sec/financials.csv        XBRL facts (cash, investments, spending, shares); sec/companyfacts/ raw
    market/prices.csv         daily bars; market/options/<date>.json.gz full chain; market/prediction_markets.csv
    trials/index.csv          trials by sponsor and drug; trials/<NCT>/<registry update>.json every version
    trials/changes.md         changes in status, size, dates, primary endpoint, results
    papers/index.csv          PubMed papers; papers/pubmed/<PMID>.xml; papers/fulltext/ open full texts
    papers/to_download.md     papers without open full text: save the PDF as papers/pdf/<PMID>.pdf
    fda/                      Drugs@FDA, CRLs, advisory committee notices
    pack/PACK.md              from 7 days before the date: map of everything above
  market/XBI.csv, market/kalshi/   biotech index; Kalshi series list
  fda/                        FDA RSS copies, Federal Register notices
  batches/                    work for the agent: pending/, done/, rejected.csv
  notices/<date>.md           what the user is told
  to_download.md              all papers waiting for a PDF, nearest PDUFA date first
  status.json, logs/          state and errors of every step
```

## Known gaps

- Press releases come from SEC filings (8-K/6-K) and FDA feeds. Releases only on newswires or company websites,
  and news, are not collected.
- Conference abstracts and posters come only if the company files them with an 8-K. Preprints are not collected.
- Drugs@FDA has no CBER products (cell and gene therapies, vaccines); for those the company filing and the FDA
  biologics feed are the sources.
- The FDA advisory committee calendar page needs a browser; the Federal Register notices and pdufa.bio are used.
- yfinance options of small companies have very wide spreads and zero quotes outside market hours. The market
  value of ADRs may be wrong in yfinance.
- Insider trades and short interest are not collected (Form 4 filings are listed in `sec/filings.csv`).
