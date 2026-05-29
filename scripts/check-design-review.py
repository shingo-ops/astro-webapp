#!/usr/bin/env python3
"""Validate that a PR has design review evidence for its current head commit."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


APPROVAL_RE = re.compile(r"(?:Design Review|設計レビュー)\s*[:：]\s*APPROVED\b", re.IGNORECASE)
SHA_RE = re.compile(r"(?:Commit|Head SHA|SHA|コミット)\s*[:：]\s*([0-9a-f]{7,40})\b", re.IGNORECASE)
REQUIRED_FIELDS = {
    "Reviewer": re.compile(r"(?:Reviewer|レビュアー)\s*[:：]\s*\S+", re.IGNORECASE),
    "Scope": re.compile(r"(?:Scope|対象)\s*[:：]\s*\S+", re.IGNORECASE),
    "Evidence": re.compile(r"(?:Evidence|エビデンス)\s*[:：]\s*\S+", re.IGNORECASE),
}


def _trusted_actors() -> set[str]:
    raw = os.getenv("DESIGN_REVIEW_TRUSTED_ACTORS", "shingo-ops,Hikky-dev")
    return {actor.strip() for actor in raw.split(",") if actor.strip()}


def _comment_candidates(pr: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for index, comment in enumerate(pr.get("comments") or [], start=1):
        body = comment.get("body") or ""
        author = (comment.get("author") or {}).get("login", "unknown")
        if body.strip():
            candidates.append(
                {
                    "source": f"PR comment #{index}",
                    "author": author,
                    "body": body,
                    "kind": "comment",
                }
            )

    for index, review in enumerate(pr.get("reviews") or [], start=1):
        body = review.get("body") or ""
        author = (review.get("author") or {}).get("login", "unknown")
        if body.strip():
            candidates.append(
                {
                    "source": f"PR review #{index}",
                    "author": author,
                    "body": body,
                    "kind": "review",
                    "state": str(review.get("state") or "").upper(),
                }
            )

    return candidates


def _matches_current_head(text: str, head_sha: str) -> bool:
    for match in SHA_RE.finditer(text):
        approved_sha = match.group(1).lower()
        if head_sha.startswith(approved_sha) or approved_sha.startswith(head_sha):
            return True
    return False


def _missing_fields(text: str) -> list[str]:
    return [name for name, pattern in REQUIRED_FIELDS.items() if pattern.search(text) is None]


def _valid_approval(text: str, head_sha: str) -> tuple[bool, str]:
    if APPROVAL_RE.search(text) is None:
        return False, "approval marker missing"
    missing = _missing_fields(text)
    if missing:
        return False, "required field(s) missing: " + ", ".join(missing)
    if not _matches_current_head(text, head_sha):
        return False, "current head SHA missing or stale"
    return True, "approved"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pr_json", type=Path, help="Path to gh pr view JSON output")
    args = parser.parse_args()

    try:
        pr = json.loads(args.pr_json.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"::error::PR metadata JSON could not be read: {exc}")
        return 1

    number = pr.get("number", "(unknown)")
    title = pr.get("title", "(untitled)")
    head_sha = str(pr.get("headRefOid") or "").lower()
    pr_author = (pr.get("author") or {}).get("login", "unknown")
    trusted = _trusted_actors()

    print(f"Checking design review evidence for PR #{number}: {title}")
    print(f"Current head SHA: {head_sha}")
    print(f"PR author: {pr_author}")
    print(f"Trusted design reviewers: {', '.join(sorted(trusted))}")

    if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        print("::error::PR headRefOid is missing or invalid.")
        return 1

    seen_approval = False
    for candidate in _comment_candidates(pr):
        source = candidate["source"]
        author = candidate["author"]
        text = candidate["body"]
        kind = candidate["kind"]

        if APPROVAL_RE.search(text):
            seen_approval = True
        if author == pr_author:
            print(f"Skipping {source} by {author}: PR author cannot self-approve")
            continue
        if author not in trusted:
            print(f"Skipping {source} by {author}: author is not a trusted design reviewer")
            continue
        if kind == "review" and candidate.get("state") != "APPROVED":
            print(f"Skipping {source} by {author}: review state is {candidate.get('state')}")
            continue
        valid, reason = _valid_approval(text, head_sha)
        if valid:
            print(f"OK: design review approval found in {source} by {author}")
            return 0
        if APPROVAL_RE.search(text):
            print(f"Skipping {source} by {author}: {reason}")

    if APPROVAL_RE.search(pr.get("body") or ""):
        print("PR body contains a design review marker, but body text is not accepted as reviewer evidence.")

    print("::error::Current-head design review approval is missing.")
    print("")
    print("A trusted reviewer must add a PR comment or GitHub Review containing:")
    print("")
    print("Design Review: APPROVED")
    print("Reviewer: <trusted reviewer or agent>")
    print(f"Commit: {head_sha}")
    print("Scope: <what was reviewed>")
    print("Evidence: <facts checked, CI/logs/docs/ADR references>")
    print("")
    print("The Commit value must match the latest PR head SHA after every push.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
