# Delivery watchdog (sandbox)

A read-only agent prototype that spots delivery risk by comparing Jira with GitHub.

**Check:** Jira tickets that are "In Progress" but have no GitHub activity
(commit, PR title/branch/body) mentioning the ticket key for N days.

**AI triage (v0.2, optional):** if `ANTHROPIC_API_KEY` is set, Claude reads the flagged
tickets and adds a short summary for the PM, plus a severity, a likely cause and one
suggested next action per ticket. Anything it infers rather than knows is labelled "Guess:".
The report is sorted most-worrying first.

It never comments, transitions tickets or messages anyone. Claude's output is suggestions
inside the report; a human decides what to do. The script writes `report.md` and, in
GitHub Actions, shows the report on the run summary page.

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
6. Optional, for AI triage: add `ANTHROPIC_API_KEY` as a secret too.
7. Actions tab > Delivery watchdog > Run workflow.

Locally, export the same variables plus `GITHUB_TOKEN` and `GITHUB_REPO=owner/repo`, then run
`python watchdog.py --days 3` (add `--no-triage` to skip the Claude step).
`ANTHROPIC_MODEL` overrides the default model.

## Design notes

- **Human in the loop:** no write access is needed or used; the agent only reports.
- **Fails safe:** if the Claude call errors, the plain report is still produced and the
  error is noted in it.
- **Untrusted input:** ticket text is passed to Claude as data, the prompt tells it not to
  follow instructions found in tickets, and its output is only ever written into the report.
- **Data sharing:** flagged ticket keys, summaries, assignee names and activity dates are
  sent to the Anthropic API. Fine for a sandbox; check your client and data policies
  before pointing this at real projects.

## Known limits

- Matching is by ticket key in text, so work that never mentions its key looks "stale".
- Only the last 30 days of commits and the latest 100 PRs are checked.
- Triage only sees what the script sends it (no ticket comments or PR review state),
  so its suggestions are educated guesses.

## Roadmap

1. PRs waiting too long for review.
2. Merged PRs whose ticket isn't Done.
3. PRs with no ticket key.
4. Optional human-approved actions (e.g. draft a Jira comment for the PM to send).
