# BioSignal

Research tools to follow small biotech companies that are waiting for an FDA decision (PDUFA date) and to study
whether public information can anticipate the outcome.

**This is research, not investment advice.** Nothing here connects to a broker or places orders.

## What is here

| Path | What |
|---|---|
| [information_capturing/](information_capturing/README.md) | Module 1: finds pending FDA decisions (SEC EDGAR + pdufa.bio) and, for each small company, keeps a folder with its filings, prices, options, prediction markets, clinical trials and papers. Run on a schedule by an agent |
| [docs/plan.md](docs/plan.md) | Implementation plan |
| [docs/reference.md](docs/reference.md) | Technical reference of the data sources |
| [docs/api-pilot.md](docs/api-pilot.md) | What the APIs really return (pilot, Nov 2026) |

## Quick start

```bash
uv sync
cp .env.example .env      # set BIOSIGNAL_CONTACT (name and email; the SEC requires it)
uv run capture init
uv run pytest             # offline tests
```

Collected data goes to `data_collection/`, which is not in the repository. Data from pdufa.bio is used under its
free-plan terms (attribution and link back to pdufa.bio).
