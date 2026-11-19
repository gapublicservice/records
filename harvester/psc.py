"""Fetch and parse Georgia PSC filing pages.

Every public filing has a page at
    https://psc.ga.gov/search/facts-document/?documentId=N
Filing numbers form one sequence across all dockets, so walking the numbers
forward finds every filing without a feed.
"""

from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from html.parser import HTMLParser

FILING_URL = "https://psc.ga.gov/search/facts-document/?documentId={id}"
DOCKET_URL = "https://psc.ga.gov/search/facts-docket/?docketId={id}"
USER_AGENT = "records-harvester/0.1 (public records archive)"

LABELS = {
    "company name": "company",
    "description": "description",
    "filed date": "filed_date",
    "received date": "received_date",
}

ATTACHMENT_RE = re.compile(
    r"https://services\.psc\.ga\.gov/api/v1/External/Public/Get/Document/DownloadFile/(\d+)/(\d+)",
    re.I,
)
DOCKET_RE = re.compile(r"facts-docket/\?docketId=(\d+)", re.I)

# Trade-secret versions are never public. A file whose name carries a TS
# marker is listed in the record but never downloaded or stored.
TS_RE = re.compile(r"(?:^|[^a-z0-9])(ts|trade[\s_-]*secret)(?:[^a-z0-9]|$)", re.I)


def is_trade_secret_name(name: str) -> bool:
    return bool(TS_RE.search(name or ""))


@dataclass
class Attachment:
    attachment_id: int
    name: str
    url: str
    trade_secret_marked: bool


@dataclass
class Filing:
    document_id: int
    url: str
    company: str | None = None
    description: str | None = None
    filed_date: str | None = None  # ISO yyyy-mm-dd
    received_date: str | None = None
    dockets: list[int] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class _Lines(HTMLParser):
    """Turns HTML into text lines and collects links with their text."""

    BLOCK = {"p", "div", "br", "li", "tr", "td", "th", "dt", "dd",
             "h1", "h2", "h3", "h4", "h5", "h6", "section", "table", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buf: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._link_text: list[str] = []
        self._skip = 0

    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        if text:
            self.lines.append(text)
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if tag in self.BLOCK:
            self._flush()
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._link_text = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._link_text).split())))
            self._href = None
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._skip:
            return
        self._buf.append(data)
        if self._href is not None:
            self._link_text.append(data)

    def close(self):
        super().close()
        self._flush()


def _iso(date: str | None) -> str | None:
    if not date:
        return None
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", date)
    if not m:
        return date.strip() or None
    mo, d, y = (int(x) for x in m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}"


def parse_filing(document_id: int, page: str) -> Filing | None:
    """Returns the filing, or None when the page holds no filing."""
    p = _Lines()
    p.feed(page)
    p.close()

    values: dict[str, str] = {}
    lines = p.lines
    for i, line in enumerate(lines):
        key = line.rstrip(":").strip().lower()
        if key in LABELS and line.endswith(":"):
            # Value is the next line that is not itself a label.
            for nxt in lines[i + 1:i + 4]:
                if nxt.rstrip(":").strip().lower() in LABELS or nxt.lower() == "attachments:":
                    break
                values[LABELS[key]] = nxt.strip()
                break
        else:
            # "Label: value" on one line.
            for label, attr in LABELS.items():
                if line.lower().startswith(label + ":") and attr not in values:
                    rest = line[len(label) + 1:].strip()
                    if rest:
                        values[attr] = rest

    if "filed_date" not in values and "description" not in values:
        return None

    f = Filing(document_id=document_id, url=FILING_URL.format(id=document_id))
    f.company = values.get("company")
    f.description = values.get("description")
    f.filed_date = _iso(values.get("filed_date"))
    f.received_date = _iso(values.get("received_date"))

    seen = set()
    for href, text in p.links:
        href = html.unescape(href)
        m = ATTACHMENT_RE.search(href)
        if m and int(m.group(1)) == document_id:
            aid = int(m.group(2))
            if aid in seen:
                continue
            seen.add(aid)
            f.attachments.append(Attachment(
                attachment_id=aid, name=text, url=m.group(0),
                trade_secret_marked=is_trade_secret_name(text)))
            continue
        d = DOCKET_RE.search(href)
        if d and int(d.group(1)) not in f.dockets:
            f.dockets.append(int(d.group(1)))
    return f


class Fetcher:
    """Polite HTTP: one request at a time, a pause between, retries on errors."""

    def __init__(self, pause: float = 1.0, retries: int = 3, timeout: int = 60):
        self.pause = pause
        self.retries = retries
        self.timeout = timeout
        self._last = 0.0

    def get(self, url: str, max_bytes: int | None = None) -> bytes:
        err: Exception | None = None
        for attempt in range(self.retries):
            wait = self.pause - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    if max_bytes is not None:
                        size = r.headers.get("Content-Length")
                        if size and int(size) > max_bytes:
                            raise TooLarge(int(size))
                        data = r.read(max_bytes + 1)
                        if len(data) > max_bytes:
                            raise TooLarge(len(data))
                        return data
                    return r.read()
            except TooLarge:
                raise
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise
                err = e
            except Exception as e:  # network trouble
                err = e
            time.sleep(5 * (attempt + 1))
        raise err  # type: ignore[misc]

    def filing(self, document_id: int) -> tuple[Filing | None, str]:
        try:
            page = self.get(FILING_URL.format(id=document_id)).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, ""
            raise
        return parse_filing(document_id, page), page


class TooLarge(Exception):
    pass
