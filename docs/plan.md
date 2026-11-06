# FDA Catalyst Intelligence — Implementation Plan

Nov 5, 2026 · @Dani

Five phases. Each one leaves the system working and adds a layer on top: after the second it is already useful every day, and after the third it installs from your repository. General criterion: the simplest thing that works. The technical information is in the sister document, the [technical reference](reference.md).

> **Update, 6 Nov 2026.** The data collection is built first, as the module [`information_capturing/`](../information_capturing/README.md): one folder per small company waiting for a decision, plain files instead of SQLite, run on a schedule by an agent that also reads the extraction batches. It covers the calendar and market of phase 1 and the collection side of phases 2 and 4 (filings, trials, papers, FDA sources, prediction markets). Analysis, probabilities and paper trading stay for later modules.

## How it is built

Do the simplest thing that works and add nothing until a real problem asks for it. Each phase ends with something that is actually used.

### Principles

1.  **Simplicity.** SQLite, a CLI and files. No Docker, web servers, queues or checks that nobody will look at.

2.  **Stable interfaces.** The commands, the `sync()` contract and the tables only grow; renaming something requires a migration and a line in the CHANGELOG.

3.  **Anything incomplete is switched off.** A half-finished connector stays disabled in `config/sources.yaml` and breaks nothing.

4.  **Tests without network.** Tests use recorded responses and do not depend on the date. Before each release, a test against the real APIs is run by hand.

5.  **No trading.** No phase connects to a broker or sends orders.

### Cycle of each phase

The same whether done by hand, with Claude Code or with another agent:

1.  Read the phase and the source sheets it covers in the technical reference.

2.  Try each new source against the real API and record the response as a fixture.

3.  Implement, with an SQL migration if needed.

4.  Tests green.

5.  Try with real data on the reference events.

6.  Update README and AGENTS.md, merge into `main` and tag the release.

### Versions

`v0.1` to `v0.5` at the close of each phase; `v1.0` when phase 5 has three months of paper trading. The VPS always installs a tag, never `main`.

## Roadmap

Five phases in order, each building on the previous one.

![Useful in phase 2, installable in phase 3, measurable in phase 5](img/hoja-de-ruta.png)

roadmap · 5 phases, 3 milestones

After phase 2 you already have a calendar, decisions, triage and a daily summary on the Mac. Phase 3 takes it to the VPS. Phases 4 and 5 add the deep analysis and the measurement of whether all this makes money.

## Phase 1 — Calendar and basic market (v0.1)

A catalyst calendar in which every date has a source and a history, and from day one prices and options for those companies are stored. Options data cannot be recovered later, so it is accumulated even if it is not yet analysed.

**Deliverables**

- Repository with `uv`, CLI (`init`, `db upgrade`, `status`, `run`, `calendar`, `event`) and SQLite with the first migration.

- HTTP client with per-source limit, retries and configurable `User-Agent`.

- Connectors `pdufa_bio`, `edgar` (submissions of the watchlist and full-text search) and `wires` (RSS of press-release agencies).

- Announcement extractor with an LLM: drug, indication, application type, date, precision and quote. If the quote does not appear in the document, the data point is discarded.

- Date history: a change adds a row; discrepancies are shown as a conflict.

- **Basic market** (`run market`): every day after the close, price, volume and market capitalisation of the companies in the calendar, and their full options chain saved as JSON, with yfinance. No calculations yet.

**Key tests**

- A quarterly date does not generate an invented day.

- The extension from 22 August to 22 November keeps both dates.

- The same event seen in three sources ends up as a single event.

- If pdufa.bio fails, EDGAR keeps working.

**Exit criterion** (against the list of reference events, at the end of the plan)

- [ ] All reference events appear with their correct date and source.

- [ ] Zero duplicates and no date without a quote.

- [ ] The date changes in the list are visible with their history.

- [ ] One week of daily market snapshots with no gaps.

## Phase 2 — Decisions, triage and daily summary (v0.2)

The system knows when the FDA has decided, ranks events by opportunity and sends you a summary every morning. First useful milestone.

**Deliverables**

- Connectors `openfda` (`drugsfda`: approvals and precedents) and `fda_pages` (approvals of the day, advisory committee calendar, RSS).

- Closing of events with a source: FDA letter or page, or company 8-K and press release. CRLs are detected through the company; the openFDA CRL database is not suitable for this because it is updated irregularly.

- Advisory committees linked to their event (pdufa.bio `/adcomm` and FDA calendar).

- Cash and cash runway per company from SEC XBRL.

- **Triage** A, B or C with `config/triage.yaml`: weight of the drug in the company (flagged in `watchlist.yaml`), market capitalisation, liquidity, market consensus and open uncertainty. Only the A events move on to the full dossier.

- `fdaci event` with a short sheet and `fdaci digest` with decisions, date changes and A events in the next 14 days.

**Key tests**

- A decision before the PDUFA date closes the event.

- A CRL that appears only in an 8-K is recorded with that source.

- Never mark "approved" for lack of news.

- `--quiet` with nothing new prints `NO_REPLY`.

**Exit criterion**

- [ ] The reference events already decided are closed with the correct source.

- [ ] Every event in the calendar has level A, B or C and its reason.

- [ ] Two weeks using the daily summary on the Mac without correcting data by hand.

## Phase 3 — Installation and automation (v0.3)

You push a tag to your repository and OpenClaw downloads it, installs it and schedules the runs. On the Mac you keep launching it by hand or from Claude Code.

**Deliverables**

- `scripts/install.sh <version>`: `uv tool install git+https://github.com/<user>/fda-catalyst-intel@<version>`, `fdaci init` the first time, `fdaci db upgrade` and `fdaci status`. The same script works for updating.

- `fdaci schedule --format openclaw|launchd|crontab`: generates the scheduled runs for OpenClaw on the VPS or for launchd on the Mac.

- `openclaw/skills/fdaci/SKILL.md`: available commands, where the reports are and how to install or update.

- `AGENTS.md` and `CLAUDE.md`: the same for Claude Code on the Mac.

- Nightly backup of the data folder, as one more scheduled run.

- README with a 10-minute installation.

**Key tests**

- Installation from scratch on a clean Ubuntu and on macOS.

- Two simultaneous runs of the same task: the second does nothing.

- Restore a backup.

**Exit criterion**

- [ ] OpenClaw installs a tag on a clean VPS following the skill.

- [ ] Seven days of scheduled runs without intervention, with the summary reaching the channel.

- [ ] Updating to a new tag works the same way: install and `fdaci db upgrade`.

- [ ] Claude Code launches any module on the Mac following `AGENTS.md`.

## Phase 4 — Dossier per event (v0.4)

Level A events receive a full report: trials, publications, prediction markets and options, with every figure quoted and the counterarguments in view.

**Deliverables**

- `ctgov`: sheet for the pivotal trials and a warning if the primary endpoint, the size or the dates change (today's copy is compared with yesterday's).

- `europepmc`: articles, preprints and conference abstracts in a single source.

- **10-Q and 10-K reports** of the company (quarterly and annual, on EDGAR): from the most recent ones, extract, with a quote, what the company says about the review (FDA information requests, *major amendment*, late-cycle meeting, planned advisory committee), manufacturing and inspections, partner agreements and royalties, explained cash and risks specific to the drug. Many small companies give their PDUFA date or the result only in these reports, with no 8-K. They arrive 40–90 days after the close of the period: they are useful for research and for completing the history, not for finding out earlier. They weigh 1–3 MB each, so only the useful sentences are stored.

- Extraction of clinical figures with a quote and simple checks (p between 0 and 1, the interval contains the estimate, the n adds up). If two documents disagree, conflict; if the text does not make it clear, ambiguous and empty.

- Manual review of the 3–5 figures that support the thesis of each A event before using them in the report.

- `kalshi` and `polymarket`: a contract is linked only if drug, indication and deadline match; the midpoint and the spread are stored.

- Implied move calculated with the options snapshots accumulated since phase 1.

- `fdaci report <id>`: sheet, clinical data, regulatory history, cash, market, prediction markets, counterarguments (a second LLM pass that looks for what contradicts the thesis), gaps and sources. It is saved with the date and never overwritten.

**Key tests**

- A contract with a different deadline is not linked to the event.

- Bid 0.35 and ask 0.75 are shown as a range, not as 55%.

- A p outside 0–1 or an interval that does not contain the estimate are rejected.

- Two different figures for the same data point end up in conflict.

**Exit criterion**

- [ ] Reports for three real A events, reviewed by you and saved before their decision.

- [ ] No figure in the report without a quote.

## Phase 5 — Probabilities, trading rules and backtest (v0.5)

Three separate questions with simple answers: will it be approved? how much would the stock move in each case? would a fixed entry and exit rule have made money? No complex models until there is data to justify them.

**Deliverables**

- Base approval rate by category (application type, review, area, committee and vote, resubmission), with published statistics and the events the system closes along the way.

- Approval probability as a range, adjusted with a maximum of six justified factors. The LLM proposes; you approve.

- Move per scenario (approval, CRL, and if applicable restriction or delay) from the implied move and comparable cases; risk of a capital raise according to cash.

- Trading rules in `config/rules.yaml`, fixed before looking at results: R1 enters at the close of the business day before the PDUFA date and exits at the first open after the announcement; R2 the same but exits at the close of the fifth business day. They include costs, out-of-hours announcements, suspensions and capital raises.

- Backtest of R1 and R2 with historical daily prices (yfinance has them; historical options it does not) and past dates from pdufa.bio and EDGAR.

- Paper trading: each A event records entry and exit according to R1 and R2 in the `paper_trade` table.

- `fdaci backtest`: Brier score of the probability against the base rate and against the prediction market, and the result of each rule with the number of events.

**Key tests**

- A backtest at date T uses nothing published after T.

- Changing a rule creates a new rule that is evaluated only on future events.

**Exit criterion**

- [ ] Backtest of the events of the last 12 months with the fixed rules.

- [ ] Three months of paper trading before `v1.0`.

**Afterwards**: with those results, decide calmly. Any connection to a broker would be a separate project, with human approval on every trade.

## Key tests and reference events

Quality is measured against a fixed list of known events, not against how many events there are in the calendar. Ten tests protect the essentials; no more are needed at first.

### The ten tests

1.  A date with month or quarter precision never generates a specific day.

2.  A date change keeps the previous one in the history.

3.  The same event in several sources, or announced by two partner companies, is a single event.

4.  No data point without a quote that appears in its document.

5.  Never "approved" for lack of news.

6.  If a source fails, the others keep going and `fdaci status` shows it.

7.  An impossible or contradictory clinical figure is not silently accepted.

8.  A prediction contract with a different deadline is not linked.

9.  A backtest at date T sees nothing after T.

10. The same commands and fixtures give the same result on the Mac and on Linux.

### Reference events

In `tests/reference_events.yaml`, with the expected result for each. Start with these four and complete up to about 15 with already known decisions: approvals, CRLs, extensions and early dates. Revalidate the dates when using them; they are not investment signals.

| Case                        | What it checks                                                                           |
|-----------------------------|------------------------------------------------------------------------------------------|
| Summit (SMMT), ivonescimab  | PDUFA date of 14 November 2026, contract on Kalshi, drug licensed from Akeso             |
| Savara (SVRA), molgramostim | Extension from 22 August to 22 November 2026; aggregators with the old date              |
| Nuvalent (NUVL), neladalkib | Priority review with a date of 27 November 2026                                          |
| Capricor (CAPR), deramiocel | Advisory committee of 29 July 2026 on its BLA 125842                                     |

### A connector is finished when

- [ ] It works with `fdaci run`, respects the limits of its source and leaves its state in `fdaci status`.

- [ ] It stores the original document and the quote for each data point.

- [ ] It has a test with a recorded response.

- [ ] It has a short sheet in `docs/sources/` with the date on which the API was verified.

## Open decisions and risks

Four decisions are yours; none blocks phase 1 except the first.

| Decision                                     | Options                                                                | When              |
|----------------------------------------------|------------------------------------------------------------------------|-------------------|
| LLM provider for extraction and writing      | Any with reliable JSON output                                          | Phase 1           |
| How to schedule on the VPS                   | OpenClaw command tasks (your case) or cron                             | Phase 3           |
| OpenClaw channel                             | Telegram, WhatsApp, Slack, Discord                                     | Phase 3           |
| Paid options data                            | Only if yfinance fails or falls short: Massive or Interactive Brokers  | When needed       |

| Risk                                        | What is done                                                                   |
|---------------------------------------------|--------------------------------------------------------------------------------|
| Wrong or outdated dates in aggregators      | Primary source rules; discrepancies as a conflict                              |
| The FDA decides before or after the date    | The event stays open until the decision is seen                                |
| An API or a page changes                    | `fdaci status` shows it; that connector is fixed                               |
| yfinance stops working                      | Change `MARKET_PROVIDER`; nothing else changes                                 |
| The LLM invents or misreads                 | Mandatory quote, simple checks and manual review of the key figures            |
| Too few events to draw conclusions          | Always compare with the base rate and do not fit models until there is data    |
| Kalshi and Polymarket blocked in Spain      | Optional module; if it does not respond, it is flagged and the rest keeps going |
