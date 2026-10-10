"""Shared authored-source policy; legacy inventory is not readiness proof."""
from __future__ import annotations

from urllib.parse import urlparse

FORBIDDEN_KEYS = {"copr", "ppa", "obs", "aur"}
ALLOWED_REPO_HOSTS = ("repo.tunaos.org", "tideforge.org")


def violations(value: object, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in FORBIDDEN_KEYS:
                found.append(f"{key_path}: {key} is not an approved package source")
            found.extend(violations(child, key_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(violations(child, f"{path}[{index}]"))
    elif isinstance(value, str) and path.rsplit(".", 1)[-1] in {"baseurl", "uri"}:
        parsed = urlparse(value)
        host = parsed.hostname or ""
        if parsed.username is not None or parsed.password is not None:
            found.append(f"{path}: repository credentials must not be authored in manifests")
        elif value.startswith(("http://", "https://")) and host not in ALLOWED_REPO_HOSTS:
            found.append(f"{path}: external repository host {host!r} is not approved")
    return found


def classify_policy(document: object, baseline: object | None) -> dict:
    """A pinned policy baseline distinguishes inherited declarations from adds."""
    def declarations(value: object, path: str = "") -> dict:
        result = {}
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if str(key).lower() in FORBIDDEN_KEYS or str(key) in {"baseurl", "uri"}:
                    result[child_path] = child
                result.update(declarations(child, child_path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                result.update(declarations(child, f"{path}[{index}]"))
        return result

    current = set(violations(document))
    previous = set(violations(baseline)) if baseline is not None else set()
    current_values, previous_values = declarations(document), declarations(baseline)
    inherited = {error for error in current & previous
                 if current_values.get(error.split(": ", 1)[0]) == previous_values.get(error.split(": ", 1)[0])}
    return {"inherited": sorted(inherited), "forbiddenNew": sorted(current - inherited)}
