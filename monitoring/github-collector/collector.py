"""
GitHub PR metrics exporter for Prometheus.

Collects Lead Time, Cycle Time, Reviewer CR Rate, Acceptance Pass Rate,
Rework Count, and WIP (open PR count) from the GitHub API.

Environment variables:
  GITHUB_TOKEN  - GitHub personal access token or App token (required)
  GITHUB_REPO   - owner/repo (default: shingo-ops/salesanchor)
  PR_LOOKBACK   - number of recent closed PRs to analyze (default: 30)
  PORT          - HTTP port to expose metrics (default: 8000)
  COLLECT_INTERVAL - seconds between collections (default: 300)
"""

import os
import time
import logging
from datetime import datetime, timezone

import requests
from prometheus_client import Gauge, start_http_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = os.environ.get("GITHUB_REPO", "shingo-ops/salesanchor")
PR_LOOKBACK = int(os.environ.get("PR_LOOKBACK", "30"))
PORT = int(os.environ.get("PORT", "8000"))
COLLECT_INTERVAL = int(os.environ.get("COLLECT_INTERVAL", "300"))

API_BASE = "https://api.github.com"
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Metrics
lead_time = Gauge(
    "github_pr_lead_time_seconds",
    "Median time from PR creation to merge (seconds)",
    ["repo"],
)
cycle_time = Gauge(
    "github_pr_cycle_time_seconds",
    "Median time from PR creation to first approval (seconds)",
    ["repo"],
)
cr_rate = Gauge(
    "github_reviewer_change_request_rate",
    "Ratio of CHANGES_REQUESTED reviews to total reviews",
    ["repo"],
)
pass_rate = Gauge(
    "github_acceptance_pass_rate",
    "Ratio of PRs merged without any CHANGES_REQUESTED to total merged PRs",
    ["repo"],
)
rework_count = Gauge(
    "github_pr_rework_count_total",
    "Total additional pushes after first review across recent PRs",
    ["repo"],
)
open_pr_count = Gauge(
    "github_pr_open_count",
    "Number of currently open PRs (WIP)",
    ["repo"],
)


def _get(path: str, params: dict | None = None) -> dict | list:
    url = f"{API_BASE}{path}"
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    mid = len(sorted_v) // 2
    if len(sorted_v) % 2 == 0:
        return (sorted_v[mid - 1] + sorted_v[mid]) / 2
    return sorted_v[mid]


def collect() -> None:
    log.info("Collecting GitHub PR metrics for %s", GITHUB_REPO)

    # Open PRs (WIP count)
    open_data = _get(f"/repos/{GITHUB_REPO}/pulls", {"state": "open", "per_page": 100})
    open_pr_count.labels(repo=GITHUB_REPO).set(len(open_data))

    # Closed/merged PRs
    closed_prs = _get(
        f"/repos/{GITHUB_REPO}/pulls",
        {"state": "closed", "per_page": PR_LOOKBACK, "sort": "updated", "direction": "desc"},
    )
    merged_prs = [pr for pr in closed_prs if pr.get("merged_at")]

    if not merged_prs:
        log.warning("No merged PRs found in last %d closed PRs", PR_LOOKBACK)
        return

    lead_times: list[float] = []
    cycle_times: list[float] = []
    total_reviews = 0
    cr_reviews = 0
    clean_merges = 0
    total_rework = 0

    for pr in merged_prs:
        pr_number = pr["number"]
        created_at = _parse_dt(pr["created_at"])
        merged_at = _parse_dt(pr["merged_at"])

        # Lead Time: created → merged
        lead_times.append((merged_at - created_at).total_seconds())

        # Reviews for this PR
        reviews = _get(f"/repos/{GITHUB_REPO}/pulls/{pr_number}/reviews")
        has_cr = False
        first_approval_at: datetime | None = None

        for review in reviews:
            state = review["state"]
            total_reviews += 1
            if state == "CHANGES_REQUESTED":
                cr_reviews += 1
                has_cr = True
            if state == "APPROVED" and first_approval_at is None:
                first_approval_at = _parse_dt(review["submitted_at"])

        # Cycle Time: created → first approval
        if first_approval_at:
            cycle_times.append((first_approval_at - created_at).total_seconds())

        # Clean merge (no CR)
        if not has_cr:
            clean_merges += 1

        # Rework: commits pushed after PR was created (proxy: total commits - 1)
        commits = _get(f"/repos/{GITHUB_REPO}/pulls/{pr_number}/commits")
        rework = max(0, len(commits) - 1)
        total_rework += rework

    lead_time.labels(repo=GITHUB_REPO).set(_median(lead_times))
    cycle_time.labels(repo=GITHUB_REPO).set(_median(cycle_times))
    cr_rate.labels(repo=GITHUB_REPO).set(cr_reviews / total_reviews if total_reviews else 0.0)
    pass_rate.labels(repo=GITHUB_REPO).set(clean_merges / len(merged_prs))
    rework_count.labels(repo=GITHUB_REPO).set(total_rework)

    log.info(
        "Done: lead=%.0fs cycle=%.0fs cr_rate=%.2f pass_rate=%.2f rework=%d open=%d",
        _median(lead_times),
        _median(cycle_times),
        cr_reviews / total_reviews if total_reviews else 0.0,
        clean_merges / len(merged_prs),
        total_rework,
        len(open_data),
    )


def main() -> None:
    start_http_server(PORT)
    log.info("Metrics server started on :%d", PORT)

    while True:
        try:
            collect()
        except Exception:
            log.exception("Collection failed")
        time.sleep(COLLECT_INTERVAL)


if __name__ == "__main__":
    main()
