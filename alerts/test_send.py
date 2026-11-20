"""One-off live test: can a docket alert go to one label and nobody else?

Steps, each printed to the log without any email address:
1. find the test member by the address in the GHOST_TEST_MEMBER secret;
2. pick the newsletter the member is subscribed to (the default one first);
3. add the label "Test docket alert" to that member only;
4. count who the send would reach and stop unless it is exactly one member;
5. with --send, publish one email-only post for one docket to that label;
6. remove the label from the member and delete the label.
Without --send it does every step except the email.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .ghost import Ghost

LABEL = "Test docket alert"
SLUG = "test-docket-alert"
ROOT = Path(__file__).resolve().parent.parent


def latest_filing(docket: str) -> dict:
    best = None
    for line in (ROOT / "data" / "index" / "filings.jsonl").open():
        r = json.loads(line)
        if docket in [str(d) for d in (r.get("dockets") or [r.get("docket")])]:
            if best is None or (r.get("filed_date") or "") > (best.get("filed_date") or ""):
                best = r
    return best or {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docket", default="56002")
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args()

    g = Ghost()
    email = os.environ["GHOST_TEST_MEMBER"].strip()

    found = g.call("GET", "/members/", filter=f"email:'{email}'", include="labels,newsletters")["members"]
    if len(found) != 1:
        sys.exit("No Ghost member has that address. Nothing was changed.")
    m = found[0]
    subs = m.get("newsletters") or []
    if not subs:
        sys.exit("That member isn't subscribed to any newsletter, so no alert could reach them. Nothing was changed.")
    nl = sorted(subs, key=lambda n: n.get("sort_order", 0))[0]
    # The member record lists newsletters without their slug; read it.
    nl = g.call("GET", f"/newsletters/{nl['id']}/")["newsletters"][0]
    print(f"Member found; newsletter used: {nl['name']}")

    labels = [{"name": l["name"]} for l in m.get("labels") or [] if l["slug"] != SLUG]
    g.call("PUT", f"/members/{m['id']}/", {"members": [{"labels": labels + [{"name": LABEL}]}]})
    print("Test label added to that member")
    post_id = None
    try:
        reach = g.call("GET", "/members/", filter=f"label:{SLUG}+newsletters.id:'{nl['id']}'+email_disabled:0", limit=1)
        total = reach["meta"]["pagination"]["total"]
        print(f"Members the send would reach: {total}")
        if total != 1:
            sys.exit("Stopped before sending: the label reaches someone other than the test member.")
        if not args.send:
            print("Dry run: no email sent")
            return
        title = f"Test alert: docket {args.docket}"
        for old in g.call("GET", "/posts/", filter="status:draft", limit="all", fields="id,title,email_only")["posts"]:
            if old.get("title") == title and old.get("email_only"):
                g.call("DELETE", f"/posts/{old['id']}/")
                print("Earlier unsent test draft deleted")
        f = latest_filing(args.docket)
        doc = f.get("document_id")
        html = (f"<p>This is a one-time test of docket alerts from the Public Service record. "
                f"It went only to the test address.</p>"
                f"<p><strong>Docket {args.docket}</strong>, newest filing ({f.get('filed_date', '')}): "
                f"{(f.get('description') or '').strip()}</p>"
                f"<p><a href=\"https://records.gapublicservice.org/docket/{args.docket}/\">Docket page on the record</a></p>")
        post = g.call("POST", "/posts/", {"posts": [{"title": title, "html": html,
                                                     "status": "draft", "email_only": True}]}, source="html")["posts"][0]
        post_id = post["id"]
        pub = g.call("PUT", f"/posts/{post_id}/", {"posts": [{"status": "published", "updated_at": post["updated_at"]}]},
                     newsletter=nl["slug"], email_segment=f"label:{SLUG}")["posts"][0]
        print(f"Email-only post published; recipient filter stored as: {pub.get('email_segment')}")
        for _ in range(20):
            p = g.call("GET", f"/posts/{post_id}/", include="email")["posts"][0]
            em = p.get("email") or {}
            if em.get("status") in ("submitted", "failed"):
                break
            time.sleep(15)
        print(f"Email status: {em.get('status')}; recipients: {em.get('email_count')}; "
              f"delivered so far: {em.get('delivered_count')}; failed: {em.get('failed_count')}")
        if em.get("status") != "submitted" or em.get("email_count") != 1:
            sys.exit("The send did not finish as one email to one member; see the line above.")
    finally:
        if post_id:
            p = g.call("GET", f"/posts/{post_id}/")["posts"][0]
            if p.get("status") == "draft":
                g.call("DELETE", f"/posts/{post_id}/")
                print("Unsent test draft deleted")
        m2 = g.call("GET", f"/members/{m['id']}/", include="labels")["members"][0]
        keep = [{"name": l["name"]} for l in m2.get("labels") or [] if l["slug"] != SLUG]
        g.call("PUT", f"/members/{m['id']}/", {"members": [{"labels": keep}]})
        for l in g.call("GET", "/labels/", filter=f"slug:{SLUG}")["labels"]:
            g.call("DELETE", f"/labels/{l['id']}/")
        print("Test label removed from the member and deleted")


if __name__ == "__main__":
    main()
