"""Bounded GET-only GitHub reader for the fixed ISO coverage producer.

The caller must still validate run/artifact content with iso_coverage_artifacts.
This transport never interprets a successful API response as coverage evidence.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from lib.iso_coverage_artifacts import MAX_ARCHIVE_BYTES, REPOSITORY
from lib.iso_coverage_receipts import timestamp

API_ORIGIN = 'https://api.github.com'
WORKFLOW_PATH = '.github/workflows/iso-coverage-plan.yml'
MAX_JSON_BYTES = 8 * 1024 * 1024
REQUEST_TIMEOUT = 30


class SafeRedirect(HTTPRedirectHandler):
    """Never send the repository token to a redirected artifact/blob origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != 'https' or not target.hostname or target.username or target.password:
            raise ValueError('GitHub redirect must use credential-free HTTPS')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            # Strip on any origin change, including different ports. Once removed,
            # it is never restored if a subsequent redirect returns to GitHub.
            old = urlsplit(req.full_url)
            if (old.scheme, old.netloc) != (target.scheme, target.netloc):
                for header in ('Authorization', 'Cookie', 'Proxy-Authorization'):
                    redirected.remove_header(header)
        return redirected


class GitHubCoverageAPI:
    """Repository-scoped API matching discover_import's injectable interface.

    No retries hide missing history or repeatedly spend rate limits. Errors become
    visible incomplete-discovery diagnostics in the caller. Token values and
    redirected signed URLs are never included in the raised error text.
    """

    def __init__(self, token=None, opener=None, deadline_seconds=300, clock=None):
        self._token = os.environ.get('GITHUB_TOKEN', '') if token is None else token
        if not isinstance(self._token, str) or not self._token or any(c.isspace() for c in self._token):
            raise ValueError('a nonempty GITHUB_TOKEN is required')
        self._opener = opener if opener is not None else build_opener(SafeRedirect())
        if (isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, (int, float))
                or not math.isfinite(deadline_seconds) or deadline_seconds <= 0):
            raise ValueError('deadline_seconds must be a finite positive duration')
        self._clock = time.monotonic if clock is None else clock
        self._deadline = self._clock() + deadline_seconds

    def _remaining(self):
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise OSError('GitHub discovery transport deadline exhausted')
        return remaining

    @staticmethod
    def _repo(repository):
        if repository != REPOSITORY:
            raise ValueError('coverage lookup is restricted to the configured repository')

    @staticmethod
    def _positive(value, name):
        if type(value) is not int or value < 1:
            raise ValueError(f'{name} must be a positive integer')
        return value

    @classmethod
    def _pagination(cls, page, per_page):
        cls._positive(page, 'page')
        cls._positive(per_page, 'per_page')
        if per_page > 100:
            raise ValueError('per_page exceeds GitHub limit')

    def _get(self, path, query=None, binary=False):
        if not path.startswith('/repos/' + REPOSITORY + '/') or '?' in path or '#' in path:
            raise ValueError('unexpected GitHub API path')
        url = API_ORIGIN + path
        if query:
            url += '?' + urlencode(query)
        request = Request(url, method='GET', headers={
            'Authorization': 'Bearer ' + self._token,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'tunaos-iso-coverage-readonly',
        })
        limit = MAX_ARCHIVE_BYTES if binary else MAX_JSON_BYTES
        remaining = self._remaining()
        try:
            with self._opener.open(request, timeout=min(REQUEST_TIMEOUT, remaining)) as response:
                if response.status != 200:
                    raise ValueError('unexpected GitHub response status')
                final = urlsplit(response.geturl())
                if final.scheme != 'https' or final.username or final.password:
                    raise ValueError('unexpected response origin')
                # JSON metadata must stay at the API origin. Artifact ZIPs use
                # signed HTTPS redirects handled by SafeRedirect above.
                if not binary and (final.scheme, final.netloc) != ('https', 'api.github.com'):
                    raise ValueError('GitHub metadata redirected outside the API origin')
                advertised = response.headers.get('Content-Length')
                if advertised is not None:
                    try:
                        length = int(advertised)
                    except (ValueError, TypeError) as error:
                        raise ValueError('invalid response content length') from error
                    if length < 0 or length > limit:
                        raise ValueError('GitHub response exceeds size bound')
                self._remaining()
                payload = response.read(limit + 1)
                self._remaining()
                if len(payload) > limit:
                    raise ValueError('GitHub response exceeds size bound')
                if advertised is not None and len(payload) != length:
                    raise ValueError('GitHub response length mismatch')
        except HTTPError as error:
            raise OSError(f'GitHub API request failed with HTTP {error.code}') from None
        except (URLError, TimeoutError) as error:
            raise OSError('GitHub API request failed or timed out') from None
        if binary:
            return payload
        try:
            result = json.loads(payload)
        except (ValueError, UnicodeError) as error:
            raise ValueError('GitHub API returned invalid JSON') from error
        if not isinstance(result, dict):
            raise ValueError('GitHub API response must be an object')
        return result

    def main_sha(self):
        """Resolve current desired main checkout independently of receipt payloads."""
        document = self._get('/repos/' + REPOSITORY + '/branches/main')
        commit = document.get('commit')
        sha = commit.get('sha') if isinstance(commit, dict) else None
        if document.get('name') != 'main' or not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError('GitHub main branch identity is malformed')
        return sha

    def resolve_workflow_id(self):
        document = self._get('/repos/' + REPOSITORY + '/actions/workflows/iso-coverage-plan.yml')
        workflow_id = self._positive(document.get('id'), 'workflow ID')
        if document.get('path') != WORKFLOW_PATH:
            raise ValueError('GitHub workflow path does not match the trusted producer')
        return workflow_id

    def list_runs(self, repository, workflow_id, branch, since, page, per_page):
        self._repo(repository)
        self._positive(workflow_id, 'workflow ID')
        self._pagination(page, per_page)
        if branch != 'main':
            raise ValueError('only main producer runs are trusted')
        timestamp(since)
        return self._get(f'/repos/{REPOSITORY}/actions/workflows/{workflow_id}/runs', {
            'branch': 'main', 'status': 'completed', 'created': '>=' + since,
            'page': page, 'per_page': per_page,
        })

    def list_artifacts(self, repository, run_id, page, per_page):
        self._repo(repository)
        self._positive(run_id, 'run ID')
        self._pagination(page, per_page)
        return self._get(f'/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts', {
            'page': page, 'per_page': per_page,
        })

    def list_jobs(self, repository, run_id, attempt, page, per_page):
        """Read one attempt's bounded job page; importer validates skip claims."""
        self._repo(repository)
        self._positive(run_id, 'run ID')
        self._positive(attempt, 'run attempt')
        self._pagination(page, per_page)
        return self._get(f'/repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}/jobs', {
            'page': page, 'per_page': per_page,
        })

    def get_attempt(self, repository, run_id, attempt):
        """Read API-established metadata for one historical run attempt."""
        self._repo(repository)
        self._positive(run_id, 'run ID')
        self._positive(attempt, 'run attempt')
        return self._get(f'/repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}')

    def download_artifact(self, repository, artifact_id):
        self._repo(repository)
        self._positive(artifact_id, 'artifact ID')
        return self._get(f'/repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip', binary=True)
