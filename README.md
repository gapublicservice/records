# Georgia PSC public records

A nightly copy of every public filing at the Georgia Public Service Commission, made searchable.

The Commission has no single feed of new filings. Every filing has its own page, and filing numbers run in one sequence across all dockets. So the harvester walks the numbers forward each night and stores what it finds.

## What it keeps

- **Every filing:** company, description, filed and received dates, docket, and the list of attachments, in `data/filings/`.
- **Full text:** of public attachments (PDF, Word, plain text, and files inside zips), in `data/text/`.
- **Each day's new filings:** in `data/daily/`.
- **Harvest state:** in `data/state.json`, including numbers still being rechecked.

Trade-secret versions are never public, and the harvester never downloads or stores a file whose name carries a trade-secret marker (TS). It lists that the file exists, because the Commission's own page does.

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

## Not built yet

- Weekly cross-check against the Commission's advanced search counts.
- Docket titles and industry.
- Spreadsheet text.
- Disagreement and location flags, and the public site.
