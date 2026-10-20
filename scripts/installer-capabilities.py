#!/usr/bin/env python3
"""Validate and query the explicit installer capability contract.

The registry is integration metadata, not a frontend implementation or a
backend. A caller must name the frontend and operation it wants; unsupported
operations fail instead of falling through to another backend.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


class CapabilityError(ValueError):
    """The registry or requested frontend operation is not supported."""


_TOP_LEVEL = {"schema_version", "contract", "fixture_version", "backends", "frontends"}
_BACKEND_FIELDS = {"contract_version", "required_operations"}
_FRONTEND_FIELDS = {
    "id", "repository", "path", "app_id", "backend", "capabilities", "unsupported"
}


def _text(value, where):
    if not isinstance(value, str) or not value or value != value.strip():
        raise CapabilityError(f"{where}: expected nonempty string")
    return value


def _unique_strings(value, where):
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise CapabilityError(f"{where}: expected nonempty string list")
    if len(value) != len(set(value)):
        raise CapabilityError(f"{where}: duplicate operation")
    return set(value)


def _closed(value, fields, where):
    if not isinstance(value, dict):
        raise CapabilityError(f"{where}: expected object")
    unknown = set(value) - fields
    missing = fields - set(value)
    if unknown or missing:
        raise CapabilityError(f"{where}: unknown={sorted(unknown)}, missing={sorted(missing)}")
    return value


def load(path: Path | str) -> dict:
    """Load and validate one versioned capability registry."""
    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityError(f"registry: cannot read JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise CapabilityError("registry: expected object")
    unknown = set(document) - _TOP_LEVEL
    missing = _TOP_LEVEL - set(document)
    if unknown or missing:
        raise CapabilityError(f"registry: unknown={sorted(unknown)}, missing={sorted(missing)}")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise CapabilityError("registry.schema_version: expected integer 1")
    if document["contract"] != "tunaos-installer-capabilities":
        raise CapabilityError("registry.contract: unsupported contract")
    if document["fixture_version"] != "fork-contracts-v1":
        raise CapabilityError("registry.fixture_version: expected fork-contracts-v1")

    backends = document["backends"]
    if not isinstance(backends, dict) or not backends:
        raise CapabilityError("registry.backends: expected nonempty object")
    required_by_backend = {}
    for name, value in backends.items():
        _text(name, "registry.backends key")
        backend = _closed(value, _BACKEND_FIELDS, f"registry.backends.{name}")
        if type(backend["contract_version"]) is not int or backend["contract_version"] != 1:
            raise CapabilityError(f"registry.backends.{name}.contract_version: expected integer 1")
        required_by_backend[name] = _unique_strings(
            backend["required_operations"], f"registry.backends.{name}.required_operations"
        )

    frontends = document["frontends"]
    if not isinstance(frontends, list) or not frontends:
        raise CapabilityError("registry.frontends: expected nonempty list")
    seen = set()
    for index, value in enumerate(frontends):
        frontend = _closed(value, _FRONTEND_FIELDS, f"registry.frontends[{index}]")
        frontend_id = _text(frontend["id"], f"registry.frontends[{index}].id")
        if frontend_id in seen:
            raise CapabilityError(f"registry.frontends[{index}].id: duplicate frontend")
        seen.add(frontend_id)
        _text(frontend["repository"], f"registry.frontends[{index}].repository")
        _text(frontend["path"], f"registry.frontends[{index}].path")
        backend = _text(frontend["backend"], f"registry.frontends[{index}].backend")
        if backend not in required_by_backend:
            raise CapabilityError(f"registry.frontends[{index}].backend: unknown backend")
        capabilities = _unique_strings(
            frontend["capabilities"], f"registry.frontends[{index}].capabilities"
        )
        unsupported = _unique_strings(
            frontend["unsupported"], f"registry.frontends[{index}].unsupported"
        )
        overlap = capabilities & unsupported
        if overlap:
            raise CapabilityError(
                f"registry.frontends[{index}]: operation both supported and unsupported: {sorted(overlap)}"
            )
        missing_operations = required_by_backend[backend] - capabilities - unsupported
        if missing_operations:
            raise CapabilityError(
                f"registry.frontends[{index}]: backend operations not declared: {sorted(missing_operations)}"
            )
    return document


def require_capability(document: dict, frontend_id: str, operation: str) -> None:
    """Require an operation without selecting a fallback backend."""
    frontend = next((item for item in document["frontends"] if item["id"] == frontend_id), None)
    if frontend is None:
        raise CapabilityError(f"frontend {frontend_id!r}: not declared")
    if operation in frontend["unsupported"]:
        raise CapabilityError(f"frontend {frontend_id!r}: unsupported operation {operation!r}")
    if operation not in frontend["capabilities"]:
        raise CapabilityError(f"frontend {frontend_id!r}: operation {operation!r} not advertised")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument("--frontend")
    parser.add_argument("--require")
    args = parser.parse_args()
    try:
        document = load(args.registry)
        if (args.frontend is None) != (args.require is None):
            parser.error("--frontend and --require must be supplied together")
        if args.frontend is not None:
            require_capability(document, args.frontend, args.require)
        print(json.dumps({"valid": True}, sort_keys=True))
        return 0
    except CapabilityError as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
