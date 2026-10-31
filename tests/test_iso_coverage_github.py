from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib.iso_coverage_github import GitHubCoverageAPI, SafeRedirect, REPOSITORY, WORKFLOW_PATH, MAX_ARCHIVE_BYTES


class Response(BytesIO):
    def __init__(self, payload, url='https://api.github.com/response', status=200, headers=None):
        super().__init__(payload)
        self.url, self.status = url, status
        self.headers = {} if headers is None else headers

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, response):
        self.response, self.requests = response, []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def api(payload=b'{}', **kwargs):
    opener = Opener(Response(payload, **kwargs))
    return GitHubCoverageAPI('secret-token', opener), opener


def test_resolve_exact_workflow_and_readonly_request():
    client, opener = api(json.dumps({'id': 42, 'path': WORKFLOW_PATH}).encode())
    assert client.resolve_workflow_id() == 42
    request, timeout = opener.requests[0]
    assert request.get_method() == 'GET'
    assert request.data is None
    assert request.get_header('Authorization') == 'Bearer secret-token'
    assert timeout == 30
    assert request.full_url.endswith('/actions/workflows/iso-coverage-plan.yml')


def test_wrong_workflow_path_rejected():
    client, _ = api(b'{"id":42,"path":".github/workflows/evil.yml"}')
    with pytest.raises(ValueError, match='trusted producer'):
        client.resolve_workflow_id()


def test_runs_query_encoded_and_scope_fixed():
    client, opener = api(b'{"total_count":0,"workflow_runs":[]}')
    client.list_runs(REPOSITORY, 42, 'main', '2026-10-23T12:00:00Z', 2, 50)
    query = parse_qs(urlsplit(opener.requests[0][0].full_url).query)
    assert query == {'branch': ['main'], 'status': ['completed'], 'created': ['>=2026-10-23T12:00:00Z'], 'page': ['2'], 'per_page': ['50']}


@pytest.mark.parametrize('args', [('foreign/repo', 1, 'main', '2026-10-23T00:00:00Z', 1, 100),
                                  (REPOSITORY, 1, 'feature', '2026-10-23T00:00:00Z', 1, 100),
                                  (REPOSITORY, True, 'main', '2026-10-23T00:00:00Z', 1, 100),
                                  (REPOSITORY, 1, 'main', 'today', 1, 100),
                                  (REPOSITORY, 1, 'main', '2026-10-23T00:00:00Z', 0, 100),
                                  (REPOSITORY, 1, 'main', '2026-10-23T00:00:00Z', 1, 101)])
def test_invalid_scope_rejected_before_request(args):
    client, opener = api()
    with pytest.raises(ValueError):
        client.list_runs(*args)
    assert not opener.requests


def test_artifact_byte_cap_even_without_content_length():
    client, _ = api(b'a' * (MAX_ARCHIVE_BYTES + 1))
    with pytest.raises(ValueError, match='size bound'):
        client.download_artifact(REPOSITORY, 7)


def test_declared_oversize_rejected_before_read():
    client, opener = api(b'a', headers={'Content-Length': str(MAX_ARCHIVE_BYTES + 1)})
    with pytest.raises(ValueError, match='size bound'):
        client.download_artifact(REPOSITORY, 7)


def test_blob_download_allowed_but_metadata_origin_change_rejected():
    client, _ = api(b'zip', url='https://artifacts.blob.core.windows.net/signed')
    assert client.download_artifact(REPOSITORY, 7) == b'zip'
    client, _ = api(b'{}', url='https://evil.example/json')
    with pytest.raises(ValueError, match='outside the API'):
        client.list_artifacts(REPOSITORY, 7, 1, 100)


@pytest.mark.parametrize('target', ['http://blob.example/a', 'file:///tmp/a', 'https://user:pass@blob.example/a'])
def test_unsafe_redirect_rejected(target):
    req = Request('https://api.github.com/a', headers={'Authorization': 'Bearer secret-token'})
    with pytest.raises(ValueError, match='HTTPS'):
        SafeRedirect().redirect_request(req, None, 302, 'Found', {}, target)


def test_crossorigin_redirect_strips_credentials_and_never_restores():
    handler = SafeRedirect()
    request = Request('https://api.github.com/a', headers={'Authorization': 'Bearer secret-token', 'Cookie': 'private=1'})
    redirected = handler.redirect_request(request, None, 302, 'Found', {}, 'https://blob.example/a')
    assert redirected.get_header('Authorization') is None
    assert redirected.get_header('Cookie') is None
    returned = handler.redirect_request(redirected, None, 302, 'Found', {}, 'https://api.github.com/b')
    assert returned.get_header('Authorization') is None


def test_sameorigin_redirect_retains_api_token():
    request = Request('https://api.github.com/a', headers={'Authorization': 'Bearer secret-token'})
    redirected = SafeRedirect().redirect_request(request, None, 302, 'Found', {}, 'https://api.github.com/b')
    assert redirected.get_header('Authorization') == 'Bearer secret-token'


@pytest.mark.parametrize('payload', [b'not json', b'[]', b'null'])
def test_bad_json_fails_closed(payload):
    client, _ = api(payload)
    with pytest.raises(ValueError):
        client.list_artifacts(REPOSITORY, 7, 1, 100)


def test_http_error_does_not_expose_url_token_or_response_body():
    error = HTTPError('https://example/secret-signed-url', 403, 'secret-token', {}, None)
    client = GitHubCoverageAPI('secret-token', Opener(error))
    with pytest.raises(OSError) as raised:
        client.download_artifact(REPOSITORY, 7)
    assert str(raised.value) == 'GitHub API request failed with HTTP 403'


def test_env_token_supported_without_global_mutation(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'test-token')
    client = GitHubCoverageAPI(opener=Opener(Response(b'{}')))
    assert client._token == 'test-token'


@pytest.mark.parametrize('token', ['', None, 'bad\nvalue'])
def test_missing_or_unsafe_token_rejected(monkeypatch, token):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    with pytest.raises(ValueError):
        GitHubCoverageAPI(token, Opener(Response(b'{}')))


def test_main_sha_independent_of_receipts():
    client, opener = api(json.dumps({'name': 'main', 'commit': {'sha': 'a' * 40}}).encode())
    assert client.main_sha() == 'a' * 40
    assert opener.requests[0][0].full_url.endswith('/branches/main')


@pytest.mark.parametrize('document', [{'name': 'other', 'commit': {'sha': 'a' * 40}},
                                      {'name': 'main', 'commit': {'sha': 'latest'}},
                                      {'name': 'main', 'commit': None}])
def test_main_sha_requires_exact_branch_and_commit(document):
    client, _ = api(json.dumps(document).encode())
    with pytest.raises(ValueError, match='branch identity'):
        client.main_sha()


def test_get_attempt_exact_endpoint_and_readonly():
    client, opener = api(b'{"id":123,"run_attempt":2}')
    assert client.get_attempt(REPOSITORY, 123, 2) == {'id': 123, 'run_attempt': 2}
    request, _ = opener.requests[0]
    assert request.full_url == 'https://api.github.com/repos/tuna-os/tunaOS/actions/runs/123/attempts/2'
    assert request.get_method() == 'GET'


@pytest.mark.parametrize('repository,run_id,attempt', [
    ('other/repo', 123, 2), (REPOSITORY, 0, 2), (REPOSITORY, True, 2),
    (REPOSITORY, 123, 0), (REPOSITORY, 123, -1), (REPOSITORY, 123, True),
    (REPOSITORY, 123, '2'),
])
def test_get_attempt_validates_before_request(repository, run_id, attempt):
    client, opener = api()
    with pytest.raises(ValueError):
        client.get_attempt(repository, run_id, attempt)
    assert not opener.requests


def test_list_jobs_attempt_scoped_endpoint_and_pagination():
    client, opener = api(b'{"total_count":0,"jobs":[]}')
    client.list_jobs(REPOSITORY, 123, 2, 3, 50)
    request, _ = opener.requests[0]
    url = urlsplit(request.full_url)
    assert url.path == '/repos/tuna-os/tunaOS/actions/runs/123/attempts/2/jobs'
    assert parse_qs(url.query) == {'page': ['3'], 'per_page': ['50']}
    assert request.get_method() == 'GET'


@pytest.mark.parametrize('arguments', [
    ('foreign/repo', 1, 1, 1, 50), (REPOSITORY, 0, 1, 1, 50),
    (REPOSITORY, 1, False, 1, 50), (REPOSITORY, 1, 1, 0, 50),
    (REPOSITORY, 1, 1, 1, 101),
])
def test_list_jobs_scope_validated_before_request(arguments):
    client, opener = api()
    with pytest.raises(ValueError):
        client.list_jobs(*arguments)
    assert not opener.requests


def test_transport_deadline_stops_further_requests():
    ticks = [10]
    opener = Opener(Response(b'{}'))
    client = GitHubCoverageAPI('token', opener, deadline_seconds=300, clock=lambda: ticks[0])
    ticks[0] = 311
    with pytest.raises(OSError, match='deadline exhausted'):
        client.list_artifacts(REPOSITORY, 1, 1, 50)
    assert not opener.requests


def test_request_timeout_clamped_to_remaining_budget():
    ticks = [10]
    opener = Opener(Response(b'{}'))
    client = GitHubCoverageAPI('token', opener, deadline_seconds=300, clock=lambda: ticks[0])
    ticks[0] = 305
    client.list_artifacts(REPOSITORY, 1, 1, 50)
    assert opener.requests[0][1] == 5


def test_response_after_deadline_cannot_be_accepted():
    ticks = [0]
    class SlowOpener(Opener):
        def open(self, request, timeout):
            ticks[0] = 301
            return super().open(request, timeout)
    client = GitHubCoverageAPI('token', SlowOpener(Response(b'{}')), clock=lambda: ticks[0])
    with pytest.raises(OSError, match='deadline exhausted'):
        client.list_artifacts(REPOSITORY, 1, 1, 50)


@pytest.mark.parametrize('duration', [0, -1, True, float('nan'), float('inf'), '300'])
def test_invalid_transport_deadline_rejected(duration):
    with pytest.raises(ValueError, match='finite positive'):
        GitHubCoverageAPI('token', Opener(Response(b'{}')), deadline_seconds=duration)
