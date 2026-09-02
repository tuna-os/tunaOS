"""Shared helpers for the failure injection test suite."""

from __future__ import annotations

import http.server
import importlib.util
import os
import stat
import threading
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parents[2]
GREEN_CRITERIA_PATH = ROOT / ".github" / "green-criteria.yml"
REUSABLE_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "reusable-build-image.yml"
GEN_MATRIX_STATUS_PATH = ROOT / "scripts" / "gen-matrix-status.py"


def load_green_criteria() -> list[dict[str, Any]]:
    """Load criteria list from .github/green-criteria.yml."""
    data = yaml.safe_load(GREEN_CRITERIA_PATH.read_text(encoding="utf-8"))
    return data.get("criteria", [])


def load_reusable_workflow() -> dict[str, Any]:
    """Load the reusable image build workflow."""
    return yaml.safe_load(REUSABLE_WORKFLOW_PATH.read_text(encoding="utf-8"))


def load_gen_matrix_status_module():
    """Dynamically load scripts/gen-matrix-status.py."""
    spec = importlib.util.spec_from_file_location("gms", GEN_MATRIX_STATUS_PATH)
    gms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gms)
    return gms


def evaluate_composite_status(
    stage: dict[str, Any],
    contract: dict[str, Any] | None = None,
    luks: dict[str, Any] | None = None,
    smoke: dict[str, Any] | None = None,
    lifecycle: dict[str, Any] | None = None,
    omissions: dict[str, Any] | None = None,
    parity: dict[str, Any] | None = None,
    criteria: list[dict[str, Any]] | None = None,
) -> tuple[int, int, list[str], dict[str, Any]]:
    """Run composite_section() from scripts/gen-matrix-status.py.

    Returns:
        (green_count, total_count, markdown_lines, provenance_dict)
    """
    gms = load_gen_matrix_status_module()
    crit = criteria or load_green_criteria()
    lines, green, total, prov = gms.composite_section(
        crit,
        stage,
        contract or {},
        luks or {},
        smoke or {},
        lifecycle or {},
        omissions or {},
        parity or {},
    )
    return green, total, lines, prov


def evaluate_promote_condition(
    needs_results: dict[str, str],
    is_pr: bool = False,
    is_cancelled: bool = False,
    workflow: dict[str, Any] | None = None,
) -> bool:
    """Evaluate whether the promote job (tag-image) in reusable-build-image.yml would execute.

    In reusable-build-image.yml:
      tag-image:
        needs: [manifest, sign, verify_boot, verify_asahi]
        if: !cancelled() && github.event_name != 'pull_request' &&
            needs.manifest.result == 'success' &&
            needs.sign.result == 'success' &&
            (needs.verify_boot.result == 'success' || needs.verify_boot.result == 'skipped') &&
            (needs.verify_asahi.result == 'success' || needs.verify_asahi.result == 'skipped')
    """
    if is_cancelled or is_pr:
        return False

    wf = workflow or load_reusable_workflow()
    tag_job = wf["jobs"].get("tag-image", {})
    condition = tag_job.get("if", "")

    # Basic invariant checks against the workflow AST
    assert "needs.sign.result == 'success'" in condition
    assert "needs.manifest.result == 'success'" in condition

    manifest_ok = needs_results.get("manifest") == "success"
    sign_ok = needs_results.get("sign") == "success"
    boot_res = needs_results.get("verify_boot", "skipped")
    boot_ok = boot_res in ("success", "skipped")
    asahi_res = needs_results.get("verify_asahi", "skipped")
    asahi_ok = asahi_res in ("success", "skipped")

    return bool(manifest_ok and sign_ok and boot_ok and asahi_ok)


def make_executable(path: Path, content: str) -> None:
    """Write an executable script to path."""
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class StubHttpServer:
    """A lightweight local HTTP server for testing network and API failures."""

    def __init__(self, routes: dict[str, tuple[int, bytes, dict[str, str]]] | None = None):
        """routes: map of path -> (status_code, body_bytes, headers)"""
        self.routes = routes or {}
        self.requests_log: list[dict[str, Any]] = []
        self.server: http.server.HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.port: int = 0

    def add_route(
        self,
        path: str,
        status_code: int = 200,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.routes[path] = (status_code, body, headers or {})

    def start(self) -> str:
        routes = self.routes
        req_log = self.requests_log

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # suppress standard stderr logging

            def do_GET(self):
                self._handle()

            def do_HEAD(self):
                self._handle()

            def do_POST(self):
                self._handle()

            def do_PUT(self):
                self._handle()

            def _handle(self):
                url_path = self.path.split("?")[0]
                req_log.append({
                    "method": self.command,
                    "path": self.path,
                    "headers": dict(self.headers),
                })
                # Match exact path or wildcard
                matched = None
                if self.path in routes:
                    matched = routes[self.path]
                elif url_path in routes:
                    matched = routes[url_path]
                else:
                    for pattern, val in routes.items():
                        if pattern in self.path:
                            matched = val
                            break

                if matched is None:
                    matched = (404, b"Not Found", {})

                code, body, resp_headers = matched
                self.send_response(code)
                for k, v in resp_headers.items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
