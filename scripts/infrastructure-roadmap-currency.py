#!/usr/bin/env python3
"""Report infrastructure roadmap currency from GitHub; never infer readiness."""
import datetime as dt
import json
import subprocess

PROJECTS = ('tacklebox', 'corral', 'remora', 'iso-builder', 'bluefin-cli')


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True))


def age_days(timestamp, today):
    return (today - dt.datetime.fromisoformat(timestamp.replace('Z', '+00:00')).date()).days


def report(today):
    quarter_start = dt.date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
    lines = [f'# Infrastructure roadmap currency — {today}', '',
             'Generated from default-branch history and open P0 issues. File currency is not release readiness.', '',
             '| Project | Last ROADMAP commit | Quarterly review |',
             '| --- | --- | --- |']
    escalations = []
    for project in PROJECTS:
        repo = f'tuna-os/{project}'
        branch = api(f'repos/{repo}')['default_branch']
        from urllib.parse import urlencode
        query = urlencode({'path': 'ROADMAP.md', 'sha': branch, 'per_page': 1})
        commits = api(f'repos/{repo}/commits?{query}')
        if commits:
            commit = commits[0]
            date = commit['commit']['committer']['date'][:10]
            state = 'review due' if dt.date.fromisoformat(date) < quarter_start else 'changed this quarter; verify content'
            source = f"[{date}]({commit['html_url']})"
        else:
            source, state = 'no history', 'review due: missing ROADMAP'
        lines.append(f'| {project} | {source} | {state} |')
        # Paginate: an old P0 must not disappear behind the first 100 issues.
        page = 1
        while True:
            issues = api(f'repos/{repo}/issues?state=open&per_page=100&page={page}')
            for issue in issues:
                if 'pull_request' in issue:
                    continue
                if any(label['name'].casefold() == 'p0' for label in issue['labels']):
                    age = age_days(issue['created_at'], today)
                    if age >= 7:
                        escalations.append(f"- [{repo}#{issue['number']}]({issue['html_url']}): open {age} days; review roadmap relevance and escalate to repository maintainer.")
            if len(issues) < 100:
                break
            page += 1
    lines += ['', '## P0 review candidates (open at least seven days)', '']
    lines += escalations or ['No matching open P0 issues. Unlabelled blockers require manual review.']
    lines += ['', 'Issue age is measured from creation, not label assignment. Candidates require human review; this report does not send notifications or declare decisions resolved.']
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    print(report(dt.datetime.now(dt.timezone.utc).date()), end='')
