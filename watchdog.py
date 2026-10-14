#!/usr/bin/env python3
"""
Delivery watchdog (v0.1): read-only stale-ticket check for Jira + GitHub.

Finds Jira tickets that are "In Progress" but have no GitHub activity
(commits, PRs, branches) mentioning the ticket key for N days.

It only READS from Jira and GitHub and writes a report. It never comments,
transitions tickets, or messages anyone.

Usage:
    python watchdog.py --demo                 # run against sample_data.json
    python watchdog.py --days 3               # live run (needs env vars)

Env vars for live mode:
    JIRA_BASE_URL    e.g. https://yourname.atlassian.net
    JIRA_EMAIL       your Atlassian account email
    JIRA_API_TOKEN   Jira API token
    JIRA_PROJECT     project key, e.g. DEMO
    GITHUB_TOKEN     GitHub token with read access to the repo
    GITHUB_REPO      owner/repo, e.g. yourname/delivery-watchdog-sandbox
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

KEY_PATTERN = r"\b{project}-\d+\b"


# ---------- helpers ----------

def parse_ts(value):
    """Parse ISO timestamps from Jira/GitHub into aware datetimes."""
    value = value.replace("Z", "+00:00")
    # Jira uses +0000 (no colon); normalise so fromisoformat is happy
    value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)
    return datetime.fromisoformat(value)


def find_keys(text, pattern):
    return set(re.findall(pattern, text or "", flags=re.IGNORECASE))


# ---------- data sources ----------

def fetch_jira_in_progress(base_url, email, token, project):
    # Jira Cloud's current search endpoint is /rest/api/3/search/jql
    # (the older /rest/api/3/search was retired). If you get a 404/410,
    # check Atlassian's docs in case this has changed again.
    jql = f'project = {project} AND statusCategory = "In Progress" ORDER BY updated DESC'
    issues, next_token = [], None
    while True:
        params = {"jql": jql, "fields": "summary,status,assignee,updated", "maxResults": 50}
        if next_token:
            params["nextPageToken"] = next_token
        resp = requests.get(
            f"{base_url}/rest/api/3/search/jql",
            params=params,
            auth=(email, token),
            headers={"Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        for i in data.get("issues", []):
            f = i["fields"]
            issues.append({
                "key": i["key"],
                "summary": f["summary"],
                "status": f["status"]["name"],
                "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
                "updated": f["updated"],
            })
        next_token = data.get("nextPageToken")
        if not next_token or data.get("isLast", True):
            break
    return issues


def fetch_github_activity(repo, token, pattern, since):
    """Return a list of {key, when, source} events mentioning ticket keys."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    events = []

    # Pull requests (title, branch name, body)
    prs = requests.get(
        f"https://api.github.com/repos/{repo}/pulls",
        params={"state": "all", "sort": "updated", "direction": "desc", "per_page": 100},
        headers=headers, timeout=30,
    )
    prs.raise_for_status()
    for pr in prs.json():
        text = f'{pr["title"]} {pr["head"]["ref"]} {pr.get("body") or ""}'
        for key in find_keys(text, pattern):
            events.append({"key": key.upper(), "when": pr["updated_at"], "source": f'PR #{pr["number"]}'})

    # Commits on the default branch (message)
    commits = requests.get(
        f"https://api.github.com/repos/{repo}/commits",
        params={"since": since.isoformat(), "per_page": 100},
        headers=headers, timeout=30,
    )
    commits.raise_for_status()
    for c in commits.json():
        for key in find_keys(c["commit"]["message"], pattern):
            events.append({"key": key.upper(), "when": c["commit"]["author"]["date"],
                           "source": f'commit {c["sha"][:7]}'})
    return events


def load_demo(path):
    with open(path) as f:
        data = json.load(f)
    return data["jira_issues"], data["github_events"]


# ---------- checks ----------

def check_stale_tickets(issues, events, days, now):
    """Flag In Progress tickets with no GitHub activity in the last `days` days."""
    cutoff = now - timedelta(days=days)
    last_seen = {}
    for e in events:
        when = parse_ts(e["when"])
        key = e["key"].upper()
        if key not in last_seen or when > last_seen[key][0]:
            last_seen[key] = (when, e["source"])

    findings = []
    for issue in issues:
        seen = last_seen.get(issue["key"].upper())
        if seen is None:
            findings.append({**issue, "reason": "No GitHub activity found for this ticket",
                             "days_quiet": None})
        elif seen[0] < cutoff:
            quiet = (now - seen[0]).days
            findings.append({**issue, "reason": f"Last GitHub activity was {seen[1]}, {quiet} days ago",
                             "days_quiet": quiet})
    # Longest-quiet first; "never seen" first of all
    findings.sort(key=lambda f: (f["days_quiet"] is not None, -(f["days_quiet"] or 0)))
    return findings


# ---------- report ----------

def render_report(findings, total_in_progress, days, now):
    lines = [
        "# Delivery watchdog: stale ticket report",
        f"_Generated {now.strftime('%Y-%m-%d %H:%M UTC')} | threshold: {days} days | "
        f"{len(findings)} of {total_in_progress} In Progress tickets flagged_",
        "",
    ]
    if not findings:
        lines.append("Nothing flagged. All In Progress tickets have recent GitHub activity.")
        return "\n".join(lines)
    lines += ["| Ticket | Summary | Assignee | Why flagged |", "|---|---|---|---|"]
    for f in findings:
        lines.append(f'| {f["key"]} | {f["summary"]} | {f["assignee"]} | {f["reason"]} |')
    lines += [
        "",
        "_Caveat: a ticket with no matching activity may simply not mention its key "
        "in branch names, PR titles or commit messages. Check before nudging anyone._",
    ]
    return "\n".join(lines)


# ---------- main ----------

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--demo", action="store_true", help="use sample_data.json instead of live APIs")
    p.add_argument("--days", type=int, default=3, help="days of inactivity before flagging (default 3)")
    p.add_argument("--out", default="report.md", help="where to write the report")
    args = p.parse_args()

    if args.demo:
        # Fixed "now" so the demo output is reproducible
        now = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
        issues, events = load_demo(os.path.join(os.path.dirname(__file__), "sample_data.json"))
    else:
        now = datetime.now(timezone.utc)
        required = ["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT", "GITHUB_TOKEN", "GITHUB_REPO"]
        missing = [v for v in required if not os.environ.get(v)]
        if missing:
            sys.exit(f"Missing environment variables: {', '.join(missing)}")
        project = os.environ["JIRA_PROJECT"]
        pattern = KEY_PATTERN.format(project=re.escape(project))
        issues = fetch_jira_in_progress(
            os.environ["JIRA_BASE_URL"].rstrip("/"), os.environ["JIRA_EMAIL"],
            os.environ["JIRA_API_TOKEN"], project)
        events = fetch_github_activity(
            os.environ["GITHUB_REPO"], os.environ["GITHUB_TOKEN"], pattern,
            since=now - timedelta(days=30))

    findings = check_stale_tickets(issues, events, args.days, now)
    report = render_report(findings, len(issues), args.days, now)

    print(report)
    with open(args.out, "w") as f:
        f.write(report + "\n")

    # In GitHub Actions, also show the report on the run summary page
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write(report + "\n")


if __name__ == "__main__":
    main()
