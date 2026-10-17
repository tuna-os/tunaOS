"""Shared authored-source policy; legacy inventory is not readiness proof."""
from __future__ import annotations

from collections import Counter
import json
import re
from urllib.parse import urlparse

FORBIDDEN_KEYS = {"copr", "ppa", "obs", "aur"}
ENDPOINT_KEYS = {"baseurl", "gpgkey", "keyring_url", "uri", "url"}
ALLOWED_REPO_HOSTS = ("repo.tunaos.org", "tideforge.org")


def _consumer_scope(path: str) -> str:
    """Return the manifest consumer scope while ignoring list positions."""
    parts = [component.split("[", 1)[0] for component in path.split(".") if component]
    if "packages" in parts:
        index = parts.index("packages")
        return ".".join(parts[:index + 2])
    return parts[0] if parts else ""


def _records(value: object, path: str = "") -> list[tuple[str, tuple[str, str, str]]]:
    found: list[tuple[str, tuple[str, str, str]]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key)
            key_path = f"{path}.{name}" if path else name
            if name.lower() in FORBIDDEN_KEYS:
                fingerprint = (
                    _consumer_scope(key_path),
                    name.lower(),
                    json.dumps(child, sort_keys=True, separators=(",", ":")),
                )
                found.append((f"{key_path}: {name} is not an approved package source", fingerprint))
            found.extend(_records(child, key_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_records(child, f"{path}[{index}]"))
    elif isinstance(value, str) and path.rsplit(".", 1)[-1] in ENDPOINT_KEYS:
        name = path.rsplit(".", 1)[-1]
        fingerprint = (_consumer_scope(path), name, value)
        if re.search(r"\s", value):
            found.append((f"{path}: repository endpoint contains whitespace", fingerprint))
            return found
        parsed = urlparse(value)
        if parsed.username is not None or parsed.password is not None:
            found.append((f"{path}: repository credentials must not be authored in manifests", fingerprint))
        elif parsed.scheme == "https":
            host = parsed.hostname or ""
            if host not in ALLOWED_REPO_HOSTS:
                found.append((f"{path}: external repository host {host!r} is not approved", fingerprint))
        elif parsed.scheme == "file":
            if parsed.netloc or not parsed.path.startswith("/"):
                found.append((f"{path}: local repository file URL must be absolute", fingerprint))
        else:
            found.append((f"{path}: repository endpoint scheme is not approved", fingerprint))
    return found


def violations(value: object, path: str = "") -> list[str]:
    return [message for message, _fingerprint in _records(value, path)]


def classify_policy(document: object, baseline: object | None) -> dict:
    """A pinned baseline distinguishes inherited values independent of list order."""
    previous = Counter(fingerprint for _message, fingerprint in _records(baseline))
    inherited = []
    forbidden = []
    for message, fingerprint in _records(document):
        if previous[fingerprint]:
            inherited.append(message)
            previous[fingerprint] -= 1
        else:
            forbidden.append(message)
    return {"inherited": sorted(inherited), "forbiddenNew": sorted(forbidden)}
