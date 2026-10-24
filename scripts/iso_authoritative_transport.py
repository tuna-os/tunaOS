"""Bounded read-only HTTP caller for the RFC014 artifact validators.

The caller accepts only independently supplied policy objects and exact selected
IDs. It never reads URLs, policy, credentials, or selection from a candidate.
Successful HTTP collection remains unqualified and keeps the existing
``authentication: not_authenticated`` result: HTTPS authenticates the endpoint,
not the separately supplied review decision or the browser/native evidence.
"""
from dataclasses import dataclass
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import iso_artifact_transport as artifact_transport


API_ORIGIN = "https://api.github.com"
USER_AGENT = "tunaos-rfc014-authoritative-transport/1"
MAX_JSON_BYTES = 1024 * 1024
MAX_READ_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = (
    artifact_transport.MAX_ISO_BYTES
    + artifact_transport.MAX_DIAGNOSTIC_BYTES
    + 8 * MAX_JSON_BYTES
)


class AuthoritativeTransportError(RuntimeError):
    """A network request cannot satisfy the reviewed transport policy."""

    def __init__(self, code, field):
        self.code = code
        self.field = field
        super().__init__(f"{code}: {field}")


@dataclass(frozen=True)
class ReviewedNetworkPolicy:
    """Reviewer-supplied HTTP limits and exact artifact redirect origins."""

    artifact_redirect_origins: tuple[str, ...]
    connect_timeout_seconds: float
    idle_timeout_seconds: float
    total_timeout_seconds: float
    max_json_bytes: int
    max_object_bytes: int
    max_total_bytes: int


class _Budget:
    def __init__(self, policy, clock):
        self.clock = clock
        self.deadline = clock() + policy.total_timeout_seconds
        self.remaining_bytes = policy.max_total_bytes

    def remaining_seconds(self):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise AuthoritativeTransportError("total_timeout", "transport")
        return remaining

    def consume(self, size):
        self.remaining_bytes -= size
        if self.remaining_bytes < 0:
            raise AuthoritativeTransportError("total_byte_limit", "transport")
        self.remaining_seconds()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _close_quietly(fp)
        raise AuthoritativeTransportError("redirect_rejected", "response.location")


class _ArtifactRedirect(urllib.request.HTTPRedirectHandler):
    """Allow one API-to-reviewed-origin redirect without forwarding secrets."""

    def __init__(self, allowed_origins):
        super().__init__()
        self.allowed_origins = frozenset(allowed_origins)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            if _url_origin(req.full_url) != API_ORIGIN:
                raise AuthoritativeTransportError("redirect_rejected", "response.location")
            if _url_origin(newurl) not in self.allowed_origins:
                raise AuthoritativeTransportError("redirect_origin", "response.location")
            if code not in (301, 302, 303, 307, 308):
                raise AuthoritativeTransportError("redirect_status", "response.status")
            redirected = urllib.request.Request(
                newurl,
                headers={
                    "Accept": "application/octet-stream",
                    "Accept-Encoding": "identity",
                    "User-Agent": USER_AGENT,
                },
                method="GET",
            )
        except Exception:
            _close_quietly(fp)
            raise
        # Close the redirect response here as well: urllib would otherwise
        # drain its body with an unbounded read() before following the hop.
        _close_quietly(fp)
        return redirected


class _BoundedResponse:
    """Context-managed response with shared wall-clock and byte budgets."""

    def __init__(self, response, budget, limit, idle_timeout, declared_length=None):
        self._response = response
        self._reader = _single_receive_reader(response)
        self._budget = budget
        self._remaining = limit
        self._declared_remaining = declared_length
        self._idle_timeout = idle_timeout
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, error_type, _error, _traceback):
        try:
            self.close()
        except Exception:
            if error_type is None:
                raise
        return False

    @property
    def closed(self):
        return self._closed

    def read(self, size=-1):
        if self._closed:
            raise AuthoritativeTransportError("closed_stream", "response")
        if type(size) is not int:
            raise AuthoritativeTransportError("invalid_read", "response")
        if size == 0:
            return b""
        if size > 0:
            return self._receive(size)
        chunks = []
        while chunk := self._receive(MAX_READ_BYTES):
            chunks.append(chunk)
        return b"".join(chunks)

    def _receive(self, size):
        """Do at most one underlying receive, bounded by the remaining deadline.

        ``read1`` returns after one socket receive, so a slow-drip body cannot
        extend a single call past ``total_timeout_seconds``; ``read`` would
        keep receiving, each time with a fresh socket timeout.
        """
        remaining_time = self._budget.remaining_seconds()
        isclosed = getattr(self._reader, "isclosed", None)
        if callable(isclosed) and isclosed() is True:
            # http.client drops its socket once the declared body is read; the
            # EOF read1 below would do no receive, so no timeout is needed.
            return b""
        total_deadline_bound = remaining_time <= self._idle_timeout
        timeout = min(self._idle_timeout, remaining_time)
        _set_response_timeout(self._response, self._reader, timeout)
        if self._declared_remaining == 0:
            return b""
        if self._budget.remaining_bytes == 0:
            raise AuthoritativeTransportError("total_byte_limit", "transport")
        allowed = min(self._remaining + 1, self._budget.remaining_bytes)
        if self._declared_remaining is not None:
            allowed = min(allowed, self._declared_remaining)
        requested = min(size, allowed, MAX_READ_BYTES)
        try:
            chunk = self._reader.read1(requested)
        except (socket.timeout, TimeoutError) as exc:
            code = "total_timeout" if total_deadline_bound else "idle_timeout"
            raise AuthoritativeTransportError(code, "response.read") from exc
        if type(chunk) is not bytes or len(chunk) > requested:
            raise AuthoritativeTransportError("invalid_response", "response.read")
        self._remaining -= len(chunk)
        if self._declared_remaining is not None:
            self._declared_remaining -= len(chunk)
        self._budget.consume(len(chunk))
        if self._remaining < 0:
            raise AuthoritativeTransportError("response_byte_limit", "response")
        return chunk

    def close(self):
        if not self._closed:
            self._closed = True
            self._response.close()


class AuthoritativeTransport:
    """Exact-endpoint GitHub/R2 transport consumed by existing validators."""

    def __init__(
        self,
        policy,
        selection,
        network_policy,
        github_token,
        retained_policy=None,
        *,
        _openers=None,
        _clock=time.monotonic,
    ):
        _validate_inputs(policy, selection, retained_policy, network_policy, github_token)
        self.endpoint = retained_policy.endpoint if retained_policy is not None else None
        self.bucket = retained_policy.bucket if retained_policy is not None else None
        self._token = github_token
        self._network = network_policy
        self._budget = _Budget(network_policy, _clock)
        run_path = f"/repos/{policy.repository}/actions/runs/{selection.run_id}"
        artifact_path = f"/repos/{policy.repository}/actions/artifacts/{selection.artifact_id}"
        self._json_paths = frozenset((run_path, run_path + "/attempts/1", artifact_path))
        self._archive_path = artifact_path + "/zip"
        self._archive_limit = policy.max_archive_bytes
        self._object_prefix = (
            artifact_transport.retained_candidate_prefix(selection.run_id, selection.attempt)
            if retained_policy is not None
            else None
        )
        if _openers is None:
            if retained_policy is not None:
                # The R2 S3 API needs SigV4 with a read-only credential: a new
                # secret and permission this caller does not add (RFC014).
                _fail("retained_signer_required", "retained_policy")
            self._api_opener = urllib.request.build_opener(_NoRedirect())
            self._archive_opener = urllib.request.build_opener(
                _ArtifactRedirect(network_policy.artifact_redirect_origins)
            )
            self._object_opener = None
        else:
            if type(_openers) is not tuple or len(_openers) != 3:
                _fail("invalid_input", "openers")
            if any(not callable(getattr(opener, "open", None))
                   for opener in _openers):
                _fail("invalid_input", "openers")
            self._api_opener, self._archive_opener, self._object_opener = _openers

    def get_json(self, path):
        if path not in self._json_paths:
            _fail("endpoint_rejected", "github.path")
        request = self._api_request(path, "application/vnd.github+json")
        with self._open_response(
            request,
            self._api_opener,
            self._network.max_json_bytes,
            frozenset((API_ORIGIN,)),
        ) as response:
            data = response.read()
        try:
            return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise AuthoritativeTransportError("invalid_json", "github.response") from exc

    def open_archive(self, path):
        if path != self._archive_path:
            _fail("endpoint_rejected", "github.archive_path")
        request = self._api_request(path, "application/octet-stream")
        final_origins = frozenset((API_ORIGIN, *self._network.artifact_redirect_origins))
        return self._open_response(
            request,
            self._archive_opener,
            self._archive_limit,
            final_origins,
        )

    def open_object(self, key):
        if self._object_prefix is None or type(key) is not str:
            _fail("endpoint_rejected", "object.key")
        if not key.startswith(self._object_prefix):
            _fail("endpoint_rejected", "object.key")
        relative = key[len(self._object_prefix):]
        if relative != "manifest.json" and re.fullmatch(r"chunks/[0-9]{5}", relative) is None:
            _fail("endpoint_rejected", "object.key")
        quoted_key = urllib.parse.quote(key, safe="/")
        url = f"{self.endpoint}/{urllib.parse.quote(self.bucket, safe='')}/{quoted_key}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/octet-stream",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
                "User-Agent": USER_AGENT,
            },
            method="GET",
        )
        return self._open_response(
            request,
            self._object_opener,
            self._network.max_object_bytes,
            frozenset((self.endpoint,)),
        )

    def _api_request(self, path, accept):
        request = urllib.request.Request(
            API_ORIGIN + path,
            headers={
                "Accept": accept,
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="GET",
        )
        request.add_unredirected_header("Authorization", "Bearer " + self._token)
        return request

    def _open_response(self, request, opener, limit, allowed_final_origins):
        timeout = min(self._network.connect_timeout_seconds, self._budget.remaining_seconds())
        response = None
        try:
            response = opener.open(request, timeout=timeout)
            status = getattr(response, "status", None)
            if status is None and hasattr(response, "getcode"):
                status = response.getcode()
            if status != 200:
                _fail("http_status", "response.status")
            if hasattr(response, "geturl"):
                final_url = response.geturl()
            else:
                final_url = getattr(response, "url", None)
            if type(final_url) is not str:
                _fail("invalid_response", "response.url")
            if _url_origin(final_url) not in allowed_final_origins:
                _fail("response_origin", "response.url")
            encoding = response.headers.get("Content-Encoding", "identity")
            if type(encoding) is not str or encoding.lower() != "identity":
                _fail("content_encoding", "response.headers")
            length = response.headers.get("Content-Length")
            declared = None
            if length is not None:
                if type(length) is not str or re.fullmatch(r"[0-9]+", length) is None:
                    _fail("invalid_content_length", "response.headers")
                declared = int(length)
                if declared > limit:
                    _fail("response_byte_limit", "response.headers")
                if declared > self._budget.remaining_bytes:
                    _fail("total_byte_limit", "response.headers")
            return _BoundedResponse(
                response,
                self._budget,
                limit,
                self._network.idle_timeout_seconds,
                declared,
            )
        except urllib.error.HTTPError as exc:
            _close_quietly(response)
            _close_quietly(exc)
            raise AuthoritativeTransportError("http_status", "response.status") from exc
        except urllib.error.URLError as exc:
            _close_quietly(response)
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                code = (
                    "total_timeout"
                    if self._budget.clock() >= self._budget.deadline
                    else "connect_timeout"
                )
                raise AuthoritativeTransportError(code, "request") from exc
            raise AuthoritativeTransportError("network_error", "request") from exc
        except Exception:
            _close_quietly(response)
            raise


def verify_authoritative_artifact_snapshot(
    policy,
    selection,
    network_policy,
    github_token,
    *,
    _openers=None,
    _clock=time.monotonic,
):
    """Collect one selected GitHub artifact and invoke the existing validator."""
    transport = AuthoritativeTransport(
        policy,
        selection,
        network_policy,
        github_token,
        _openers=_openers,
        _clock=_clock,
    )
    return artifact_transport.verify_artifact_snapshot(policy, selection, transport)


def verify_authoritative_retained_candidate(
    policy,
    selection,
    retained_policy,
    network_policy,
    github_token,
    *,
    _openers=None,
    _clock=time.monotonic,
):
    """Collect selected GitHub/R2 bytes and invoke the retained-media validator.

    R2's S3 API needs SigV4 requests from a read-only key, which is a new
    secret/permission outside this change. With the default openers this
    therefore raises ``retained_signer_required`` before any request.
    """
    transport = AuthoritativeTransport(
        policy,
        selection,
        network_policy,
        github_token,
        retained_policy,
        _openers=_openers,
        _clock=_clock,
    )
    return artifact_transport.verify_retained_candidate_snapshot(
        policy, selection, retained_policy, transport
    )


def _validate_inputs(policy, selection, retained, network, token):
    if type(policy) is not artifact_transport.ReviewedPolicy:
        _fail("invalid_input", "policy")
    if type(selection) is not artifact_transport.ArtifactSelection:
        _fail("invalid_input", "selection")
    if retained is not None and type(retained) is not artifact_transport.RetainedMediaPolicy:
        _fail("invalid_input", "retained_policy")
    if type(network) is not ReviewedNetworkPolicy:
        _fail("invalid_input", "network_policy")
    if policy.repository != "tuna-os/iso-builder":
        _fail("policy_mismatch", "policy.repository")
    for value, field in (
        (selection.run_id, "selection.run_id"),
        (selection.artifact_id, "selection.artifact_id"),
        (policy.max_archive_bytes, "policy.max_archive_bytes"),
    ):
        if type(value) is not int or value <= 0:
            _fail("invalid_input", field)
    if selection.attempt != 1:
        _fail("attempt_rejected", "selection.attempt")
    if (
        type(token) is not str
        or not token
        or token.strip() != token
        or any(not 33 <= ord(ch) <= 126 for ch in token)
    ):
        _fail("invalid_credential", "github_token")
    _validate_network_policy(network)
    if retained is not None:
        if re.fullmatch(r"https://[0-9a-f]{32}\.r2\.cloudflarestorage\.com", retained.endpoint) is None:
            _fail("invalid_origin", "retained.endpoint")
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", retained.bucket) is None:
            _fail("invalid_input", "retained.bucket")


def _validate_network_policy(policy):
    origins = policy.artifact_redirect_origins
    field = "network_policy.artifact_redirect_origins"
    if type(origins) is not tuple or not origins:
        _fail("invalid_input", field)
    if any(type(origin) is not str for origin in origins) or len(origins) != len(set(origins)):
        _fail("invalid_input", field)
    for origin in origins:
        try:
            reviewed = _reviewed_origin(origin)
        except AuthoritativeTransportError as error:
            raise AuthoritativeTransportError(error.code, field) from error
        if reviewed != origin or origin == API_ORIGIN:
            _fail("invalid_origin", field)
    for value, maximum, field in (
        (policy.connect_timeout_seconds, 60, "connect_timeout_seconds"),
        (policy.idle_timeout_seconds, 300, "idle_timeout_seconds"),
        (policy.total_timeout_seconds, 7200, "total_timeout_seconds"),
    ):
        if type(value) not in (int, float) or isinstance(value, bool) or not 0 < value <= maximum:
            _fail("invalid_input", "network_policy." + field)
    for value, maximum, field in (
        (policy.max_json_bytes, MAX_JSON_BYTES, "max_json_bytes"),
        (policy.max_object_bytes, artifact_transport.MAX_CHUNK_BYTES, "max_object_bytes"),
        (policy.max_total_bytes, MAX_TOTAL_BYTES, "max_total_bytes"),
    ):
        if type(value) is not int or value <= 0 or value > maximum:
            _fail("invalid_input", "network_policy." + field)


def _url_origin(url):
    if type(url) is not str:
        _fail("invalid_origin", "url")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise AuthoritativeTransportError("invalid_origin", "url") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        _fail("invalid_origin", "url")
    return "https://" + parsed.hostname.lower()


def _reviewed_origin(url):
    origin = _url_origin(url)
    parsed = urllib.parse.urlsplit(url)
    if parsed.path or parsed.query or parsed.fragment or url != origin:
        _fail("invalid_origin", "url")
    return origin


def _close_quietly(stream):
    if stream is not None:
        try:
            stream.close()
        except Exception:
            pass


def _single_receive_reader(response):
    """Resolve the stream whose read1 performs at most one receive."""
    candidate = response
    seen = set()
    while candidate is not None and id(candidate) not in seen:
        seen.add(id(candidate))
        if callable(getattr(candidate, "read1", None)):
            return candidate
        candidate = getattr(candidate, "fp", None)
    _fail("invalid_response", "response.reader")


def _set_response_timeout(response, reader, timeout):
    """Set the socket timeout on a response or its wrapped raw stream."""
    pending = [reader, response]
    seen = set()
    while pending:
        candidate = pending.pop(0)
        if candidate is None or id(candidate) in seen:
            continue
        seen.add(id(candidate))
        setter = getattr(candidate, "settimeout", None)
        if callable(setter):
            setter(timeout)
            return
        pending.extend(
            getattr(candidate, attribute, None)
            for attribute in ("fp", "raw", "_sock")
        )
    _fail("invalid_response", "response.timeout")


def _unique_object(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            _fail("duplicate_key", "github.response")
        output[key] = value
    return output


def _fail(code, field):
    raise AuthoritativeTransportError(code, field)
