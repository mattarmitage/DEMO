# Delivery watchdog (sandbox)

A read-only agent prototype that spots delivery risk by comparing Jira with GitHub.

**v0.1 check:** Jira tickets that are "In Progress" but have no GitHub activity
(commit, PR title/branch/body) mentioning the ticket key for N days.

It never comments, transitions tickets or messages anyone. It writes `report.md`
and, in GitHub Actions, shows the report on the run summary page.

## Try it with no credentials

```bash
pip install -r requirements.txt
python watchdog.py --demo
```

## Run it live

1. Create a **new, throwaway** GitHub repo and push these files to it.
2. Create a free Jira project (key e.g. `DEMO`) with a few tickets set to In Progress.
3. In the repo, open a few PRs/commits whose title, branch or message includes the key
   (e.g. `DEMO-2: add staging config`), and leave others quiet on purpose.
4. Make a Jira API token (id.atlassian.com > Security > API tokens).
5. Add repo secrets (Settings > Secrets and variables > Actions):
   `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`. The project key is set in the workflow file.
   (`GITHUB_TOKEN` is provided automatically.)
6. Actions tab > Delivery watchdog > Run workflow.

Locally, export the same variables plus `GITHUB_TOKEN` and `GITHUB_REPO=owner/repo`, then run
`python watchdog.py --days 3`.

## Known limits

- Matching is by ticket key in text, so work that never mentions its key looks "stale".
- Only the last 30 days of commits and the latest 100 PRs are checked.
- Currently deterministic. The LLM step (judging which flags matter, drafting the
  risk note) is the planned next version.

## Roadmap

1. Claude API step: triage flagged tickets, guess likely cause, draft the risk summary.
2. PRs waiting too long for review.
3. Merged PRs whose ticket isn't Done.
4. PRs with no ticket key.
