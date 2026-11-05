# FDA Catalyst Intelligence — Technical Reference

Nov 5, 2026 · @Dani

Everything needed by whoever builds or uses the system: sources, access, data rules, model, analysis and interface. The build order is in the companion document, the [implementation plan](plan.md).

## Purpose, scope and principles

The system finds FDA decisions and trial readouts of listed companies, gathers the public evidence with its source, compares it with what the market is pricing in, and produces one report per event. The decision to trade is always a person's.

### What it does

- Catalyst calendar (PDUFA, advisory committees, trial readouts) with date precision, change history and source.

- Stores prices and options of the calendar companies every day from day one, even if they are not analysed yet.

- Triage: decides which events deserve deep analysis according to their possible economic impact.

- Dossier for the important events: clinical data, regulatory history, cash, options and prediction markets.

- Three separate estimates: probability of approval, stock move in each scenario, and the result of a trading rule fixed in advance.

- Daily digest and a record of the actual outcome of each event.

### What it does not do

- It does not execute orders or connect to broker or prediction-market accounts.

- It does not use non-public information or bypass logins or paywalls.

- It gives no investment or clinical recommendations.

### Principles

1.  **Simple first.** One CLI, one SQLite file and folders of files. No Docker, no web server, no queues. Complexity is added only when a real problem asks for it.

2.  **Data comes from documents.** Every date and every key figure carries a URL and a short quote. The LLM reads and summarises, but does not invent; anything ambiguous is left unresolved.

3.  **History is never deleted.** A date change adds a row and marks the previous one as replaced.

4.  **Two dates per data point**: when it was published and when the system saw it. That is enough for an honest backtest.

5.  **Each module works on its own.** If a source fails, it is noted and the rest carries on.

6.  **Research where there is opportunity.** Deep analysis is reserved for the events that pass triage.

### Status of each data point

| Status      | Meaning                                                                |
|-------------|------------------------------------------------------------------------|
| confirmed   | It is in a primary document (SEC, FDA, company, trial registry)        |
| unconfirmed | It appears only in an aggregator or does not yet have a primary source |
| conflict    | Two sources say different things: both are shown                       |
| ambiguous   | The document does not allow certainty: it is left empty                |

### Legal and practical limits

- **Spain**: in May 2026 the DGOJ blocked the Kalshi and Polymarket websites as a precautionary measure ([DGOJ](https://www.ordenacionjuego.es/en/node/3309)). The system only reads their prices; if they do not respond, it notes it and carries on.

- **Terms of use**: respect each source's limits and the attribution that pdufa.bio requires on its free plan. yfinance and market data, for personal use only.

- **Third-party content**: store links and short quotes; full text only with an open licence.

## Architecture and distribution

A Python package with a single command, `fdaci`. The data lives in a SQLite file and in folders of files inside `FDACI_HOME`: copying that folder is the backup.

![A single CLI for people, agents and scheduled tasks](img/arquitectura.png)

architecture · 4 launchers, 1 CLI, 9 modules, 2 stores

The collection modules download, extract with a quote and store. The processing modules only read from the database. Each module is launched separately, by hand or scheduled.

### Technical stack

- Python 3.12 with `uv`; Typer for the CLI; `httpx` with simple retries; `feedparser`; `selectolax` for HTML; PyMuPDF for PDF; Jinja2 for reports.

- SQLite with Python's `sqlite3` module. Migrations as numbered SQL files (`migrations/001_init.sql`, `002_...`) applied by `fdaci db upgrade` according to `PRAGMA user_version`.

- LLM through an API, configurable; JSON output validated with Pydantic.

- `pytest` with recorded responses in `tests/fixtures/`; `ruff` for style.

- If real concurrency or several users are ever needed, move to PostgreSQL; not before.

### Repository structure

``` text
fda-catalyst-intel/
  pyproject.toml  uv.lock  .env.example  README.md  AGENTS.md  CLAUDE.md  CHANGELOG.md
  config/        sources.yaml  watchlist.yaml  triage.yaml  rules.yaml  conferences.yaml
  migrations/    001_init.sql  002_...sql
  src/fdaci/
    cli.py
    core/        config, db, http, files, llm
    connectors/  one file per source
    modules/     calendar, fda, market, clinical, predict, triage, report, backtest
  openclaw/      skills/fdaci/SKILL.md
  scripts/       install.sh
  tests/         fixtures/  reference_events.yaml  test_*.py
  docs/          reference.md  plan.md  sources/
```

### Data folder

``` text
$FDACI_HOME/
  fdaci.db                      database
  raw/<source>/<date>/          downloaded documents as they are
  market/<date>/<ticker>.json   full option chains
  reports/<event>/<date>.md     reports; never overwritten
  digest/<date>.md              daily digest
  fdaci.log                     text log
```

### Connector contract

``` text
def sync(since: date | None = None) -> SyncResult: ...

@dataclass
class SyncResult:
    new: int
    updated: int
    ok: bool
    error: str | None = None
```

Each connector respects its source's limit and `Retry-After`, stores the original document in `raw/` before interpreting it and, if it fails, leaves the error in `source_status` without stopping the others.

## Source catalogue

Ten sources are enough for the complete system and all of them are free. The rest are optional: add them only if needed.

### Core

| Source                                                    | Module        | Access    | Key                          | Limits                                          | Purpose                                                              |
|-----------------------------------------------------------|---------------|-----------|------------------------------|-------------------------------------------------|----------------------------------------------------------------------|
| pdufa.bio                                                 | calendar      | API       | Optional                     | 1,000/day and 10/min without key                | Starting calendar with date history                                  |
| SEC EDGAR (submissions, full-text search, XBRL)           | calendar, fda | API       | No; `User-Agent` required    | 10 requests/s                                   | Verify dates, announced CRLs, cash                                   |
| Press release wires                                       | calendar      | RSS       | No                           | Reasonable                                      | Announcements as soon as they come out                               |
| openFDA `drugsfda`                                        | fda           | API       | Optional                     | 1,000/day without key; 120,000 with free key    | Approvals and precedents                                             |
| FDA pages (approvals, committees, RSS)                    | fda           | HTML, RSS | No                           | Reasonable                                      | Same-day decisions and committees                                    |
| ClinicalTrials.gov API v2                                 | clinical      | API       | No                           | ≈ 50/min                                        | Trial design and changes                                             |
| Europe PMC                                                | clinical      | API       | No                           | Reasonable                                      | Articles, preprints and conference supplements in a single search    |
| yfinance                                                  | market        | Library   | No                           | Unofficial                                      | Prices, volume and options from day one, personal use                |
| Kalshi                                                    | predict       | API       | Not for reading             | Per docs                                        | Market probability                                                   |
| Polymarket                                                | predict       | API       | No                           | Per docs                                        | Market probability                                                   |

### Optional, when needed

| Source                                             | When to add it                                                                                    |
|----------------------------------------------------|---------------------------------------------------------------------------------------------------|
| Massive or Interactive Brokers                     | If yfinance fails or better quality is needed for options                                         |
| openFDA CRL                                        | To read rejection reasons; updated irregularly and not useful for detecting decisions             |
| Federal Register                                   | If the FDA committee calendar and pdufa.bio are not enough                                        |
| FDA Data Dashboard                                 | To review inspections of a plant in an A event                                                    |
| FINRA Short Interest                               | If short interest turns out to be useful in triage                                                |
| Per-company investor websites                      | For key companies on the watchlist                                                                |
| AACT                                               | To reconstruct past trials in the backtest                                                        |
| PubMed, Crossref, OpenAlex, bioRxiv                | If Europe PMC does not find something                                                             |
| Endpoint Arena, EMA, OpenFIGI, paid aggregators    | Only if they are shown to add something                                                           |

The following entries describe all of them, core and optional, so they do not have to be researched again.

## Connectors: calendar and FDA

The calendar starts from pdufa.bio and is verified and completed with EDGAR and press releases; the FDA confirms committees and decisions. All connectors follow the common contract described in the architecture.

### pdufa.bio (calendar, A)

- **Base**: `https://www.pdufa.bio/api/v1`. Endpoints `/pdufa`, `/events`, `/readouts`, `/conferences`, `/adcomm`, `/usage`, `/health`. Parameters `ticker`, `type`, `status`, `from`, `to`, `q`, `limit` (max. 1,000), `offset`, `format` ([docs](https://www.pdufa.bio/developers)).

- **Access**: without a key, 1,000 requests per day and 10 per minute. With a free key (`x-api-key` header), 10,000 per month and 30 per minute. Respect `Retry-After` on 429.

- **Key fields**: `date` (null if not an exact day), `date_precision` (day, month, quarter, year), `date_month`, `date_history` with the reason for each change, `source` and `source_url`, `goal_date_held`, stable `id`.

- **Origin of the dates**: exact-day dates come from the FDA, SEC or the company; periods are usually ClinicalTrials.gov estimates and change.

- **Persist**: the whole raw record, plus `upsert` by `(source, external id)`, never by date.

- **Obligation**: visible link to pdufa.bio in reports and views that use its data on the free plan.

- **Caution**: the page is ambiguous about whether NCT and indication are free; treat them as optional.

### SEC EDGAR (calendar and market, A)

| Endpoint                                                                              | Use                                                                                  |
|---------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| `https://www.sec.gov/files/company_tickers.json`                                      | Ticker → CIK (daily)                                                                 |
| `https://data.sec.gov/submissions/CIK##########.json`                                 | Filings per company; 10-digit CIK                                                    |
| `https://efts.sec.gov/LATEST/search-index?q=&forms=&dateRange=custom&startdt=&enddt=` | Full-text search across all of EDGAR, exhibits included; `/LATEST/` in capitals      |
| `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom`     | Latest 8-Ks, almost in real time                                                     |
| `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`                       | Cash, debt, spending, shares (market sheet)                                          |
| `https://www.sec.gov/Archives/edgar/data/{cik}/{accession sin guiones}/{archivo}`     | Original document; the press release is usually EX-99.1                              |

- **Rules** ([SEC](https://www.sec.gov/edgar/searchedgar/accessing-edgar-data.htm)): `User-Agent` header with the tool name and a configurable contact email (without it, 403); maximum 10 requests per second in total; operate at 5 per second with backoff.

- **Discovery queries** (forms 8-K, 6-K, 10-Q, 10-K, 20-F; last 7 days): `"PDUFA"`, `"target action date"`, `"major amendment"`, `"complete response letter"`, `"advisory committee"`, `"accepted for filing"`, `"priority review"`, `"late-cycle meeting"`.

- **Extraction**: the LLM receives the paragraph and returns drug, indication, application type, review type, date, precision and verbatim quote. It is validated that the quote appears in the document.

### Press releases and investor websites (calendar, A)

- PR Newswire: `https://www.prnewswire.com/rss/health-latest-news/health-latest-news-list.rss` and the index `prnewswire.com/rss/`.

- GlobeNewswire: feeds by industry (Biotechnology, Pharmaceuticals) and by organisation at `rss.globenewswire.com`.

- Business Wire: Health, Clinical Trials, Oncology feeds and per-company feeds.

- Investor websites: one configurable adapter per company (URL of the RSS or of the news page), declared in `config/watchlist.yaml`.

- Keyword filter and later verification against EDGAR.

### Paid aggregators (calendar, C)

Only as a hint, with status verified_secondary at most. [Benzinga](https://docs.benzinga.com/api-reference/calendar-api/get-fda.md) `GET https://api.benzinga.com/api/v2.1/calendar/fda` with `parameters[date_from]`, `parameters[date_to]`, `parameters[date_search_field]=target`, `parameters[securities]`; dates are sometimes fuzzy (`2026-Q1`). [BiopharmaWatch](https://biopharmawatch.com/subscription) `/api/v2/pdufa/upcoming` and `/api/v2/pdufa/historical`.

### openFDA and Drugs@FDA (fda, A)

- **Base**: `https://api.fda.gov/{category}/{endpoint}.json`; parameters `search` (Lucene syntax), `count`, `limit` (max. 1,000), `skip`, `sort`; key in `api_key` ([authentication](https://open.fda.gov/apis/authentication)).

- **Endpoints**: `drug/drugsfda` (applications and their history: confirms approvals and precedents), `drug/label` (labels), `transparency/crl` (rejection letters with reasons).

- **Drugs@FDA Data Files**: ZIP with 12 tables, updated every morning Monday to Friday ([FDA](https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files)); complete local copy with links to letters and reviews.

- **Caution**: Drugs@FDA is historical, not a calendar of pending applications.

- **CRL**: the FDA has published them since July 2025. It paused real-time publication in April 2026 and resumed it on 10 July 2026, with a rule in preparation ([IntuitionLabs](https://intuitionlabs.ai/articles/fda-complete-response-letters-dataset)). Do not depend on them: the company usually announces the CRL earlier in an 8-K.

### Advisory committees, approvals and notices (fda, A)

| Source                                                                                                                          | Method                                                                                                     | Signal                                                                                                  |
|---------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|
| Advisory Committee Calendar (fda.gov)                                                                                           | Daily HTML                                                                                                 | Meeting with product, company and application number; briefing documents at the latest 2 business days before |
| Federal Register API `https://www.federalregister.gov/api/v1/documents.json`                                                    | Daily API; `conditions[agencies][]=food-and-drug-administration`, `conditions[term]="advisory committee"` | Legal notice at least 15 days before each meeting (21 CFR 14.20)                                        |
| Regulations.gov API v4                                                                                                          | API                                                                                                        | Docket and committee comments (docket number from the notice)                                           |
| Novel Drug Approvals (CDER), CBER approvals, oncology notifications                                                             | HTML every 30 min on business days                                                                         | Same-day approval                                                                                       |
| FDA RSS: `press-releases`, `drugs`, `biologics` under `https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/`     | Feed                                                                                                       | Press releases and CDER and CBER news                                                                   |

### Inspections and manufacturing (fda, B)

[FDA Data Dashboard](https://www.fda.gov/about-fda/performance-data/fda-data-dashboard): inspections (NAI, VAI, OAI), 483 citations and enforcement actions (warning letters). Weekly update, final actions only; API with registration and XLSX downloads. It is linked by the FEI of each declared plant. Rule: the absence of manufacturing information does not mean low risk.

## Connectors: clinical and conferences

Trial registries and literature have free, stable APIs. Conferences have no API: press releases, journal supplements and a manually maintained embargo calendar are combined.

### ClinicalTrials.gov API v2 (clinical, A)

- **Endpoints**: `https://clinicaltrials.gov/api/v2/studies` (search) and `/studies/{NCT}` (record). No key; about 50 requests per minute per IP; JSON or CSV; pagination with `pageToken` / `nextPageToken`.

- **Useful parameters**: `query.term`, `query.intr` (intervention), `query.spons`, `query.cond`, `filter.overallStatus`, `fields` to reduce the response.

- **Store**: `protocolSection`, `resultsSection`, `derivedSection` in full as a file in raw/; each day it is compared with the previous copy.

- **Different dates, never mix**: `primaryCompletionDate`, `completionDate`, `resultsFirstPostDate`, `lastUpdatePostDate`. None of them is a PDUFA date.

- **History**: the API gives the current version. The system stores a daily copy of each watched trial and records differences (primary endpoint, size, dates, status). For the past, use AACT.

- **Link**: an NCT is linked to drug and indication; a trial may test several drugs (combinations).

### AACT (clinical and backtest, B)

PostgreSQL database from CTTI that downloads all of ClinicalTrials.gov every day, with cloud access through a free account and downloadable full copies, including old versions ([AACT](https://aact.ctti-clinicaltrials.org/)). It is used to reconstruct what a trial looked like on a past date and for backtest cohorts. It is not a source of PDUFA dates.

### Literature

| Source                                                               | Endpoint                                                                                     | Access                                                                                     | Use                                                                    |
|----------------------------------------------------------------------|----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| [PubMed E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/)   | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi`, `efetch.fcgi`, `esummary.fcgi` | 3 req/s; 10 with key; send `tool` and `email`                                              | Articles by INN, development code and NCT                              |
| Europe PMC                                                           | `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=&resultType=core&format=json` | No key                                                                                     | PubMed, PMC, preprints and conference supplements in one search        |
| Crossref                                                             | `https://api.crossref.org/works?query.bibliographic=&mailto=`                                | No key; `mailto`                                                                           | Metadata by DOI, supplements by ISSN, corrections and retractions      |
| [OpenAlex](https://groups.google.com/g/openalex-users/c/rI1GIAySpVQ) | `https://api.openalex.org/works`                                                             | Free key required since 13 February 2026; daily budget by credits                          | Related works and citations                                            |
| [bioRxiv / medRxiv](https://api.biorxiv.org)                         | `https://api.biorxiv.org/details/{server}/{desde}/{hasta}/{cursor}`                          | No key                                                                                     | No keyword search: download the daily window and filter locally        |

**Rules**: deduplicate by DOI, then PMID/PMCID, then normalised title. Classify the type (original article, review, editorial, preprint, conference abstract, press release). Store online date, formal date and ingestion date. Download full text only with an open licence; for the rest, metadata and link.

### Conferences (clinical, B)

There is no public abstract API for ASCO, ESMO or ASH. The connector supports four modes: `official_api`, `public_rss`, `public_html_permitted` and `manual_upload_licensed`. Sources, from most to least reliable:

1.  **Company press releases**: they announce the presentation with the abstract number and usually post the slides in an 8-K (EX-99.2). The calendar already captures them.

2.  **Journal supplements**: ASCO publishes in Journal of Clinical Oncology and ESMO in Annals of Oncology; they are located through Europe PMC or Crossref.

3.  **Embargo calendar** in `config/conferences.yaml`: conference, dates, publication time of regular and late-breaking abstracts, in UTC (`embargo_until`). At ESMO the late-breaking abstracts become public when their session starts. The system schedules a search right after each embargo and never ingests material before that time.

4.  **Conference websites** (ASCO Meeting Library, OncologyPRO): public pages only and respecting terms; posters, slides and videos usually require membership.

### Results extraction

Each clinical document is turned into rows of the `fact` table: trial, arm, endpoint and its level (primary, key secondary, exploratory), metric, value, 95% CI, p, n and data cut-off date, each with its quote. The checks and the manual review are in the truth rules.

## Connectors: market, identifiers and prediction markets

Market data goes behind a single interface so the provider can be changed. Prediction markets are optional: they provide a probability when they exist and never block the rest.

### `MarketDataProvider` interface

Methods: `get_daily_bars`, `get_corporate_actions`, `get_shares_outstanding`, `get_option_chain`, `get_quotes`. Adapters:

| Provider                                     | Use                                                                                                                                                            | Notes                                                                                                                                                                                                                                                                                       |
|----------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Massive (formerly Polygon.io)                | Daily bars `GET /v2/aggs/ticker/{t}/range/1/day/{desde}/{hasta}` and option chain `GET /v3/snapshot/options/{subyacente}` at `https://api.massive.com`        | Implied volatility and Greeks are current only, computed from the midpoint; no volatility history ([Massive](https://massive.com/knowledge-base/article/why-are-greeks-and-implied-volatility-missing-from-the-options-snapshot)). Snapshot not included in the Options Basic plan          |
| Interactive Brokers (TWS API via IB Gateway) | Historical implied volatility with `OPTION_IMPLIED_VOLATILITY` bars; chains and quotes                                                                         | Requires IB Gateway running and data subscriptions (OPRA), billed per full month ([IBKR](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-bar-what-to-show/option-implied-volatility))                                                                  |
| `yfinance`                                   | Default option at the start: prices, volume and option chains with implied volatility, to accumulate history from day one                                      | Unofficial and for personal use; if it fails, change MARKET_PROVIDER and the rest stays the same                                                                                                                                                                                            |

**Rule**: since no affordable provider gives reliable historical implied volatility, the system stores its own daily options snapshot from the moment an event enters the calendar. Splits, reverse splits, ticker changes and non-trading days are recorded explicitly.

### Other market sources

- **FINRA Short Interest** ([FINRA](https://www.finra.org:443/finra-data/browse-catalog/equity-short-interest)): consolidated twice a month, through the Query API at `api.finra.org` or files at `cdn.finra.org`. Do not confuse it with daily short volume, which is a different file.

- **SEC XBRL** (`companyfacts`): cash, short-term investments, debt, operating expenses, shares outstanding. Months of cash = cash ÷ average quarterly spending × 3. Always use the same concept (basic or diluted) and fix the price date.

- **OpenFIGI** `POST https://api.openfigi.com/v3/mapping`: validates ticker, market and identifier; optional `X-OPENFIGI-APIKEY` header (10 identifiers per request without a key, 100 with a key).

### Kalshi (predict, B)

- **Base**: `https://external-api.kalshi.com/trade-api/v2` (`https://api.elections.kalshi.com/trade-api/v2` also works). Reading without authentication ([docs](https://docs.kalshi.com/getting_started)).

- **Hierarchy**: Series → Events → Markets. Endpoints: `/series/{s}`, `/events?series_ticker=&status=open&with_nested_markets=true`, `/markets?limit=`, `/markets/{ticker}`, `/markets/{ticker}/orderbook`, `/series/{s}/markets/{ticker}/candlesticks`. For already settled markets, check the documentation for the historical routes.

- **Series of interest**: `KXFDAAPPROVE` (approval before a date) and `KXFDAANNOUNCE`; discover new biotech series by walking through `/series` once a day.

- **Contract rules** ([FDAAPPROVAL](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/FDAAPPROVAL.pdf)): traditional, accelerated and approval with REMS all count; a CRL resolves "No" unless approved later before the date; a deadline extension is not an approval; if the committee votes against and the FDA approves, it resolves "Yes".

- **Store**: ticker, event, full text of the rules, open and close in UTC, bid, ask, last, volume, open interest, status and snapshot time.

- **No account connection and no orders.**

### Polymarket (predict, B)

| API                    | Host                               | Endpoints                                                                     |
|------------------------|------------------------------------|-------------------------------------------------------------------------------|
| Gamma (discovery)      | `https://gamma-api.polymarket.com` | `/public-search?q=`, `/events`, `/markets`, `/tags`                           |
| CLOB (prices)          | `https://clob.polymarket.com`      | `/price`, `/midpoint`, `/book`, `/prices-history?market=&interval=&fidelity=` |
| Data                   | `https://data-api.polymarket.com`  | `/oi`, `/trades`                                                              |

Flow: `public-search` → `clobTokenIds` (index 0 = Yes) and `conditionId` → price, book and history ([docs](https://docs.polymarket.com/market-data/overview)). No keys, no wallets, no orders. Follow the pagination given by the current documentation.

### Endpoint Arena (predict, C)

Read-only API at `https://endpointarena.com`: `/api/current-season`, `/api/v1/markets`, `/api/v1/markets/{id}`, `/api/leaderboard`, and an MCP ([API](https://endpointarena.com/api)). In season 8 only AI models trade, each with 100,000 simulated dollars ([method](https://endpointarena.com/method)). Store with origin `simulated_ai`; never treat it as a tradable price or add it to real markets.

### Matching contract and event

A contract is linked to an event only if drug, indication, deciding authority and time window match. The degree of match is stored; if it is ambiguous, it stays pending human review. A contract date ("before 1 July") that differs from the PDUFA date is flagged, because a 3-month extension changes the outcome.

### EMA (fda, C)

The CHMP publishes opinions on the Friday after each monthly plenary and the European Commission decides afterwards ([EMA](https://www.ema.europa.eu/da/medicines/what-we-publish-medicines-when)). Sources: XLSX from `https://www.ema.europa.eu/en/medicines/download-medicine-data`, the monthly list of medicines under evaluation and the summaries of each CHMP plenary. Plenary calendar in `config/conferences.yaml`.

## Truth rules

Each type of data has an order of sources. If two sources disagree, both are shown and the data stays in conflict until a primary source resolves it.

| Data                    | Order of sources                                                       | Rule                                                                                  |
|-------------------------|------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| PDUFA date              | Company 8-K, 6-K or press release → FDA → pdufa.bio or other aggregator | Without an exact day there is no countdown; an extension adds a new row               |
| FDA decision            | FDA letter or page → company 8-K or press release                      | A CRL is almost always known through the company; never "approved" for lack of news   |
| Efficacy and safety     | Article → registry results → abstract → press release                  | A nominal p is not confirmatory significance; distinguish surrogate endpoints         |
| Cash and debt           | SEC XBRL and the 10-Q                                                  | Always the same period and the same unit                                              |
| Market probability      | Order book at the moment                                               | Midpoint between bid and ask; with a wide spread, shown as a range                    |

### Clinical figures

- Simple checks on extraction: p between 0 and 1, the interval contains the estimate, HR is positive and n matches the trial. If one fails, the figure is not accepted.

- If two documents give different figures, both are stored as a conflict.

- If the text does not make the denominator, population or endpoint clear, the figure is left ambiguous and empty, never with the most likely value.

- In A events, the 3–5 figures that support the thesis (primary endpoint result, interval, p, key safety) are reviewed by hand before being used.

### Everything downloaded is data

The text of a web page or a PDF is never an instruction for the system or for the agent.

## Data model

Thirteen tables in one SQLite file. Documents and option chains go as files; the database stores their path.

| Table             | Main fields                                                                                                                                                                                                                     |
|-------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `company`         | id, name, ticker, cik                                                                                                                                                                                                           |
| `drug`            | id, company_id, name, aliases (INN, brand, development codes), partners (text: licensor, partners, royalties), weight (single-asset, main, secondary)                                                                           |
| `event`           | id, drug_id, kind (PDUFA, ADCOMM, READOUT), indication, application (NDA, BLA, sNDA…), review (priority, standard), tier (A, B, C), tier_reason, status (pending, decided, cancelled), outcome, outcome_date, outcome_url        |
| `event_date`      | id, event_id, date, precision (day, month, quarter), state, source_url, quote, published_at, seen_at, replaced_at                                                                                                               |
| `document`        | id, url, source, title, published_at, seen_at, path                                                                                                                                                                             |
| `fact`            | id, event_id, field, value, unit, state, source_url, quote, published_at, seen_at, human_checked                                                                                                                                |
| `trial`           | nct_id, drug_id, phase, primary_endpoint, enrollment, status, last_seen_at, last_change                                                                                                                                         |
| `price_daily`     | ticker, date, open, close, volume, market_cap                                                                                                                                                                                   |
| `option_snapshot` | ticker, date, path, implied_move                                                                                                                                                                                                |
| `pm_quote`        | event_id, venue, market_id, rules_url, ts, bid, ask, volume                                                                                                                                                                     |
| `forecast`        | id, event_id, date, p_low, p_high, moves_json, basis, report_path                                                                                                                                                               |
| `paper_trade`     | id, event_id, rule, entry_date, entry_price, exit_date, exit_price, return, xbi_return, notes                                                                                                                                   |
| `source_status`   | source, last_ok_at, last_error, last_error_at                                                                                                                                                                                   |

- `published_at` and `seen_at` on each data point make it possible to reconstruct what was known on a past date.

- A date that changes is not edited: `replaced_at` is filled in on the old row and a new one is added.

- Option chains are stored in full in `market/<date>/<ticker>.json`; `implied_move` is computed later, when needed.

- Times in UTC; displayed in Madrid time. US market hours are interpreted in America/New_York.

## Analysis: triage, three estimates and trading rules

First it is decided which events deserve work. Then three questions are answered separately: whether it will be approved, how much the stock would move, and whether a fixed trading rule would have made money. No complex models until there is data to justify them.

### Triage

A simple classification using data that already exists, with thresholds in `config/triage.yaml`:

| Signal                         | How it is measured                                                                      | Why it matters                                               |
|--------------------------------|-----------------------------------------------------------------------------------------|--------------------------------------------------------------|
| Weight of the drug in the company | Marked by hand in `watchlist.yaml` (single-asset, main, secondary) and market cap    | An approval barely moves a diversified pharma company        |
| Implied move                   | Options, if any                                                                         | How much the market thinks the price can change              |
| Consensus                      | Price on Kalshi or Polymarket, if it exists                                             | Above 90% there is little margin left                        |
| Open uncertainty               | Committee convened, extension, prior CRL, disputed data                                 | Where there are doubts there may be pricing errors           |
| Liquidity                      | Average daily volume in dollars                                                         | Without liquidity there is no reasonable trade               |

- **A**: full dossier and report. **B**: short sheet and follow-up. **C**: calendar only.

- Thresholds start as rough estimates and are adjusted with the results.

### 1. Probability of approval

- Base rate by category (application type, review, area, committee and its vote, resubmission), using published statistics and the events the system closes over time.

- Adjustment with a short list of factors, six at most, each with its evidence. The LLM proposes; the person approves.

- Result as a range (for example, 70–80%), never as an exact figure.

- No fitted statistical model until there are at least 100 resolved events; in the meantime, the reference is the base rate.

### 2. Stock move in each scenario

- Scenarios: approval and CRL; if applicable, restricted approval or delay.

- Move range per scenario based on the options' implied move and on comparable cases (size, single-asset or not, area).

- With little cash, expect a capital raise after an approval.

Implied move of the event, with an expiry before the date (T₁, σ₁) and another just after (T₂, σ₂), T in years:

``` text
\sigma_{evento} \approx \sqrt{\sigma_2^2 T_2 - \sigma_1^2 T_1}
```

Quick check: price of the at-the-money straddle of the later expiry divided by the stock price.

### 3. Trading rules

They are fixed in `config/rules.yaml` before any backtest and are not changed after seeing results. A new rule is evaluated only with future events.

| Rule  | Entry                                          | Exit                                        |
|-------|------------------------------------------------|---------------------------------------------|
| R0    | None                                           | Reference                                   |
| R1    | Close of the business day before the PDUFA date | First open after the announcement          |
| R2    | Same as R1                                     | Close of the fifth business day after the announcement |

- If the FDA decides before the entry, the event is excluded and counted.

- Announcement outside trading hours: the exit is the first available open.

- Trading halt: first price after resumption.

- Costs: average spread plus a configured fixed commission.

- Capital raise announced in the window: it is recorded and counted in the result.

- Result also against the XBI index.

Expected value of the rule, with p from question 1, G and L (rise and fall) from question 2 and c the costs:

``` text
EV = p \cdot G - (1 - p) \cdot L - c
```

### Measuring whether it works

- Brier score of the approval probability against the base rate and the prediction market.

- Result of R1 and R2 in simulated trading, with the number of events and without re-optimising.

- Only events with a report saved before the decision count.

### When the report is research only

If the confirmed date is missing, it is unclear who benefits from the drug, the price is stale or a key figure has not been reviewed, the report is marked `RESEARCH_ONLY`.

## Interface: commands and configuration

A single command, `fdaci`, for you, for a coding agent and for scheduled tasks. Each module is launched on its own or all together.

``` text
fdaci init                    # creates FDACI_HOME, .env and example configuration
fdaci db upgrade              # applies migrations
fdaci status                  # last successful run and last error of each source

fdaci run calendar            # pdufa.bio, EDGAR, press releases
fdaci run fda                 # decisions, committees, precedents
fdaci run market              # prices and options of the calendar companies
fdaci run triage              # recomputes tiers A, B and C
fdaci run clinical            # trials and literature for A and B events
fdaci run predict             # Kalshi and Polymarket
fdaci run all                 # everything, in this order

fdaci calendar [--days 90]    # upcoming events
fdaci event <id|ticker>       # event sheet
fdaci report <id>             # report; saved with the date and does not overwrite
fdaci digest                  # summary of the day in digest/<date>.md
fdaci backtest                # rules R1 and R2 on resolved events
fdaci schedule --format crontab|launchd|openclaw   # recommended scheduling
```

- `--json` on the query commands, so another program can read the output.

- `--quiet` prints only news; if there is none, it prints `NO_REPLY` and OpenClaw sends no message.

- Exit codes: 0 fine, 1 error, 2 some source failed.

- If an identical run is still in progress, the second one ends without doing anything (lock file).

### Configuration

- `.env`: keys and paths.

- `config/watchlist.yaml`: companies and drugs to follow closely, with their weight (single-asset, main, secondary).

- `config/triage.yaml`: triage thresholds.

- `config/rules.yaml`: trading rules R1 and R2.

- `config/sources.yaml`: active sources and frequency.

- `config/conferences.yaml`: conference dates and embargoes (optional).

``` text
variable,use,required
FDACI_HOME,Data folder,yes
FDACI_CONTACT,Name and email for the SEC and NCBI User-Agent,yes
LLM_PROVIDER / LLM_API_KEY / LLM_MODEL,Extraction and writing,yes
OPENFDA_API_KEY,More quota on openFDA,no
PDUFA_BIO_API_KEY,More quota on pdufa.bio,no
MARKET_PROVIDER,yfinance (default) | massive | ibkr,no
MASSIVE_API_KEY,Only if Massive is used,no
DISPLAY_TZ,Europe/Madrid by default,no
```

## Installation, scheduling and security

You develop and test on the Mac, launching it from the terminal or from Claude Code. When a version is ready, you push it to the repository with a tag; OpenClaw installs it on the VPS and schedules the runs.

### Installation

``` text
# Mac (development)
git clone https://github.com/<usuario>/fda-catalyst-intel && cd fda-catalyst-intel
uv sync
uv run fdaci init            # then, fill in .env
uv run fdaci db upgrade
uv run fdaci run calendar

# VPS or other machine
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install git+https://github.com/<usuario>/fda-catalyst-intel@v0.3.0
fdaci init && fdaci db upgrade && fdaci status
```

- On the VPS, a dedicated system user and `.env` with 600 permissions.

- Backup: every night, `sqlite3 fdaci.db ".backup copia.db"` and copy the rest of the folder.

- Update: install the new tag and run `fdaci db upgrade`.

### Scheduling

`fdaci schedule --format crontab` prints the lines ready to paste (times in UTC):

``` text
*/15 13-21 * * 1-5  fdaci run calendar --quiet
0 */2 * * *         fdaci run fda --quiet
30 22 * * 1-5       fdaci run market
0 5 * * *           fdaci run triage && fdaci run clinical && fdaci run predict
0 6 * * *           fdaci digest --quiet
```

- On the Mac, `--format launchd` if you also want it to run on its own there.

- On the VPS, `--format openclaw` generates the tasks for OpenClaw (`openclaw cron create … --command-argv '["fdaci","run","calendar","--quiet"]'`), which run the command and send the output to the channel ([docs](https://docs2.openclaw.ai/cli/cron.md)).

- To change frequencies: edit `config/sources.yaml` and regenerate, or ask OpenClaw directly.

### OpenClaw and Claude Code

The same `fdaci` commands work in both places.

- **On the Mac**: you launch it from the terminal or ask Claude Code to run a module, everything or a report. `AGENTS.md` and `CLAUDE.md` explain the commands to it.

- **On the VPS**, OpenClaw orchestrates:

  1.  You publish a tag in the repository, for example `v0.3.0`.

  2.  You ask it to install or update: it runs `scripts/install.sh v0.3.0`, which installs that version, runs `fdaci init` the first time, `fdaci db upgrade` and `fdaci status`.

  3.  It schedules the runs with what `fdaci schedule --format openclaw` generates, or with the frequency you ask for.

  4.  It sends you the daily digest and answers questions using `fdaci calendar`, `fdaci event` and `fdaci report`.

- The skill `openclaw/skills/fdaci/SKILL.md` explains to it the commands, files and how to install or update.

- The Mac and the VPS each have their own `FDACI_HOME`. To move data from one to the other, copy the folder.

- No broker or prediction-market key anywhere.

## References

Verified between 3 and 5 November 2026. APIs change: each connector must pass a smoke test against the current documentation before being finalised.

- **Calendar**: [pdufa.bio API](https://www.pdufa.bio/developers), [SEC: Accessing EDGAR Data](https://www.sec.gov/edgar/searchedgar/accessing-edgar-data.htm), [full-text search guide](https://orthogonal.info/sec-edgar-full-text-search-api-efts-python/), [submissions and ticker → CIK](https://dev.to/odeeb/sec-edgar-api-submissions-json-and-ticker-to-cik-9f5), [Benzinga Calendar API](https://docs.benzinga.com/api-reference/calendar-api/get-fda.md), [BiopharmaWatch](https://biopharmawatch.com/subscription)

- **FDA**: [openFDA authentication](https://open.fda.gov/apis/authentication), [Drugs@FDA Data Files](https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files), [FDA Data Dashboard](https://www.fda.gov/about-fda/performance-data/fda-data-dashboard), [CRL database](https://intuitionlabs.ai/articles/fda-complete-response-letters-dataset), [committee notice 15 days before](https://www.federalregister.gov/documents/full_text/xml/2013/01/02/2012-31475.xml)

- **Clinical**: [ClinicalTrials.gov API v2](https://cdn.jsdelivr.net/npm/@saibolla/ada@0.1.3/skills/clinicaltrials-database/references/api_reference.md), [AACT](https://aact.ctti-clinicaltrials.org/), [E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/), [bioRxiv API](https://api.biorxiv.org), [OpenAlex keys](https://groups.google.com/g/openalex-users/c/rI1GIAySpVQ)

- **Prediction markets**: [Kalshi](https://docs.kalshi.com/getting_started), [Kalshi environments](https://dev.to/deskbot_store/kalshi-api-keys-and-authentication-how-request-signing-works-41ia), [FDAAPPROVAL terms](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/FDAAPPROVAL.pdf), [Polymarket](https://docs.polymarket.com/market-data/overview), [Endpoint Arena API](https://endpointarena.com/api), [Endpoint Arena method](https://endpointarena.com/method), [DGOJ](https://www.ordenacionjuego.es/en/node/3309)

- **Market**: [Massive](https://massive.com/knowledge-base/article/why-are-greeks-and-implied-volatility-missing-from-the-options-snapshot), [IBKR TWS API](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-bar-what-to-show/option-implied-volatility), [FINRA Short Interest](https://www.finra.org:443/finra-data/browse-catalog/equity-short-interest)

- **OpenClaw**: [cron](https://docs.openclaw.ai/cron), [cron CLI](https://docs2.openclaw.ai/cli/cron.md), [sandbox and tool policy](https://docs.openclaw.ai/gateway/sandbox-vs-tool-policy-vs-elevated.md), [tools per agent](https://docs.openclaw.ai/tools/multi-agent-sandbox-tools), [skill format](https://docs.openclaw.ai/clawhub/skill-format.md)

- **Europe**: [EMA: what is published and when](https://www.ema.europa.eu/da/medicines/what-we-publish-medicines-when)
