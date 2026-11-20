# Georgia bills in the public record

The `legis` package adds Georgia General Assembly bills to the same record as
the PSC filings: every bill's status history, sponsors, committees, roll-call
votes and every version of its text, with version-to-version comparisons.

- **Source:** the General Assembly's public web service
  (webservices.legis.ga.gov), which needs no login. Each record links to the
  bill's page on legis.ga.gov.
- **Scope of the public pages:** a published rule, in `legis/scope.py`: bills
  that amend Title 46 (public utilities), name the Public Service Commission,
  go to a utilities committee, or change statewide election law (Title 21).
  Local acts and honorary resolutions are left out.
- **Expert views:** shown only when both sides have a view quoted from a
  public source, checked against a saved copy of that source (or, for
  hearing video, against a saved transcript with a link to the moment), and
  approved by a named reviewer. See `legis/views.py`.
- **Neutral:** these pages report the record. Public Service takes no
  position on any bill.

```
python -m legis.run session 2025_26 --text   # full pass
python -m legis.run new 2025_26               # new bills, and changes to tracked ones
python -m legis.run probe 69287               # save one real response as a test fixture
python -m legis.site 2025_26                  # bill pages and widgets in _site/legislature/
python -m legis.video pull <url> --id <id>    # hearing video, then transcribe, find
python -m legis.sources save <url> --id <id>  # saved copy of a cited source
python -m unittest discover -s tests -t .
```
