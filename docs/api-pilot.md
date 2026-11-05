# API Pilot Study

5 Nov 2026. Real calls from the Mac, without paid keys. Complements the [technical reference](reference.md): this is what the APIs really return and what to keep in mind when implementing them.

## Summary

| Source | Responds? | Most important for implementation |
|---|---|---|
| pdufa.bio | Yes, no key | 118 PDUFA (57 decided, 60 upcoming, 1 withdrawn), only since 18 Jun 2026. Free plan: `history_access: false`; only 9 events come with `date_history` |
| SEC submissions | Yes, with `User-Agent` (without it, 403) | List of filings per company; parallel arrays in `filings.recent` |
| SEC full-text search | Yes | Metadata only, no text snippet: each document has to be downloaded |
| SEC XBRL `companyfacts` | Yes, ~2 MB per company | Cash is spread across several concepts; mixes quarterly and cumulative periods |
| SEC 8-K Atom | Yes | All companies, no sector filter |
| openFDA `drugsfda` | Yes, no key | Does not include CBER products (cell and gene therapy); ~1 week of delay; mostly generics |
| openFDA `transparency/crl` | Yes | `last_updated` 13 Aug 2026: almost 3 months without an update |
| ClinicalTrials.gov v2 | Yes | Searching by drug brings noise; version history is not accessible (403) |
| Europe PMC | **No** (503 in 3 attempts) | An alternative is needed |
| PubMed E-utilities | Yes | Works as an alternative to Europe PMC |
| yfinance | Yes | Huge spreads in small-biotech options; no prices for companies that no longer trade |
| Kalshi | Yes, no key | ~10 open drug markets, spread across many series and categories; volume of $1,000 to $11,000 |
| Polymarket | Yes | Only 2 active FDA markets and none on small biotech |
| FDA RSS | Yes | 20 entries per feed |
| PR Newswire RSS (health) | Yes | 20 entries |
| GlobeNewswire RSS | **No** (403 with the test URL) | Find the correct URL by industry or organisation |
| Federal Register | Yes | Lots of noise: committee renewals and nominations |

## Reference events: check

| Case | Plan | Real data |
|---|---|---|
| SMMT, ivonescimab | PDUFA 14 Nov 2026, contract on Kalshi | Correct date in pdufa.bio (source: 8-K 29 Jan 2026); `indication` empty. Kalshi `KXIVONESCIMAB-27-Y`, in the *Financials* category, 61–66% Yes. The contract says "decision in 2026", not the PDUFA date |
| SVRA, molgramostim | Extension 22 Aug → 22 Nov | Correct: the May and August 10-Qs say so. pdufa.bio has 22 Nov but no history and with `goal_date_held: true`. Good case of "aggregator without history" |
| NUVL, neladalkib | Priority, 27 Nov 2026 | **Outdated.** GSK bought Nuvalent in July 2026; the event's ticker is now GSK and the date dropped to month precision (Nov 2026). NUVL no longer trades |
| CAPR, deramiocel | Committee 29 Jul 2026 | Correct: vote 3–9 against. Also, extension 22 Aug → 22 Nov (8-K of 24 Aug). It is CBER: it will not appear in `drugsfda` |

Proposed substitute for NUVL: **zidesamtinib** (Nuvalent, NDA220185), PDUFA 18 Sep 2026 and approved on 22 Jul 2026 according to openFDA. It tests the "decision before the date" case.

## Notes by source

### pdufa.bio

- `GET /api/v1/pdufa?limit=1000` returns everything in one call (172 KB). `/events` combines PDUFA, committees, readouts and conferences (502 events, 729 KB).
- Response: `{meta, data[]}`. `meta` carries `total`, `as_of`, `data_built_at` and the licence ("Attribution + link-back required").
- `id` is stable even if the date changes, but it contains the original date (`pdufa_capr_2026-08-22` has date 22 Nov). The `ticker` can change (Nuvalent → GSK). Store by `id`, never by ticker or date.
- Since the free plan does not give full history, the system must keep its own daily copy and build the history by comparing.
- Useful fields the plan does not mention: `decision_date`, `fda_action_date`, `decision_source_url`, `outcome` (Approved, CRL), `market_cap_usd`, `cash_runway_months`, `cohort_move_*`, `runup_summary`.
- `/usage` reports the quota; the `x-ratelimit-*` headers do too.
- On the free plan, 54 of 57 decided are approvals: it is not usable as a base rate without checking that no CRLs are missing.

### SEC EDGAR

- Without a `User-Agent` it responds 403. With a generic one containing an email it works.
- `submissions`: `filings.recent` is an object of parallel arrays (`form[i]`, `filingDate[i]`, `accessionNumber[i]`, `primaryDocument[i]`, `items[i]`).
- Index of a filing: `/Archives/edgar/data/{cik}/{accession without dashes}/index.json` lists the exhibits (EX-99.1).
- Full-text search: `hits.hits[]._source` carries `ciks`, `display_names`, `form`, `file_date`, `file_type`, `adsh`, `items`, `sics`. The `_id` is `adsh:file`. It carries no text: each document has to be downloaded.
- "PDUFA" in 8-Ks, last 7 days: 34 results, almost all quarterly results. Filtering by `sics` (2834, 2836) and by `items` (8.01) reduces noise; the rest has to be read by the LLM.
- XBRL: Savara's cash is $41.8M in `CashAndCashEquivalentsAtCarryingValue` but another $131M in `ShortTermInvestments`. Add up the cash and investment concepts. For quarterly spending, use the rows with a `frame` of type `CY2026Q2`; the others are cumulative.

### openFDA

- With `[` in the URL, curl needs `-g` (or encoding). "No results" returns 404 with `NOT_FOUND`, not an empty list.
- `drugsfda`: filter `application_number` by `NDA` or `BLA`; the rest are generics. Dates like `20261030`. `review_priority` comes in each `submission`.
- ELEVIDYS and CASGEVY are not there: CBER products do not appear. For CBER, use the CBER approvals page and the company's 8-K.
- CRL: dates like `08/07/2026` (another format). Useful for reading reasons, not for detecting decisions.

### ClinicalTrials.gov v2

- `query.intr=molgramostim` also returns sargramostim trials (it expands synonyms). Better `query.spons=<company>` and pick the NCT by hand once.
- `fields=` greatly reduces the response. The full record carries `protocolSection`, `derivedSection` and `hasResults`.
- `/api/int/studies/{NCT}/history` responds 403: the history has to be built with daily copies.

### Literature

- Europe PMC returned 503 ("Search service is temporarily unavailable") in three attempts in a row.
- PubMed: `esearch` (list of PMIDs) and then `esummary` (title, journal, date, type). 98 molgramostim articles; the two most recent are from September 2026.

### yfinance

- Price, market capitalisation and options chain in 2–5 s per company.
- SVRA: only 4 monthly expirations. CAPR and SMMT: weekly.
- Very wide spreads: SVRA ATM call with bid 0 and ask $4.90 on a $4.37 stock; implied volatilities of 200–700%. The implied move only makes sense with spread and open interest filters, and with the snapshot taken after the close.
- NUVL `history`: no data ("possibly delisted"). A backtest using only yfinance loses acquired or bankrupt companies.

### Kalshi

- Unauthenticated reads at `external-api.kalshi.com` and at `api.elections.kalshi.com` (same responses).
- Drug contracts are not in a single series: `KXFDAAPPROVE`, `KXFDAAPPROVAL`, `KXFDAAPPROVALDATE*`, `KXNEWDRUGAPP*`, `KXIVONESCIMAB` (in *Financials*), etc. To discover them you have to download the whole `/series` (15,813 series, 20 MB) and filter by text.
- Prices as dollar text: `yes_bid_dollars`, `yes_ask_dollars`, `last_price_dollars`; volume in `volume_fp`. The rules come in `rules_primary`.

### Polymarket

- `gamma-api.polymarket.com/public-search?q=` searches fuzzily ("Summit Therapeutics" returns football).
- `clobTokenIds` and `outcomePrices` are JSON inside a string: they must be decoded twice.
- `/midpoint`, `/book` and `/prices-history` work with the "Yes" token.
- Only two active FDA markets (retatrutide and skin cancer vaccine). Of little use for this system.

### RSS and Federal Register

- FDA (`press-releases`, `drugs`) and PR Newswire health: work, 20 entries each.
- GlobeNewswire: 403 with the industry URL tried. Business Wire: the identifier of the health feed is still to be found.
- Federal Register: responds fine, but the search "advisory committee" brings mostly renewals and nominations. Filter by document type and the title "Notice of Meeting".

## Historical prices with companies that no longer trade

yfinance returns nothing for a ticker that stopped trading (NUVL after the GSK purchase). For a backtest without survivorship bias:

- **DoltHub `post-no-preference/stocks`**: free (CC BY-SA 4.0), since ~2011, updated daily. Checked with MRTX, KRTX, CLVS and NUVL (NUVL has prices up to 14 Jul 2026). SQL API: `https://www.dolthub.com/api/v1alpha1/post-no-preference/stocks/master?q=SELECT ... FROM ohlcv WHERE act_symbol='NUVL' AND date IN (...)`. Unadjusted prices: splits are in the `split` table. The API is slow with long ranges; better to request specific dates or clone the database with `dolt clone`. A reused ticker can mix two companies.
- **Sharadar SEP** (paid, ~$299/year, personal use): companies that no longer trade, a fixed identifier per company, adjusted and unadjusted prices. An option if DoltHub falls short.
- Hugging Face, GitHub and Kaggle: nothing useful (only large companies, data up to 2017 or paid).
