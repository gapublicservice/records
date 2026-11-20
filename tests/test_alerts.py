import base64, hashlib, hmac, json

from alerts.ghost import token


def test_token_is_signed_for_admin_api():
    key = "6489:" + "11" * 32
    t = token(key, now=1000)
    head, body, sig = t.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)
    assert json.loads(base64.urlsafe_b64decode(pad(head)))["kid"] == "6489"
    claims = json.loads(base64.urlsafe_b64decode(pad(body)))
    assert claims == {"iat": 1000, "exp": 1300, "aud": "/admin/"}
    want = hmac.new(bytes.fromhex("11" * 32), f"{head}.{body}".encode(), hashlib.sha256).digest()
    assert base64.urlsafe_b64decode(pad(sig)) == want
