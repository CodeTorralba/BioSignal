# Collection schedule

What is collected, how often, and why. Times are UTC; the daily run is after the US market close all year
(16:00 New York is 21:00 UTC in winter and 20:00 UTC in summer).

| Job | When | Command |
|---|---|---|
| Daily | Monday to Friday, 22:30 UTC | `uv run capture daily` |
| Weekly | Saturday, 10:00 UTC | `uv run capture weekly` |
| Monthly | Day 1, 12:00 UTC | `uv run capture monthly` |
| After any job that prints `AGENT: … batch(es) to read` | Right after the job | the agent reads the batches, then `uv run capture merge` |
| First install, once | — | `uv run capture init`, read the batches, `uv run capture merge` |

## Daily

| Source | What | Why daily |
|---|---|---|
| SEC EDGAR full-text search | New filings of the last 3 days (8-K, 6-K, 10-Q, 10-K, 20-F, 40-F, 424B, S-1, F-1) that say "PDUFA", "target action date" or "goal date". Sentences with a date go to the agent | New events and date changes appear first in filings. The 3-day window covers weekends and late indexing |
| pdufa.bio `/pdufa` and `/adcomm` | Full copy, kept every day | Second source to compare with EDGAR. The free plan gives no date history, so the daily copies build it |
| SEC filings of each followed company | Every filing is listed; the main document and press-release exhibits (EX-99) of 8-K, 6-K, 10-Q, 10-K, 20-F, 40-F, 424B, S-1, F-1 are downloaded in full | Press releases, offerings and decisions are news of the day |
| Prices (yfinance) | Daily bar of each followed company and of XBI (biotech index) | Run-up, liquidity and the reaction to the decision |
| Options (yfinance) | Full chain, every expiration | Free options history cannot be recovered later |
| Kalshi and Polymarket | Prices of the linked contracts | The probability the market gives; it moves near the date |
| FDA RSS | Press releases, drugs and biologics feeds | The FDA sometimes announces approvals itself (also CBER products) |
| Federal Register | FDA advisory committee meeting notices | Published at least 15 days before each meeting |
| Pack | `pack/PACK.md` from 7 days before the date until the decision | Our analysis starts a few days before the date |

## Weekly

| Source | What | Why weekly |
|---|---|---|
| ClinicalTrials.gov | Trials by sponsor and by drug name; a new copy each time the record changes, with changes in key fields (status, size, dates, primary endpoint, results) | Records change rarely; the registry gives no history, so the copies are the history |
| PubMed, PubMed Central, Unpaywall | New papers naming the drug; open full texts (PMC XML or PDF); the rest in `papers/to_download.md`; paywalled ones checked again after 30 days | Papers appear slowly; embargoes end |
| Drugs@FDA (openFDA) | Records of the drug's applications | Updated with a delay of about a week; it has no CBER products |
| openFDA CRL database | Published Complete Response Letters of the company | Updated irregularly; useful to read the reasons |
| Market value | yfinance for every pending event | The $2B limit decides which companies are followed |
| Kalshi series list | All series (20 MB, kept), linked by company or drug name | New contracts appear every few weeks |

## Monthly

| Source | What | Why monthly |
|---|---|---|
| SEC EDGAR full-text search | The same search over 45 days | Safety net for missed days and documents indexed late |

## When something happens

| Event | What is done |
|---|---|
| A company starts being followed (pending event, decision in the next 6 months, market value under $2B) | Filings of the last 24 months, 2 years of prices, trials, papers, Drugs@FDA and CRLs, at once |
| New 10-Q, 10-K, 20-F or 40-F | XBRL financial facts downloaded again (`sec/financials.csv`) |
| 7 days before the PDUFA date | `pack/PACK.md` written, then rewritten every day until the decision |
| Decision seen | Prices and options for 10 more trading sessions, then the company is closed |
| 45 days after the date with no decision seen | No longer followed; a notice asks to check it by hand |
