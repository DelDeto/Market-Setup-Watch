#!/usr/bin/env python3
"""Recover stale Market Setup Watch schedule using repository-scoped GITHUB_TOKEN.

This launches only the existing manual-analysis scanner workflow.
It never places orders. There is a cooldown to prevent a dispatch storm.
"""
from datetime import datetime, timezone
import json
import os
import sys
import urllib.error
import urllib.request

MAX_SCANNER_AGE_SECONDS = 45 * 60
RECENT_RUN_COOLDOWN_SECONDS = 40 * 60
REPO = "DelDeto/Market-Setup-Watch"
FLOW = "market-setup-watch.yml"


def parse_time(value):
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def needs_recovery(scanner_age, recent_run_ages):
    """Never dispatch if a scanner run began within the cooldown window."""
    if scanner_age is not None and scanner_age <= MAX_SCANNER_AGE_SECONDS:
        return False
    return not any(age <= RECENT_RUN_COOLDOWN_SECONDS for age in recent_run_ages)


def request_json(url, token=None, data=None):
    headers = {
        "User-Agent": "ATLAS-Scanner-Self-Heal/3.0",
        "Accept": "application/vnd.github+json,application/json",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=None if data is None else json.dumps(data).encode(),
        headers=headers, method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=24) as res:
        if res.status == 204:
            return {}
        return json.load(res)


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ATLAS recovery unavailable: GITHUB_TOKEN not provided")
        return 1
    base = os.environ.get(
        "ATLAS_URL", "https://atlas-market-terminal.duc-nguyen-ndd127.workers.dev"
    ).rstrip("/")
    now = datetime.now(timezone.utc)
    dashboard = request_json(base + "/api/dashboard")
    scanner = dashboard.get("scanner") or {}
    last = parse_time(scanner.get("updatedAt"))
    age = (now - last).total_seconds() if last else None
    if age is not None and age <= MAX_SCANNER_AGE_SECONDS:
        print("ATLAS scanner healthy: source age %.1f min" % (age / 60))
        return 0

    repo = os.environ.get("GITHUB_REPOSITORY", REPO)
    if repo.lower() != REPO.lower():
        print("ATLAS scanner recovery disabled in untrusted repo:", repo)
        return 1
    api = "https://api.github.com/repos/" + REPO + "/actions/workflows/" + FLOW
    runs = request_json(api + "/runs?per_page=12", token=token)
    ages = []
    for run in runs.get("workflow_runs") or []:
        created = parse_time(run.get("created_at"))
        if created:
            ages.append((now - created).total_seconds())
    if not needs_recovery(age, ages):
        print("ATLAS scanner stale but a recent run exists; no duplicate dispatch",
              "age minutes:", round(age / 60, 1) if age else None)
        return 0

    request_json(api + "/dispatches", token=token, data={"ref": "main"})
    print("ATLAS scanner stale: dispatched ONE recovery run;",
          "scanner age minutes:", round(age / 60, 1) if age else None)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        print("ATLAS scanner recovery API failed:", type(exc).__name__,
              getattr(exc, "code", ""), str(exc)[:150])
        sys.exit(1)
