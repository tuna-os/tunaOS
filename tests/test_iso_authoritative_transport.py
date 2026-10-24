"""Exercise the bounded RFC014 caller without real credentials or network I/O."""
import base64
import copy
import io
import json
import http.client
import re
from pathlib import Path
import socket
import sys
import urllib.error
import urllib.request

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = str(ROOT / "scripts")
sys.path.insert(0, SCRIPTS)
try:
    import iso_artifact_transport as ARTIFACT  # noqa: E402
    import iso_authoritative_transport as CALLER  # noqa: E402
finally:
    sys.path.remove(SCRIPTS)

CASE = json.loads((ROOT / "tests/fixtures/iso-artifact-transport-v1/case.json").read_text())
ARTIFACT_ORIGIN = "https://artifacts.example.test"
TOKEN = "synthetic-token"


class Clock:
    def __init__(self):
        self.now = 100.0
        self.advance = 0.0

    def __call__(self):
        return self.now


class FakeResponse:
    def __init__(self, data, url, *, status=200, headers=None, read_error=None, clock=None):
        self.data = io.BytesIO(data)
        self.url = url
        self.status = status
        self.headers = dict(headers or {})
        self.headers.setdefault("Content-Length", str(len(data)))
        self.read_error = read_error
        self.clock = clock
        self.closed = False
        self.timeouts = []
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        if self.clock is not None:
            self.clock.now += self.clock.advance
        if self.read_error is not None:
            raise self.read_error
        return self.data.read(size)

    def close(self):
        self.closed = True

    def geturl(self):
        return self.url

    def settimeout(self, timeout):
        self.timeouts.append(timeout)


class FakeServerOpener:
    """Return queued server responses while recording exact client requests."""

    def __init__(self, responses=(), error=None):
        self.responses = list(responses)
        self.error = error
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def network_policy(**changes):
    values = {
        "artifact_redirect_origins": (ARTIFACT_ORIGIN,),
        "connect_timeout_seconds": 3,
        "idle_timeout_seconds": 5,
        "total_timeout_seconds": 30,
        "max_json_bytes": 64 * 1024,
        "max_object_bytes": 64 * 1024,
        "max_total_bytes": 1024 * 1024,
    }
    values.update(changes)
    return CALLER.ReviewedNetworkPolicy(**values)


def reviewed(case):
    return ARTIFACT.ReviewedPolicy(**case["policy"])


def selected(case):
    return ARTIFACT.ArtifactSelection(**case["selection"])


def response(value, url=CALLER.API_ORIGIN + "/fixture", **kwargs):
    return FakeResponse(encode(value), url, **kwargs)


def fake_servers(case, *, clock=None):
    run = f"{CALLER.API_ORIGIN}/repos/tuna-os/iso-builder/actions/runs/{case['selection']['run_id']}"
    artifact = (
        f"{CALLER.API_ORIGIN}/repos/tuna-os/iso-builder/actions/artifacts/"
        f"{case['selection']['artifact_id']}"
    )
    api = FakeServerOpener(
        [
            response(case["currentBefore"], run),
            response(case["attempt"], run + "/attempts/1"),
            response(case["artifact"], artifact),
            response(case["artifactAfter"], artifact),
            response(case["currentAfter"], run),
        ]
    )
    archive_response = FakeResponse(
        base64.b64decode(case["archiveBase64"], validate=True),
        ARTIFACT_ORIGIN + "/signed/archive.zip",
        clock=clock,
    )
    archive = FakeServerOpener([archive_response])
    objects = FakeServerOpener()
    return (api, archive, objects), archive_response


def transport(case, *, policy=None, retained=None, openers=None, clock=None):
    return CALLER.AuthoritativeTransport(
        reviewed(case),
        selected(case),
        policy or network_policy(),
        TOKEN,
        retained,
        _openers=openers or fake_servers(case)[0],
        _clock=clock or Clock(),
    )


def test_authoritative_caller_uses_only_selected_endpoints_and_existing_validator():
    case = copy.deepcopy(CASE)
    openers, archive_response = fake_servers(case)

    result = CALLER.verify_authoritative_artifact_snapshot(
        reviewed(case),
        selected(case),
        network_policy(),
        TOKEN,
        _openers=openers,
        _clock=Clock(),
    )

    api, archive, objects = openers
    run_path = f"/repos/tuna-os/iso-builder/actions/runs/{case['selection']['run_id']}"
    artifact_path = f"/repos/tuna-os/iso-builder/actions/artifacts/{case['selection']['artifact_id']}"
    assert [call[0].full_url for call in api.calls] == [
        CALLER.API_ORIGIN + run_path,
        CALLER.API_ORIGIN + run_path + "/attempts/1",
        CALLER.API_ORIGIN + artifact_path,
        CALLER.API_ORIGIN + artifact_path,
        CALLER.API_ORIGIN + run_path,
    ]
    assert [call[0].full_url for call in archive.calls] == [
        CALLER.API_ORIGIN + artifact_path + "/zip"
    ]
    assert objects.calls == []
    assert all(call[0].get_header("Authorization") == "Bearer " + TOKEN for call in api.calls)
    assert archive.calls[0][0].get_header("Authorization") == "Bearer " + TOKEN
    assert archive_response.closed
    assert result == case["expectedResult"]
    assert result["authentication"] == "not_authenticated"
    assert not {"qualified", "qualification", "admitted"} & result.keys()


@pytest.mark.parametrize(
    "snapshot,path,value",
    [
        ("currentBefore", ("repository", "fork"), True),
        ("currentBefore", ("head_repository", "full_name"), "fork/iso-builder"),
        ("currentBefore", ("pull_requests",), [{"number": 1}]),
        ("currentBefore", ("workflow_id",), 1),
        ("currentBefore", ("event",), "pull_request"),
        ("currentBefore", ("repository", "full_name"), "tuna-os/other"),
        ("attempt", ("head_sha",), "e" * 40),
        ("currentBefore", ("path",), ".github/workflows/other.yml"),
        ("currentBefore", ("head_sha",), "f" * 40),
        ("artifact", ("expired",), True),
    ],
)
def test_untrusted_producer_metadata_rejects_before_archive(snapshot, path, value):
    case = copy.deepcopy(CASE)
    target = case[snapshot]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    openers, archive_response = fake_servers(case)

    with pytest.raises(ARTIFACT.ArtifactVerificationError):
        CALLER.verify_authoritative_artifact_snapshot(
            reviewed(case), selected(case), network_policy(), TOKEN, _openers=openers, _clock=Clock()
        )

    assert openers[1].calls == []
    assert not archive_response.closed


@pytest.mark.parametrize(
    "snapshot,field,value",
    [
        ("artifactAfter", "size_in_bytes", 167),
        ("currentAfter", "run_attempt", 2),
        ("currentAfter", "conclusion", "failure"),
    ],
)
def test_changed_metadata_and_reruns_reject_after_closed_archive(snapshot, field, value):
    case = copy.deepcopy(CASE)
    case[snapshot][field] = value
    openers, archive_response = fake_servers(case)

    with pytest.raises(ARTIFACT.ArtifactVerificationError):
        CALLER.verify_authoritative_artifact_snapshot(
            reviewed(case), selected(case), network_policy(), TOKEN, _openers=openers, _clock=Clock()
        )

    assert len(openers[1].calls) == 1
    assert archive_response.closed


@pytest.mark.parametrize(
    "method,value",
    [
        ("get_json", "https://api.github.com/repos/tuna-os/iso-builder/actions/runs/latest"),
        ("get_json", "/repos/tuna-os/iso-builder/actions/runs/900000000001/attempts/2"),
        ("open_archive", "https://candidate.invalid/archive.zip"),
        ("open_archive", "/repos/tuna-os/iso-builder/actions/artifacts/1/zip"),
    ],
)
def test_transport_rejects_unselected_and_receipt_controlled_endpoints(method, value):
    case = copy.deepcopy(CASE)
    openers, _ = fake_servers(case)
    client = transport(case, openers=openers)

    with pytest.raises(CALLER.AuthoritativeTransportError, match="endpoint_rejected"):
        getattr(client, method)(value)

    assert all(not opener.calls for opener in openers)


def test_artifact_redirect_allows_one_reviewed_origin_without_forwarding_credential():
    handler = CALLER._ArtifactRedirect((ARTIFACT_ORIGIN,))
    request = urllib.request.Request(CALLER.API_ORIGIN + "/artifact", method="GET")
    request.add_unredirected_header("Authorization", "Bearer secret")

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        ARTIFACT_ORIGIN + "/signed/value?signature=synthetic",
    )

    assert redirected.full_url == ARTIFACT_ORIGIN + "/signed/value?signature=synthetic"
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("Accept-encoding") == "identity"


def test_artifact_redirect_normalizes_explicit_default_https_port():
    handler = CALLER._ArtifactRedirect((ARTIFACT_ORIGIN,))
    request = urllib.request.Request(CALLER.API_ORIGIN + "/artifact", method="GET")
    target = "https://artifacts.example.test:443/signed/value"

    redirected = handler.redirect_request(request, None, 302, "Found", {}, target)

    assert redirected.full_url == target


@pytest.mark.parametrize(
    "source,target",
    [
        (CALLER.API_ORIGIN + "/artifact", "https://evil.invalid/value"),
        (CALLER.API_ORIGIN + "/artifact", "http://artifacts.example.test/value"),
        (CALLER.API_ORIGIN + "/artifact", "https://user@artifacts.example.test/value"),
        (ARTIFACT_ORIGIN + "/first", ARTIFACT_ORIGIN + "/second"),
    ],
)
def test_redirect_rejects_wrong_origin_insecure_credentials_and_second_hop(source, target):
    handler = CALLER._ArtifactRedirect((ARTIFACT_ORIGIN,))
    request = urllib.request.Request(source, method="GET")
    response = FakeResponse(b"", source)

    with pytest.raises(CALLER.AuthoritativeTransportError):
        handler.redirect_request(request, response, 302, "Found", {}, target)

    assert response.closed


class RecordingFile(io.BytesIO):
    """Raw HTTP bytes behind a real ``http.client.HTTPResponse``."""

    def __init__(self, data):
        super().__init__(data)
        self.body_reads = 0

    def read(self, size=-1):
        self.body_reads += 1
        return super().read(size)


class FakeSocket:
    def __init__(self, data):
        self.file = RecordingFile(data)

    def makefile(self, _mode):
        return self.file


class FakeHTTPSServer(urllib.request.BaseHandler):
    """Serve queued raw HTTP responses to a real urllib opener chain."""

    handler_order = 50  # ahead of ProxyHandler/HTTPSHandler: never touch a network

    def __init__(self, exchanges):
        self.exchanges = list(exchanges)
        self.requests = []
        self.files = []

    def https_open(self, request):
        url, status, headers, body = self.exchanges.pop(0)
        assert request.full_url == url
        self.requests.append((request.full_url, dict(request.header_items())))
        lines = [f"HTTP/1.1 {status} {http.client.responses[status]}"]
        lines += [f"{name}: {value}" for name, value in headers.items()]
        lines.append(f"Content-Length: {len(body)}")
        raw = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
        sock = FakeSocket(raw)
        result = http.client.HTTPResponse(sock, method=request.get_method())
        result.begin()
        result.url = request.full_url
        result.msg = result.reason
        self.files.append(sock.file)
        return result


def test_real_urllib_chain_redirects_once_without_credential_or_redirect_drain():
    case = copy.deepcopy(CASE)
    run = f"{CALLER.API_ORIGIN}/repos/tuna-os/iso-builder/actions/runs/{case['selection']['run_id']}"
    artifact = (
        f"{CALLER.API_ORIGIN}/repos/tuna-os/iso-builder/actions/artifacts/"
        f"{case['selection']['artifact_id']}"
    )
    signed = ARTIFACT_ORIGIN + "/signed/archive.zip?signature=synthetic"
    api_server = FakeHTTPSServer(
        (url, 200, {}, encode(case[name]))
        for url, name in (
            (run, "currentBefore"),
            (run + "/attempts/1", "attempt"),
            (artifact, "artifact"),
            (artifact, "artifactAfter"),
            (run, "currentAfter"),
        )
    )
    archive_server = FakeHTTPSServer(
        [
            (artifact + "/zip", 302, {"Location": signed}, b"r" * 4096),
            (signed, 200, {}, base64.b64decode(case["archiveBase64"], validate=True)),
        ]
    )
    openers = (
        urllib.request.build_opener(CALLER._NoRedirect(), api_server),
        urllib.request.build_opener(CALLER._ArtifactRedirect((ARTIFACT_ORIGIN,)), archive_server),
        urllib.request.build_opener(CALLER._NoRedirect(), FakeHTTPSServer(())),
    )

    result = CALLER.verify_authoritative_artifact_snapshot(
        reviewed(case), selected(case), network_policy(), TOKEN, _openers=openers, _clock=Clock()
    )

    assert result == case["expectedResult"]
    assert result["authentication"] == "not_authenticated"
    assert api_server.exchanges == [] and archive_server.exchanges == []
    assert all(h["Authorization"] == "Bearer " + TOKEN for _, h in api_server.requests)
    (first_url, first), (second_url, second) = archive_server.requests
    assert (first_url, first["Authorization"]) == (artifact + "/zip", "Bearer " + TOKEN)
    assert second_url == signed
    assert "Authorization" not in second
    redirect_file, archive_file = archive_server.files
    assert redirect_file.closed
    assert redirect_file.body_reads == 0
    assert archive_file.closed
    assert all(f.closed for f in api_server.files)


def test_metadata_and_object_redirect_rejection_closes_response():
    response = FakeResponse(b"", CALLER.API_ORIGIN + "/metadata")

    with pytest.raises(CALLER.AuthoritativeTransportError, match="redirect_rejected"):
        CALLER._NoRedirect().redirect_request(
            urllib.request.Request(CALLER.API_ORIGIN + "/metadata"),
            response,
            302,
            "Found",
            {},
            CALLER.API_ORIGIN + "/elsewhere",
        )

    assert response.closed


def retained_policy():
    return ARTIFACT.RetainedMediaPolicy(
        endpoint="https://" + "a" * 32 + ".r2.cloudflarestorage.com",
        bucket="tunaos-candidates",
        manifest_sha256="sha256:" + "1" * 64,
        media_sha256="sha256:" + "2" * 64,
        media_size_bytes=32,
        receipt_sha256="sha256:" + "3" * 64,
        receipt_path="qualification/browser-v2.json",
    )


def test_r2_object_uses_exact_configured_key_without_github_credential():
    case = copy.deepcopy(CASE)
    retained = retained_policy()
    prefix = (
        f"browser-iso/candidates/{case['selection']['run_id']}/1/"
        "yellowfin-gnome/s1/"
    )
    url = retained.endpoint + "/" + retained.bucket + "/" + prefix + "manifest.json"
    object_response = FakeResponse(b"{}", url)
    openers = (FakeServerOpener(), FakeServerOpener(), FakeServerOpener([object_response]))
    client = transport(case, retained=retained, openers=openers)

    with client.open_object(prefix + "manifest.json") as stream:
        assert stream.read() == b"{}"

    request = openers[2].calls[0][0]
    assert request.full_url == url
    assert request.get_header("Authorization") is None
    assert object_response.closed


@pytest.mark.parametrize(
    "key",
    [
        "https://candidate.invalid/manifest.json",
        "browser-iso/candidates/900000000099/1/yellowfin-gnome/s1/manifest.json",
        "browser-iso/candidates/900000000001/1/yellowfin-gnome/s1/../secret",
        "browser-iso/candidates/900000000001/1/yellowfin-gnome/s1/chunks/latest",
    ],
)
def test_r2_object_rejects_candidate_urls_cross_run_keys_and_nonexact_members(key):
    case = copy.deepcopy(CASE)
    openers = (FakeServerOpener(), FakeServerOpener(), FakeServerOpener())
    client = transport(case, retained=retained_policy(), openers=openers)

    with pytest.raises(CALLER.AuthoritativeTransportError, match="endpoint_rejected"):
        client.open_object(key)

    assert openers[2].calls == []


def test_connect_timeout_is_classified_before_any_response():
    case = copy.deepcopy(CASE)
    error = urllib.error.URLError(socket.timeout("synthetic connect stall"))
    api = FakeServerOpener(error=error)
    client = transport(case, openers=(api, FakeServerOpener(), FakeServerOpener()))
    path = f"/repos/tuna-os/iso-builder/actions/runs/{case['selection']['run_id']}"

    with pytest.raises(CALLER.AuthoritativeTransportError, match="connect_timeout"):
        client.get_json(path)

    assert api.calls[0][1] == 3


def test_idle_timeout_closes_stream_and_never_reaches_post_metadata():
    case = copy.deepcopy(CASE)
    archive_response = FakeResponse(
        b"",
        ARTIFACT_ORIGIN + "/signed/archive.zip",
        read_error=socket.timeout("synthetic idle stall"),
    )
    openers, _ = fake_servers(case)
    openers = (openers[0], FakeServerOpener([archive_response]), openers[2])

    with pytest.raises(CALLER.AuthoritativeTransportError, match="idle_timeout"):
        CALLER.verify_authoritative_artifact_snapshot(
            reviewed(case), selected(case), network_policy(), TOKEN, _openers=openers, _clock=Clock()
        )

    assert archive_response.closed
    assert len(openers[0].calls) == 3
    assert archive_response.timeouts == [5]


def test_total_timeout_after_a_read_closes_stream():
    case = copy.deepcopy(CASE)
    clock = Clock()
    clock.advance = 2
    archive_response = FakeResponse(
        base64.b64decode(case["archiveBase64"], validate=True),
        ARTIFACT_ORIGIN + "/signed/archive.zip",
        clock=clock,
    )
    openers, _ = fake_servers(case)
    openers = (openers[0], FakeServerOpener([archive_response]), openers[2])

    with pytest.raises(CALLER.AuthoritativeTransportError, match="total_timeout"):
        CALLER.verify_authoritative_artifact_snapshot(
            reviewed(case),
            selected(case),
            network_policy(total_timeout_seconds=1),
            TOKEN,
            _openers=openers,
            _clock=clock,
        )

    assert archive_response.closed
    assert len(openers[0].calls) == 3


@pytest.mark.parametrize(
    "policy,error",
    [
        (network_policy(max_json_bytes=2), "response_byte_limit"),
        (network_policy(max_total_bytes=2), "total_byte_limit"),
    ],
)
def test_declared_response_and_shared_total_byte_limits_close_response(policy, error):
    case = copy.deepcopy(CASE)
    path = f"/repos/tuna-os/iso-builder/actions/runs/{case['selection']['run_id']}"
    api_response = response(case["currentBefore"], CALLER.API_ORIGIN + path)
    api = FakeServerOpener([api_response])
    client = transport(
        case,
        policy=policy,
        openers=(api, FakeServerOpener(), FakeServerOpener()),
    )

    with pytest.raises(CALLER.AuthoritativeTransportError, match=error):
        client.get_json(path)

    assert api_response.closed


def test_undeclared_body_cannot_cross_total_byte_limit_and_is_closed():
    case = copy.deepcopy(CASE)
    path = f"/repos/tuna-os/iso-builder/actions/runs/{case['selection']['run_id']}"
    api_response = FakeResponse(
        b"{}x",
        CALLER.API_ORIGIN + path,
        headers={"Content-Length": "3"},
    )
    del api_response.headers["Content-Length"]
    api = FakeServerOpener([api_response])
    client = transport(
        case,
        policy=network_policy(max_total_bytes=2),
        openers=(api, FakeServerOpener(), FakeServerOpener()),
    )

    with pytest.raises(CALLER.AuthoritativeTransportError, match="total_byte_limit"):
        client.get_json(path)

    assert api_response.read_sizes == [3]
    assert api_response.closed


def test_compressed_or_wrong_origin_response_is_rejected_and_closed():
    case = copy.deepcopy(CASE)
    path = f"/repos/tuna-os/iso-builder/actions/runs/{case['selection']['run_id']}"
    responses = [
        FakeResponse(b"{}", CALLER.API_ORIGIN + path, headers={"Content-Encoding": "gzip"}),
        FakeResponse(b"{}", "https://evil.invalid/value"),
    ]
    for api_response in responses:
        api = FakeServerOpener([api_response])
        client = transport(case, openers=(api, FakeServerOpener(), FakeServerOpener()))
        with pytest.raises(CALLER.AuthoritativeTransportError):
            client.get_json(path)
        assert api_response.closed


@pytest.mark.parametrize(
    "changes",
    [
        {"artifact_redirect_origins": ("http://artifacts.example.test",)},
        {"artifact_redirect_origins": (ARTIFACT_ORIGIN + "/path",)},
        {"artifact_redirect_origins": ("https://user@artifacts.example.test",)},
        {"connect_timeout_seconds": 0},
        {"idle_timeout_seconds": 301},
        {"total_timeout_seconds": float("inf")},
        {"max_json_bytes": CALLER.MAX_JSON_BYTES + 1},
        {"max_object_bytes": ARTIFACT.MAX_CHUNK_BYTES + 1},
        {"max_total_bytes": CALLER.MAX_TOTAL_BYTES + 1},
        {"artifact_redirect_origins": (["https://artifacts.example.test"],)},
        {"artifact_redirect_origins": (None,)},
        {"artifact_redirect_origins": (ARTIFACT_ORIGIN, ARTIFACT_ORIGIN)},
        {"artifact_redirect_origins": [ARTIFACT_ORIGIN]},
        {"artifact_redirect_origins": ()},
    ],
)
def test_network_policy_cannot_disable_origin_time_or_byte_bounds(changes):
    case = copy.deepcopy(CASE)
    with pytest.raises(CALLER.AuthoritativeTransportError):
        transport(case, policy=network_policy(**changes))


def test_explicit_rerun_selection_fails_before_opening_any_endpoint():
    case = copy.deepcopy(CASE)
    case["selection"]["attempt"] = 2
    openers, _ = fake_servers(case)

    with pytest.raises(CALLER.AuthoritativeTransportError, match="attempt_rejected"):
        CALLER.verify_authoritative_artifact_snapshot(
            reviewed(case), selected(case), network_policy(), TOKEN, _openers=openers, _clock=Clock()
        )

    assert all(not opener.calls for opener in openers)



def test_policy_for_another_repository_fails_before_opening_any_endpoint():
    case = copy.deepcopy(CASE)
    case["policy"]["repository"] = "fork/iso-builder"
    openers, _ = fake_servers(case)

    with pytest.raises(CALLER.AuthoritativeTransportError, match="policy_mismatch"):
        CALLER.verify_authoritative_artifact_snapshot(
            reviewed(case), selected(case), network_policy(), TOKEN, _openers=openers, _clock=Clock()
        )

    assert all(not opener.calls for opener in openers)


def test_retained_prefix_matches_the_v2_schema_manifest_key():
    schema = json.loads((ROOT / "schemas/iso-media-provenance-v2.schema.json").read_text())
    patterns = []

    def collect(node):
        if isinstance(node, dict):
            pattern = node.get("pattern")
            if isinstance(pattern, str) and "browser-iso/candidates" in pattern:
                patterns.append(pattern)
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(schema)
    key = ARTIFACT.retained_candidate_prefix(900000000001, 1) + "manifest.json"
    assert patterns
    assert all(re.fullmatch(pattern, key) for pattern in patterns)