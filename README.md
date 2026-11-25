# Georgia PSC public records

A nightly copy of every public filing at the Georgia Public Service Commission, made searchable.

This is an independent project. It is not a work product of the Georgia Public Service Commission, and the Commission does not run or endorse it. The Commission's own record is at psc.ga.gov.

The Commission has no single feed of new filings. Every filing has its own page, and filing numbers run in one sequence across all dockets. So the harvester walks the numbers forward each night and stores what it finds.

## What it keeps

- **Every filing:** company, description, filed and received dates, docket, and the list of attachments, in `data/filings/`.
- **Full text:** of public attachments (PDF, Word, plain text, and files inside zips), in `data/text/`.
- **Each day's new filings:** in `data/daily/`.
- **Harvest state:** in `data/state.json`, including numbers still being rechecked.

Trade-secret versions are never public, and the harvester never downloads or stores a file whose name carries a trade-secret marker (TS). It lists that the file exists, because the Commission's own page does.

## How to check a record

Every record links to the Commission's own filing page and to the original file there. Each attachment that was read carries a SHA-256 fingerprint of the file as downloaded and the time it was downloaded, so anyone can download the original and confirm it is the same file. The text in `data/text/` is extracted by machine and can drop tables, columns or scanned pages; the original file is the record. A text that contains trade-secret brackets is marked for a person to confirm that the passage is redacted in the public version.

This archive shows what the Commission posted. It does not show that what a filing says is true.

## How a night works

1. Recheck every empty number from the last 30 days, because numbers are sometimes filled in late.
2. Walk forward from the highest number seen.
3. Stop for the night after 25 empty numbers in a row.
4. Commit what changed.

One request at a time, with a pause between requests.

## Running it

```
python -m harvester.run nightly --seed 229480
python -m harvester.run backfill --start 219000 --end 229500
python -m harvester.run one 229480
python -m unittest discover -s tests -t .
```

In GitHub Actions: **Nightly harvest** runs on a schedule, **Backfill** and **Probe one filing** run by hand from the Actions tab.

## The site

The record is published at records.gapublicservice.org, rebuilt from this repository after each harvest by `python -m harvester.site`.

- **Search** (`index.html`), **Dockets** (`dockets.html` and `docket/<number>/`), **Last night** (`today.html`).
- **Wire** (`wire.html`, feed `data/wire.json`). Up to 20 items from the last week, about 10 in view, newest first, each labeled by source. When more come in, lower priority drops first: Commission, then commissioners, utilities, Commission staff, other parties. Filings go in on their own. Statements come in through `send-a-quote.html` (Netlify form `wire-statement`) and go up only once approved by hand and added to `data/reference/wire-statements.json`. Each item has a Flag link (`flag.html`, Netlify form `wire-flag`); flagged items stay up until decided. The **Midday check** workflow looks for new filings at about noon Eastern on weekdays and logs them to `data/midday`; the next morning's run folds them into its log, so docket alerts still go out once.
- **Calendar** (`calendar.html`, the `calendar.ics` feed and `agenda/<meeting>/` pages). Events that aren't the Commission's come in through the submission form (`submit-event.html`, a Netlify Forms inbox on the follow service). Each is approved by hand before it is added to `data/reference/other-events.json`, and each is marked "Not a Commission event".
- **Regions** (`regions.html`), **Positions** (`positions.html`), **Legislature** (`legislature/`), **About** (`about.html`).
- **Corrections** (`corrections.html`): the corrections policy and a public correction log. Built, but held out of the site, its navigation and its footer until the policy text is written. The policy goes in `data/reference/corrections-policy.md` and log entries go in `data/reference/corrections.json` (date, page, what was wrong, what changed). Then set `ON = True` in `harvester/corrections.py`.

## Docket alerts

Anyone can follow a docket from the Follow page on gapublicservice.org. After each nightly harvest, `alerts/nightly.py` sends one short email for each followed docket that got new filings that night, to that docket's followers only. A night with no new filings sends nothing. Set `ENABLED = False` in that file to stop all alerts.

## Bills and disconnections (not live yet)

`harvester/household.py` builds a page of Georgia Power's typical residential bill
(the Commission's Residential Rate Survey at 1,000 kWh), bill changes the Commission
approved (from its orders, in `data/reference/bill-changes.json`), Georgia Power's
monthly residential disconnections for nonpayment (from the bad debt reports it files
in Docket 42516), and the Atlanta Gas Light base charge and typical marketer bills
(from the Commission's Marketers Pricing Index). The nightly harvest reads the reports
and pages into `data/household/`. The page is written to `_preview/` until
`data/reference/household.json` says `"live": true`.

## Not built yet

- Weekly cross-check against the Commission's advanced search counts.
- Text from older spreadsheet formats (.xls). Excel workbooks (.xlsx) are read.
