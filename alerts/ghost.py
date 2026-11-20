"""Small client for Ghost's Admin API, standard library only.

The Admin API key comes from the GHOST_ADMIN_KEY secret and never appears
in the repo or in logs. Only the GitHub Actions workflows use it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = "/ghost/api/admin"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def token(key: str, now: int | None = None) -> str:
    kid, secret = key.split(":")
    now = int(now if now is not None else time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": kid}
    payload = {"iat": now, "exp": now + 300, "aud": "/admin/"}
    msg = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    sig = hmac.new(bytes.fromhex(secret), msg.encode(), hashlib.sha256).digest()
    return f"{msg}.{_b64(sig)}"


class Ghost:
    def __init__(self, url: str | None = None, key: str | None = None):
        self.url = (url or os.environ.get("GHOST_URL") or "https://gapublicservice.org").rstrip("/")
        self.key = key or os.environ["GHOST_ADMIN_KEY"]

    def call(self, method: str, path: str, body: dict | None = None, _hops: int = 0, **params) -> dict:
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        req = urllib.request.Request(
            f"{self.url}{API}{path}{q}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Ghost {token(self.key)}",
                     "Content-Type": "application/json",
                     "Accept-Version": "v6.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                self._follow(r.geturl(), path)
        except urllib.error.HTTPError as err:
            # Ghost(Pro) can answer the public domain with a redirect to the
            # site's admin domain. urllib follows that for GET but not for
            # PUT, POST or DELETE, so switch to the admin domain and retry.
            if err.code in (301, 302, 307, 308) and _hops < 2 and self._follow(err.headers.get("Location", ""), path):
                return self.call(method, path, body, _hops=_hops + 1, **params)
            detail = err.read().decode(errors="replace")[:500]
            if err.code in (301, 302, 307, 308):
                loc = urllib.parse.urlsplit(err.headers.get("Location", ""))
                detail = f"redirect to host {loc.hostname!r}, path {loc.path!r}"
            raise SystemExit(f"Ghost said {err.code} to {method} {path}: {detail}")
        return json.loads(raw) if raw else {}

    def _follow(self, location: str, path: str) -> bool:
        """Move to the redirect target's origin if it is the same API path on
        https and on the site's own domain or a ghost.io host."""
        u = urllib.parse.urlsplit(location)
        host = (u.hostname or "").lower()
        ok_host = host == "gapublicservice.org" or host.endswith(".gapublicservice.org") or host.endswith(".ghost.io")
        if u.scheme != "https" or not ok_host or f"{API}{path}" not in u.path:
            return False
        prefix = u.path[: u.path.index(f"{API}{path}")]
        new = f"https://{u.netloc}{prefix}"
        if new == self.url:
            return False
        self.url = new
        return True
