"""Point legis at a temporary folder for tests, without changing RECORDS_ROOT
for the rest of the test run (the PSC harvester reads it too)."""
import os
import shutil
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="legis-test-"))
ROSTER = Path(__file__).resolve().parents[2] / "data" / "legislature" / "views" / "roster.json"
(TMP / "data" / "legislature" / "views").mkdir(parents=True, exist_ok=True)
shutil.copy(ROSTER, TMP / "data" / "legislature" / "views" / "roster.json")

_old = os.environ.get("RECORDS_ROOT")
os.environ["RECORDS_ROOT"] = str(TMP)
try:
    from legis import store, views, site  # noqa: F401  (fix their paths now)
finally:
    if _old is None:
        os.environ.pop("RECORDS_ROOT", None)
    else:
        os.environ["RECORDS_ROOT"] = _old
