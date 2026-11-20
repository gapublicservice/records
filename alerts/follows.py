"""Read-only: list the Docket labels in Ghost and how many members carry each.

  python -m alerts.follows

Prints label names and counts only, never member names or addresses.
"""
from alerts.ghost import Ghost


def main() -> None:
    labels = Ghost().call("GET", "/labels/", limit="all", include="count.members")["labels"]
    rows = [(l["name"], (l.get("count") or {}).get("members", 0)) for l in labels if l["name"].lower().startswith("docket")]
    if not rows:
        print("no Docket labels yet: nobody has followed a docket")
    for name, n in sorted(rows):
        print(f"{name}: {n} member(s)")


if __name__ == "__main__":
    main()
