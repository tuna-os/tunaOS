#!/usr/bin/env python3
"""Build and qualify a config-and-owned-assets-only fork (#3806).

The manual workflow uses the primary TOML compiler to make a local stock/fork
commit pair, then retains local stock and customized Yellowfin/RPM and
Grouper/APT base+GNOME images. It never authenticates to a registry or publishes.
Image checks reuse the native package receipt and OCI identity primitives from
qualify-image-packages.py; this is build evidence only, not install/boot/recovery
qualification (#3474).
"""
from __future__ import annotations

import argparse
import configparser
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import tunaos_config  # noqa: E402

_HARNESS_SPEC = importlib.util.spec_from_file_location(
    "config_only_package_harness", ROOT / "scripts/qualify-image-packages.py"
)
_HARNESS = importlib.util.module_from_spec(_HARNESS_SPEC)
_HARNESS_SPEC.loader.exec_module(_HARNESS)

SCHEMA_VERSION = 1
PLATFORM = "linux/amd64"
PROJECT_NAME = "Acme OS"
PROJECT_ID = "acmeos"
CPE_VENDOR = "acme"
HOMEPAGE = "https://acme.example.org"
DOCS_URL = "https://docs.acme.example.org"
PLYMOUTH_THEME = "config-proof"
PACKAGE = "tree"
ASSET_DIR = Path("system_files/usr/share/plymouth/themes") / PLYMOUTH_THEME
ASSET_FIXTURE = ROOT / "tests/fixtures/config-only-image-assets"
ASSET_FILES = ("config-proof.plymouth", "config-proof.script")
# `.github/build-config.yml` is an ignored projection: `just build` regenerates
# it through build-config.sh after each commit checkout, so it is never staged.
GENERATED_PATHS = frozenset({
    "build_scripts/lib/identity.env",
    "build_scripts/lib/variant-identity.tsv",
    "build_scripts/lib/variant-aliases.tsv",
    "build_scripts/lib/image-packages.tsv",
    "build_scripts/desktop/flatpak-preinstall.tsv",
    "docs/iso-builder.config.json",
    "docs/iso-builder.flavors.json",
})
GENERATE_CHECKS = (
    "check-builder-config", "check-builder-flavors", "check-identity",
    "check-variant-identity", "check-variant-aliases", "check-image-packages",
    "check-flatpak-policy",
)
FAMILIES = (
    {"family": "rpm", "route": "el10", "variant": "yellowfin", "manager": "dnf"},
    {"family": "apt", "route": "ubuntu", "variant": "grouper", "manager": "apt"},
)
ROLES = ("stockBase", "stockDesktop", "modifiedBase", "modifiedDesktop")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_REF = re.compile(r"localhost/[a-z0-9][a-z0-9._-]*:[a-z0-9][a-z0-9._-]*\Z")


class QualificationError(ValueError):
    """The selected inputs or observations cannot prove this qualification."""


def need(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> object:
    try:
        data = path.read_bytes()
        need(0 < len(data) <= 1024 * 1024, f"{path}: expected 1..1048576 bytes")
        return json.loads(data, object_pairs_hook=_HARNESS.unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"{path}: invalid JSON: {exc}") from exc


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    need(result.returncode == 0, f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def run(root: Path, argv: list[str], what: str) -> None:
    result = subprocess.run(argv, cwd=root, capture_output=True, text=True, check=False)
    need(result.returncode == 0, f"{what}: {result.stderr.strip() or result.stdout.strip()}")


def _resolve_image_flavor(root: Path, variant: str, public_flavor: str) -> str:
    result = subprocess.run(["bash", "scripts/resolve-flavor.sh", variant, public_flavor],
                            cwd=root, capture_output=True, check=False)
    need(result.returncode == 0,
         f"route {variant}:{public_flavor}: {result.stderr.decode(errors='replace').strip()}")
    try:
        routing = _HARNESS.parse_route(result.stdout)
    except _HARNESS.QualificationError as exc:
        raise QualificationError(f"route {variant}:{public_flavor}: {exc}") from exc
    target = routing.get("DESKTOP_FLAVOR")
    need(isinstance(target, str) and target, f"route {variant}:{public_flavor}: resolver omitted DESKTOP_FLAVOR")
    return target


def _generated_commands(root: Path, mode: str) -> None:
    command = "generate-all" if mode == "generate" else "validate"
    run(root, [sys.executable, "scripts/config.py", command, "--root", str(root)],
        f"primary TOML {command}")
    if mode == "check":
        for check in GENERATE_CHECKS:
            run(root, [sys.executable, "scripts/config.py", check, "--root", str(root)],
                f"primary TOML {check}")
        run(root, [sys.executable, "scripts/config.py", "check-drawn-artwork", "--root", str(root)],
            "primary TOML check-drawn-artwork")


def _replace_once(text: str, old: str, new: str, where: str) -> str:
    need(text.count(old) == 1, f"tunaos.toml: expected one {where} recipe anchor")
    return text.replace(old, new, 1)


def recipe_text(text: str) -> str:
    """Apply the documented F5 fork edits without implementing another TOML parser."""
    replacements = (
        ('name = "TunaOS"\nid = "tunaos"\ncpe_vendor = "jamesreilly"',
         f'name = "{PROJECT_NAME}"\nid = "{PROJECT_ID}"\ncpe_vendor = "{CPE_VENDOR}"', "project identity"),
        ('website = "https://tunaos.org"\ndocs_url = "https://tunaos.org/docs"',
         f'website = "{HOMEPAGE}"\ndocs_url = "{DOCS_URL}"', "project URLs"),
        ('countme_endpoint = "https://countme.tunaos.org/v1/report"\n'
         'countme_metrics_url = "https://tunaos.org/metrics"',
         'countme_endpoint = ""\ncountme_metrics_url = ""', "usage-report destination"),
        ('homepage = "https://github.com/tuna-os/tunaos"',
         f'homepage = "{HOMEPAGE}"', "visible homepage"),
        ('documentation = "https://github.com/tuna-os/tunaos/tree/main/docs"',
         f'documentation = "{DOCS_URL}"', "documentation URL"),
        ('support = "https://github.com/tuna-os/tunaos/issues/"',
         f'support = "{HOMEPAGE}/support"', "support URL"),
        ('bug_report = "https://github.com/tuna-os/tunaos/issues/"',
         f'bug_report = "{HOMEPAGE}/issues"', "bug-report URL"),
        ('plymouth = "tropical-fish"', f'plymouth = "{PLYMOUTH_THEME}"', "Yellowfin theme"),
        ('plymouth = "coral"', f'plymouth = "{PLYMOUTH_THEME}"', "Grouper theme"),
    )
    for old, new, where in replacements:
        text = _replace_once(text, old, new, where)
    for variant in ("yellowfin", "grouper"):
        need(f"[variants.{variant}.packages]" not in text,
             f"tunaos.toml: [variants.{variant}.packages] already exists")
        text += f"\n[variants.{variant}.packages]\nadd = [\"{PACKAGE}\"]\n"
    return text


def allowed_source_path(path: str, theme: str = PLYMOUTH_THEME) -> bool:
    """Only TOML, compiler outputs, and the fixture's exact owned assets may differ."""
    assets = {f"system_files/usr/share/plymouth/themes/{theme}/{name}" for name in ASSET_FILES}
    return path == "tunaos.toml" or path in GENERATED_PATHS or path in assets


def _expected_asset_digests(root: Path) -> dict[str, str]:
    result = {}
    for name in ASSET_FILES:
        path = ASSET_FIXTURE / name
        need(path.is_file() and not path.is_symlink(), f"owned asset fixture missing: {path}")
        result[(ASSET_DIR / name).as_posix()] = sha256(path.read_bytes())
    return result


def _copy_owned_assets(root: Path) -> dict[str, str]:
    digests = _expected_asset_digests(root)
    for relative, expected in digests.items():
        target = root / relative
        need(not target.exists() and not target.is_symlink(), f"owned asset already exists: {relative}")
        need(target.resolve(strict=False).is_relative_to(root), f"owned asset escapes source checkout: {relative}")
        for parent in (target.parent, *target.parent.parents):
            if parent == root.parent:
                break
            need(not parent.is_symlink(), f"owned asset parent is a symlink: {parent}")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = (ASSET_FIXTURE / Path(relative).name).read_bytes()
        need(sha256(content) == expected, f"owned asset changed while copying: {relative}")
        target.write_bytes(content)
    return digests


def _check_source_delta(root: Path, stock: str, modified: str, expected_assets: dict[str, str]) -> list[str]:
    head = git(root, "rev-parse", "HEAD")
    need(head == modified, "source: checkout HEAD differs from modifiedCommit")
    need(not git(root, "status", "--porcelain", "--untracked-files=all"),
         "source: checkout must be clean")
    parents = git(root, "rev-list", "--parents", "-n", "1", head).split()
    need(parents == [head, stock], "source: modifiedCommit must have stockCommit as its only parent")
    changed = set(filter(None, git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", head).splitlines()))
    need(changed and all(allowed_source_path(path) for path in changed),
         "source: modified commit contains code or non-owned input changes")
    actual_assets = {path for path in changed if path.startswith(f"{ASSET_DIR.as_posix()}/")}
    need(actual_assets == set(expected_assets), "source: owned asset set differs from the declared fork assets")
    for path, digest in expected_assets.items():
        target = root / path
        need(target.is_file() and not target.is_symlink(), f"source: owned asset {path} is not a regular file")
        need(sha256(target.read_bytes()) == digest, f"source: owned asset {path} digest mismatch")
    _generated_commands(root, "check")
    config = tunaos_config.load(root / "tunaos.toml")
    need(config["project"]["name"] == PROJECT_NAME and config["project"]["id"] == PROJECT_ID,
         "source: fork project identity differs from the qualification recipe")
    need(config["defaults"]["branding"]["homepage"] == HOMEPAGE,
         "source: expected visible homepage marker is stale")
    need(config["variants"]["yellowfin"]["branding"]["plymouth"] == PLYMOUTH_THEME
         and config["variants"]["grouper"]["branding"]["plymouth"] == PLYMOUTH_THEME,
         "source: custom theme is not named by both selected variants")
    # The package adapter is compiler output; its selected additions must be
    # exactly the two recipe rows, with no removal or unrelated package delta.
    raw = (root / "build_scripts/lib/image-packages.tsv").read_text(encoding="utf-8").splitlines()
    rows = [line.split("\t") for line in raw if line and not line.startswith("#")]
    need(rows == [["yellowfin", "dnf", "add", PACKAGE], ["grouper", "apt", "add", PACKAGE]],
         "source: generated package adapter does not exactly match the two qualification additions")
    return sorted(changed)


def prepare(root: Path, plan_path: Path) -> dict:
    need(not root.is_symlink(), "source: expected a real checkout")
    root = root.resolve()
    plan_path = plan_path.resolve()
    need(root.is_dir(), "source: expected a real checkout")
    need(not plan_path.is_relative_to(root), "plan: must be outside the source checkout")
    need(not git(root, "status", "--porcelain", "--untracked-files=all"),
         "source: checkout must be clean before preparing the local fork")
    need(not plan_path.exists() and not plan_path.is_symlink(), "plan: refusing to replace existing file")
    run(root, [sys.executable, "scripts/config.py", "generate", "--root", str(root)],
        "stock primary TOML matrix projection")
    _generated_commands(root, "check")
    stock = git(root, "rev-parse", "HEAD")
    stock_config = (root / "tunaos.toml").read_bytes()
    stock_document = tunaos_config.load(root / "tunaos.toml")
    stock_adapter = (root / "build_scripts/lib/image-packages.tsv").read_bytes()
    assets = _expected_asset_digests(root)

    config_path = root / "tunaos.toml"
    config_path.write_text(recipe_text(config_path.read_text(encoding="utf-8")), encoding="utf-8")
    _copy_owned_assets(root)
    _generated_commands(root, "generate")
    run(root, [sys.executable, "scripts/config.py", "validate", "--root", str(root)],
        "primary TOML validate")
    run(root, [sys.executable, "scripts/config.py", "check-drawn-artwork", "--root", str(root)],
        "primary TOML check-drawn-artwork")
    changed = set(filter(None, git(root, "status", "--porcelain", "--untracked-files=all").splitlines()))
    need(changed, "source: recipe made no changes")
    # Stage only the exact candidate inputs and compiler outputs; never `git add .`.
    add_paths = ["tunaos.toml", *sorted(GENERATED_PATHS), *sorted(assets)]
    git(root, "add", "--", *add_paths)
    staged = set(filter(None, git(root, "diff", "--cached", "--name-only").splitlines()))
    allowed = {"tunaos.toml", *GENERATED_PATHS, *assets}
    required = {"tunaos.toml", "build_scripts/lib/identity.env",
                "build_scripts/lib/image-packages.tsv", *assets}
    need(staged <= allowed and required <= staged, "source: unexpected or incomplete staged input")
    git(root, "-c", "user.name=config-only-qualification", "-c", "user.email=qualification@invalid",
        "-c", "commit.gpgsign=false", "commit", "--no-verify", "--quiet", "-m",
        "qualification fork: TOML and owned assets only")
    modified = git(root, "rev-parse", "HEAD")
    need(modified != stock, "source: stock and customized commits are identical")
    changed_paths = _check_source_delta(root, stock, modified, assets)
    modified_config = (root / "tunaos.toml").read_bytes()
    modified_adapter = (root / "build_scripts/lib/image-packages.tsv").read_bytes()
    modified_document = tunaos_config.load(root / "tunaos.toml")
    families = []
    builds = []
    for item in FAMILIES:
        variant, family = item["variant"], item["family"]
        base = stock_document["variants"][variant]["base_image"]
        need(isinstance(base, str) and "@sha256:" in base and DIGEST.fullmatch(base.rsplit("@", 1)[1]),
             f"{variant}: base image is not digest-pinned")
        need(modified_document["variants"][variant]["base_image"] == base,
             f"{variant}: qualification recipe changed the base image")
        refs = {role: f"localhost/{variant}:config-proof-{role.lower()}" for role in ROLES}
        image_flavors = {}
        for role in ROLES:
            public_flavor = "base" if role.endswith("Base") else "gnome"
            image_flavors[role] = _resolve_image_flavor(root, variant, public_flavor)
        cell = {**item, "package": PACKAGE, "desktop": "gnome", "platform": PLATFORM,
                "baseImage": base, "images": refs, "imageFlavors": image_flavors}
        families.append(cell)
        for role in ROLES:
            commit = stock if role.startswith("stock") else modified
            flavor = "base" if role.endswith("Base") else "gnome"
            tag = refs[role].split(":", 1)[1]
            builds.append({"family": family, "role": role, "commit": commit, "variant": variant,
                           "flavor": flavor, "isCi": "1", "tag": tag, "chain": ""})
    plan = {
        "schemaVersion": SCHEMA_VERSION,
        "platform": PLATFORM,
        "stockCommit": stock,
        "modifiedCommit": modified,
        "stockConfigSha256": sha256(stock_config),
        "modifiedConfigSha256": sha256(modified_config),
        "stockAdapterSha256": sha256(stock_adapter),
        "modifiedAdapterSha256": sha256(modified_adapter),
        "generatedPaths": sorted(GENERATED_PATHS),
        "ownedAssets": assets,
        "changedPaths": changed_paths,
        "expectedBrand": {"projectName": PROJECT_NAME, "homepage": HOMEPAGE, "theme": PLYMOUTH_THEME},
        "families": families,
        "builds": builds,
    }
    validate_plan(plan)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"stockCommit": stock, "modifiedCommit": modified, "builds": builds,
            "planSha256": sha256(plan_path.read_bytes())}


def prepare_build(root: Path, expected_commit: str) -> str:
    need(not root.is_symlink(), "build source: expected a real checkout")
    root = root.resolve()
    need(root.is_dir(), "build source: expected a real checkout")
    need(isinstance(expected_commit, str) and COMMIT.fullmatch(expected_commit),
         "build source: expected a full commit")
    need(git(root, "rev-parse", "HEAD") == expected_commit,
         "build source: checked-out commit differs from the selected build record")
    need(not git(root, "status", "--porcelain", "--untracked-files=all"),
         "build source: tracked checkout must be clean before projection generation")
    # Refuse stale committed adapters before running a generator that can rewrite
    # them. generate-all then refreshes ignored manifests and the matrix from this
    # exact TOML; the second check/status pair refuses any tracked drift.
    _generated_commands(root, "check")
    run(root, [sys.executable, "scripts/config.py", "generate-all", "--root", str(root)],
        "checked-out primary TOML generate-all")
    _generated_commands(root, "check")
    need(git(root, "rev-parse", "HEAD") == expected_commit,
         "build source: generated projections changed the selected commit")
    need(not git(root, "status", "--porcelain", "--untracked-files=all"),
         "build source: generate-all changed tracked files")
    return expected_commit


def validate_plan(value: object) -> dict:
    fields = {"schemaVersion", "platform", "stockCommit", "modifiedCommit", "stockConfigSha256",
              "modifiedConfigSha256", "stockAdapterSha256", "modifiedAdapterSha256", "generatedPaths",
              "ownedAssets", "changedPaths", "expectedBrand", "families", "builds"}
    need(isinstance(value, dict) and set(value) == fields, "plan: invalid fields")
    need(value["schemaVersion"] == SCHEMA_VERSION and value["platform"] == PLATFORM, "plan: unsupported schema/platform")
    for key in ("stockCommit", "modifiedCommit"):
        need(isinstance(value[key], str) and COMMIT.fullmatch(value[key]), f"plan.{key}: expected full commit")
    need(value["stockCommit"] != value["modifiedCommit"], "plan: commits must differ")
    for key in ("stockConfigSha256", "modifiedConfigSha256", "stockAdapterSha256", "modifiedAdapterSha256"):
        need(isinstance(value[key], str) and DIGEST.fullmatch(value[key]), f"plan.{key}: invalid digest")
    need(value["generatedPaths"] == sorted(GENERATED_PATHS), "plan.generatedPaths: compiler output allowlist mismatch")
    assets = value["ownedAssets"]
    need(isinstance(assets, dict) and set(assets) == {(ASSET_DIR / name).as_posix() for name in ASSET_FILES},
         "plan.ownedAssets: unexpected paths")
    for path, digest in assets.items():
        need(allowed_source_path(path) and isinstance(digest, str) and DIGEST.fullmatch(digest),
             "plan.ownedAssets: invalid asset path or digest")
    need(isinstance(value["changedPaths"], list) and value["changedPaths"]
         and all(isinstance(path, str) and allowed_source_path(path) for path in value["changedPaths"]),
         "plan.changedPaths: code or non-owned path")
    need(value["changedPaths"] == sorted(set(value["changedPaths"])), "plan.changedPaths: duplicates or unsorted paths")
    brand = value["expectedBrand"]
    need(brand == {"projectName": PROJECT_NAME, "homepage": HOMEPAGE, "theme": PLYMOUTH_THEME},
         "plan.expectedBrand: recipe mismatch")
    cells = value["families"]
    need(isinstance(cells, list) and len(cells) == len(FAMILIES), "plan.families: expected RPM and APT")
    by_family = {item.get("family"): item for item in cells if isinstance(item, dict)}
    need(set(by_family) == {"rpm", "apt"}, "plan.families: family set mismatch")
    for expected in FAMILIES:
        cell = by_family[expected["family"]]
        required = {"family", "route", "variant", "manager", "package", "desktop", "platform",
                    "baseImage", "images", "imageFlavors"}
        need(set(cell) == required and all(cell[key] == expected[key] for key in expected),
             f"plan.{expected['family']}: target identity mismatch")
        need(cell["package"] == PACKAGE and cell["desktop"] == "gnome" and cell["platform"] == PLATFORM,
             f"plan.{expected['family']}: package/flavor/platform mismatch")
        need(isinstance(cell["baseImage"], str) and "@" in cell["baseImage"]
             and DIGEST.fullmatch(cell["baseImage"].rsplit("@", 1)[1]),
             f"plan.{expected['family']}.baseImage: expected digest pin")
        refs = cell["images"]
        need(isinstance(refs, dict) and set(refs) == set(ROLES), f"plan.{expected['family']}.images: invalid roles")
        for role, ref in refs.items():
            need(isinstance(ref, str) and IMAGE_REF.fullmatch(ref), f"plan.{expected['family']}.{role}: invalid local ref")
        image_flavors = cell["imageFlavors"]
        need(isinstance(image_flavors, dict) and set(image_flavors) == set(ROLES),
             f"plan.{expected['family']}.imageFlavors: invalid roles")
        for role, target in image_flavors.items():
            need(isinstance(target, str) and re.fullmatch(r"[a-z0-9][a-z0-9._-]*", target),
                 f"plan.{expected['family']}.{role}: invalid resolved image flavor")
    builds = value["builds"]
    need(isinstance(builds, list) and len(builds) == len(FAMILIES) * len(ROLES), "plan.builds: expected eight local builds")
    expected_builds = {(cell["family"], role, cell["images"][role]) for cell in cells for role in ROLES}
    actual_builds = set()
    for item in builds:
        need(isinstance(item, dict) and set(item) == {"family", "role", "commit", "variant", "flavor", "isCi", "tag", "chain"},
             "plan.builds: invalid build record")
        actual_builds.add((item["family"], item["role"], f"localhost/{item['variant']}:{item['tag']}"))
        expected_commit = value["stockCommit"] if item["role"].startswith("stock") else value["modifiedCommit"]
        need(item["commit"] == expected_commit and item["isCi"] == "1" and item["chain"] == "",
             "plan.builds: commit or local-only build mode mismatch")
        need(item["variant"] in {"yellowfin", "grouper"}
             and item["flavor"] == ("base" if item["role"].endswith("Base") else "gnome"),
             "plan.builds: unexpected image target")
    need(actual_builds == expected_builds, "plan.builds: role/ref set mismatch")
    return value


def _source_record(plan: dict, root: Path, log_path: Path) -> dict:
    log_path = Path(log_path)
    run(root, [sys.executable, "scripts/config.py", "generate", "--root", str(root)],
        "source primary TOML matrix projection")
    try:
        with _HARNESS.CommandLog(log_path) as log:
            paths = _check_source_delta(root, plan["stockCommit"], plan["modifiedCommit"], plan["ownedAssets"])
            stock_bytes = _HARNESS.checked(log, ["git", "show", f"{plan['stockCommit']}:tunaos.toml"], cwd=root,
                                           what="stock TOML")
            modified_bytes = (root / "tunaos.toml").read_bytes()
            need(sha256(stock_bytes) == plan["stockConfigSha256"], "source: stock TOML digest mismatch")
            need(sha256(modified_bytes) == plan["modifiedConfigSha256"], "source: modified TOML digest mismatch")
            adapter_before = _HARNESS.checked(log,
                ["git", "show", f"{plan['stockCommit']}:build_scripts/lib/image-packages.tsv"], cwd=root,
                what="stock package adapter")
            adapter_now = (root / "build_scripts/lib/image-packages.tsv").read_bytes()
            stock_rows = [line for line in adapter_before.decode().splitlines() if line and not line.startswith("#")]
            modified_rows = [line for line in adapter_now.decode().splitlines() if line and not line.startswith("#")]
            need(not stock_rows and sha256(adapter_before) == plan["stockAdapterSha256"],
                 "source: stock package adapter is not the expected empty compiler output")
            need(modified_rows == ["yellowfin\tdnf\tadd\ttree", "grouper\tapt\tadd\ttree"]
                 and sha256(adapter_now) == plan["modifiedAdapterSha256"],
                 "source: modified package adapter is stale or mismatched")
            for cell in plan["families"]:
                for role in ROLES:
                    public_flavor = "base" if role.endswith("Base") else "gnome"
                    resolved = _resolve_image_flavor(root, cell["variant"], public_flavor)
                    need(resolved == cell["imageFlavors"][role],
                         f"source: {cell['family']}.{role} resolved flavor changed")
        return {"stockCommit": plan["stockCommit"], "modifiedCommit": plan["modifiedCommit"],
                "stockConfigSha256": plan["stockConfigSha256"],
                "modifiedConfigSha256": plan["modifiedConfigSha256"],
                "stockAdapterSha256": plan["stockAdapterSha256"],
                "modifiedAdapterSha256": plan["modifiedAdapterSha256"],
                "changedPaths": paths}
    finally:
        log_path.unlink(missing_ok=True)


def _os_release_values(raw: bytes, where: str) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise QualificationError(f"{where}: os-release is not UTF-8") from exc
    result = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in {"NAME", "PRETTY_NAME", "HOME_URL", "VERSION_CODENAME", "VARIANT_ID"}:
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1].replace('\\"', '"').replace('\\\\', '\\')
            result[key] = value
    return result


def _inventory_from_receipt(raw: bytes, family: str, variant: str) -> dict[str, str]:
    try:
        document = json.loads(raw, object_pairs_hook=_HARNESS.unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"{family}: invalid native package inventory receipt") from exc
    need(isinstance(document, dict) and set(document) == {"image", "flavor", "pkg_manager", "count", "packages"},
         f"{family}: package inventory receipt has invalid fields")
    need(document["image"] == variant and document["flavor"] == "gnome"
         and document["pkg_manager"] == ("dnf" if family == "rpm" else "apt"),
         f"{family}: package inventory receipt identity mismatch")
    packages = document["packages"]
    need(isinstance(packages, list) and document["count"] == len(packages),
         f"{family}: package inventory count mismatch")
    inventory = {}
    for item in packages:
        need(isinstance(item, dict) and set(item) == {"name", "version"}
             and isinstance(item["name"], str) and item["name"]
             and isinstance(item["version"], str), f"{family}: invalid package inventory row")
        need(item["name"] not in inventory, f"{family}: duplicate package inventory name")
        inventory[item["name"]] = item["version"]
    return inventory


def _package_manifest(log, image_id: str, family: str, variant: str) -> tuple[dict[str, str], str, str]:
    result = _HARNESS.podman(log, image_id, "/usr/bin/cat", "/usr/share/tunaos/packages.json")
    need(result.returncode == 0, f"{family}: desktop package inventory receipt is missing")
    inventory = _inventory_from_receipt(result.stdout, family, variant)
    return inventory, sha256(result.stdout), result.stdout.decode("utf-8")


SCRIPT_PLUGIN_PROBE = (
    'for path in /usr/lib*/plymouth/script.so /usr/lib*/*/plymouth/script.so; do '
    'if [ -f "$path" ]; then printf "%s\\n" "$path"; fi; done'
)


def _plymouth_observation(log, image_id: str, family: str, role: str, expected_theme: str) -> dict:
    conf = _HARNESS.podman(log, image_id, "/usr/bin/cat", "/etc/plymouth/plymouthd.conf")
    configured_theme = None
    if conf.returncode == 0:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read_string(conf.stdout.decode("utf-8"))
            configured_theme = parser.get("Daemon", "Theme", fallback=None)
        except (UnicodeError, configparser.Error):
            configured_theme = None
    link = _HARNESS.podman(log, image_id, "/usr/bin/readlink",
                           "/usr/share/plymouth/themes/default.plymouth")
    link_target = link.stdout.decode("utf-8", errors="replace").strip() if link.returncode == 0 else None
    plugins = _HARNESS.podman(log, image_id, "/bin/sh", "-c", SCRIPT_PLUGIN_PROBE)
    plugin_paths = [line for line in plugins.stdout.decode("utf-8", errors="replace").splitlines() if line]
    plugin = plugin_paths[0] if plugin_paths else None
    expected_link = f"{expected_theme}/{expected_theme}.plymouth"
    plugin_valid = (plugins.returncode == 0 and isinstance(plugin, str)
                    and plugin.startswith("/usr/lib") and plugin.endswith("/plymouth/script.so"))
    checks = {
        "configuredTheme": configured_theme == expected_theme,
        "defaultThemeLink": link_target == expected_link,
        "scriptPlugin": plugin_valid,
    }
    reason = ", ".join(name for name, passed in checks.items() if not passed) or None
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "configuredTheme": configured_theme,
        "defaultThemeLinkTarget": link_target,
        "scriptPlugin": plugin,
        "checks": checks,
        "reason": reason,
    }


def _image_record(plan: dict, cell: dict, role: str, root: Path, log) -> dict:
    ref = cell["images"][role]
    local = _HARNESS.local_image(log, ref)
    image_id = local["imageId"]
    identity = _HARNESS.image_identity(log, ref, image_id)
    info = _HARNESS.read_image_info(log, image_id)
    source_commit = plan["stockCommit"] if role.startswith("stock") else plan["modifiedCommit"]
    public_flavor = "base" if role.endswith("Base") else "gnome"
    image_flavor = _resolve_image_flavor(root, cell["variant"], public_flavor)
    need(image_flavor == cell["imageFlavors"][role],
         f"{cell['family']}.{role}: resolver target changed from the prepared plan")
    short_commit = git(root, "rev-parse", "--short", source_commit)
    base_digest = cell["baseImage"].rsplit("@", 1)[1]
    _HARNESS.verify_info(info, variant=cell["variant"], target=image_flavor, short_commit=short_commit,
                         base_image=cell["baseImage"], where=f"{cell['family']}.{role}")
    if role.startswith("modified"):
        installed = _HARNESS.package_query(log, cell["manager"], image_id, cell["package"])
        if cell["manager"] == "apt":
            need(installed.returncode == 0 and installed.stdout.strip() == b"installed",
                 f"{cell['family']}.{role}: package is not installed")
        else:
            need(installed.returncode == 0 and installed.stdout.strip(),
                 f"{cell['family']}.{role}: package is not installed")
        receipt_result = _HARNESS.receipt(log, image_id)
        need(receipt_result.returncode == 0, f"{cell['family']}.{role}: package receipt is missing")
        receipt_hash = _HARNESS.verify_modified_receipt(receipt_result.stdout, cell["variant"],
                                                        cell["manager"], cell["package"],
                                                        f"{cell['family']}.{role}")
        receipt_text = receipt_result.stdout.decode("utf-8")
        package_state = "installed"
    else:
        receipt_result = _HARNESS.receipt(log, image_id)
        need(receipt_result.returncode == 1, f"{cell['family']}.{role}: stock image has a generated package receipt")
        receipt_hash = None
        receipt_text = None
        if role == "stockBase":
            installed = _HARNESS.package_query(log, cell["manager"], image_id, cell["package"])
            need(installed.returncode == 1, f"{cell['family']}.stockBase: added package is present in stock")
        package_state = "stock"

    brand = None
    if role.startswith("modified"):
        os_release = _HARNESS.podman(log, image_id, "/usr/bin/cat", "/etc/os-release")
        need(os_release.returncode == 0, f"{cell['family']}.{role}: /etc/os-release is unreadable")
        values = _os_release_values(os_release.stdout, f"{cell['family']}.{role}")
        expected_pretty = cell["variant"].capitalize()
        need(values.get("HOME_URL") == plan["expectedBrand"]["homepage"],
             f"{cell['family']}.{role}: visible HOME_URL does not match fork identity")
        need(values.get("PRETTY_NAME") == expected_pretty,
             f"{cell['family']}.{role}: visible PRETTY_NAME does not match variant")
        metadata = _HARNESS.podman(log, image_id, "/usr/bin/cat",
            "/usr/share/plasma/look-and-feel/org.tunaos.desktop/metadata.json")
        need(metadata.returncode == 0 and plan["expectedBrand"]["projectName"].encode() in metadata.stdout,
             f"{cell['family']}.{role}: visible project-name marker is missing")
        theme = plan["expectedBrand"]["theme"]
        assets = {}
        for path, expected_hash in plan["ownedAssets"].items():
            runtime_path = "/" + path.removeprefix("system_files/")
            read = _HARNESS.podman(log, image_id, "/usr/bin/cat", runtime_path)
            need(read.returncode == 0 and sha256(read.stdout) == expected_hash,
                 f"{cell['family']}.{role}: owned asset is missing or stale: {path}")
            assets[path] = expected_hash
        plymouth = _plymouth_observation(log, image_id, cell["family"], role, theme)
        brand = {"status": plymouth["status"], "homeUrl": values["HOME_URL"],
                 "prettyName": values["PRETTY_NAME"], "projectNameMarker": plan["expectedBrand"]["projectName"],
                 "theme": theme, "assets": assets, "plymouth": plymouth}
    config_digest = plan["stockConfigSha256"] if role.startswith("stock") else plan["modifiedConfigSha256"]
    return {
        "role": role, "ref": ref, "sourceCommit": source_commit, "configSha256": config_digest,
        "publicFlavor": public_flavor, "imageFlavor": image_flavor,
        "baseImage": cell["baseImage"], "baseDigest": base_digest,
        "imageId": image_id, "manifestDigest": identity["manifestDigest"],
        "configDigest": identity["configDigest"], "platform": identity["platform"],
        "packageStatus": package_state, "packageReceiptSha256": receipt_hash,
        "packageReceipt": receipt_text, "branding": brand,
    }


def _qualify_family(plan: dict, cell: dict, root: Path, base_source_digest: str) -> dict:
    family = cell["family"]
    images = []
    log_path = root / f".config-only-{family}.log"
    try:
        with _HARNESS.CommandLog(log_path) as log:
            for role in ROLES:
                image = _image_record(plan, cell, role, root, log)
                images.append(image)
                if image["branding"] is not None:
                    need(image["branding"]["status"] == "passed",
                         f"{family}.{role}: effective visible branding failed: "
                         f"{image['branding']['plymouth']['reason'] or 'marker mismatch'}")
            stock, stock_hash, stock_receipt = _package_manifest(log, images[1]["imageId"], family,
                                                                 cell["variant"])
            custom, custom_hash, custom_receipt = _package_manifest(log, images[3]["imageId"], family,
                                                                   cell["variant"])
            missing = sorted(name for name, version in stock.items() if custom.get(name) != version)
            added = sorted(set(custom) - set(stock))
            need(not missing, f"{family}: customized desktop lost or changed stock packages: {missing[:20]}")
            need(cell["package"] in added, f"{family}: package parity did not observe the declared addition")
            parity = {"status": "passed", "stockInventorySha256": stock_hash,
                      "customInventorySha256": custom_hash, "stockInventoryReceipt": stock_receipt,
                      "customInventoryReceipt": custom_receipt, "stockPackageCount": len(stock),
                      "customPackageCount": len(custom), "missingOrChanged": missing, "added": added}
        return {"family": family, "status": "passed", "reason": None,
                "baseDigest": base_source_digest, "stockParity": parity, "images": images,
                "logSha256": sha256(log_path.read_bytes())}
    except (QualificationError, _HARNESS.QualificationError, OSError) as exc:
        return {"family": family, "status": "failed", "reason": str(exc),
                "baseDigest": base_source_digest, "stockParity": {"status": "not-run"},
                "images": images, "logSha256": sha256(log_path.read_bytes()) if log_path.exists() else None}
    finally:
        log_path.unlink(missing_ok=True)


def qualify(plan_path: Path, source: Path, output: Path) -> tuple[dict, bool]:
    need(not output.exists() and not output.is_symlink(), "evidence: refusing to replace existing directory")
    plan = validate_plan(read_json(plan_path))
    output.mkdir(parents=True)
    source_status = "failed"
    source_record = None
    source_reason = None
    families = []
    try:
        source_root = Path(source)
        need(not source_root.is_symlink() and source_root.is_dir(),
             "source: expected a real checkout")
        source_root = source_root.resolve()
        source_record = _source_record(plan, source_root, output / "source.log")
        source_status = "passed"
    except (QualificationError, _HARNESS.QualificationError, OSError) as exc:
        source_reason = str(exc)
    if source_status == "passed":
        for cell in plan["families"]:
            base_digest = None
            log_path = output / f"{cell['family']}-base-source.log"
            try:
                with _HARNESS.CommandLog(log_path) as log:
                    base_digest = _HARNESS.verify_base_source(log, cell["baseImage"])
                need(base_digest == cell["baseImage"].rsplit("@", 1)[1],
                     f"{cell['family']}: base source digest mismatch")
                families.append(_qualify_family(plan, cell, source_root, base_digest))
            except (QualificationError, _HARNESS.QualificationError, OSError) as exc:
                families.append({"family": cell["family"], "status": "failed", "reason": str(exc),
                                 "baseDigest": base_digest, "stockParity": {"status": "not-run"},
                                 "logSha256": sha256(log_path.read_bytes()) if log_path.exists() else None})
            finally:
                log_path.unlink(missing_ok=True)
    else:
        families = [{"family": cell["family"], "status": "not-run", "reason": "source-gate-failed",
                     "baseDigest": None, "stockParity": {"status": "not-run"}, "images": [], "logSha256": None}
                    for cell in plan["families"]]
    counts = {status: sum(item["status"] == status for item in families)
              for status in ("passed", "failed", "not-run")}
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "planSha256": sha256(plan_path.read_bytes()),
        "sourceGate": {"status": source_status, "reason": source_reason, "evidence": source_record},
        "families": families, "summary": counts,
        "qualificationPass": source_status == "passed" and counts == {"passed": 2, "failed": 0, "not-run": 0},
        "scope": "image-build-only; no install, boot, recovery, update, initramfs-rendering claim, publish, or production qualification",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report, report["qualificationPass"]


def _valid_passed_family(report_family: object, plan_cell: dict, plan: dict) -> bool:
    if not isinstance(report_family, dict) or report_family.get("family") != plan_cell["family"] \
            or report_family.get("status") != "passed" or report_family.get("reason") is not None:
        return False
    base_digest = plan_cell["baseImage"].rsplit("@", 1)[1]
    if report_family.get("baseDigest") != base_digest:
        return False
    images = report_family.get("images")
    if not isinstance(images, list) or len(images) != len(ROLES):
        return False
    by_role = {item.get("role"): item for item in images if isinstance(item, dict)}
    if set(by_role) != set(ROLES):
        return False
    for role in ROLES:
        image = by_role[role]
        expected_source = plan["stockCommit"] if role.startswith("stock") else plan["modifiedCommit"]
        expected_config = plan["stockConfigSha256"] if role.startswith("stock") else plan["modifiedConfigSha256"]
        expected_package = "stock" if role.startswith("stock") else "installed"
        receipt = image.get("packageReceiptSha256")
        receipt_text = image.get("packageReceipt")
        expected_public_flavor = "base" if role.endswith("Base") else "gnome"
        if (image.get("ref") != plan_cell["images"][role] or image.get("sourceCommit") != expected_source
                or image.get("configSha256") != expected_config or image.get("baseImage") != plan_cell["baseImage"]
                or image.get("baseDigest") != base_digest or image.get("publicFlavor") != expected_public_flavor
                or image.get("imageFlavor") != plan_cell["imageFlavors"][role]
                or not isinstance(image.get("imageId"), str) or not HEX.fullmatch(image["imageId"])
                or not isinstance(image.get("manifestDigest"), str) or not DIGEST.fullmatch(image["manifestDigest"])
                or not isinstance(image.get("configDigest"), str) or not DIGEST.fullmatch(image["configDigest"])
                or image.get("platform") != PLATFORM or image.get("packageStatus") != expected_package):
            return False
        if expected_package == "installed":
            expected_receipt = (f"# Written by build_scripts/lib/image-packages.sh for "
                                f"{plan_cell['variant']} ({plan_cell['manager']}).\n"
                                f"required\t{plan_cell['package']}\n")
            if (not isinstance(receipt, str) or not DIGEST.fullmatch(receipt)
                    or receipt_text != expected_receipt
                    or sha256(receipt_text.encode("utf-8")) != receipt):
                return False
            brand = image.get("branding")
            expected_theme = plan["expectedBrand"]["theme"]
            plymouth = brand.get("plymouth") if isinstance(brand, dict) else None
            plugin = plymouth.get("scriptPlugin") if isinstance(plymouth, dict) else None
            plugin_valid = isinstance(plugin, str) and plugin.startswith("/usr/lib") \
                and plugin.endswith("/plymouth/script.so")
            expected_checks = {"configuredTheme": True, "defaultThemeLink": True, "scriptPlugin": True}
            if (not isinstance(brand, dict) or brand.get("status") != "passed"
                    or brand.get("homeUrl") != plan["expectedBrand"]["homepage"]
                    or brand.get("prettyName") != plan_cell["variant"].capitalize()
                    or brand.get("projectNameMarker") != plan["expectedBrand"]["projectName"]
                    or brand.get("theme") != expected_theme or brand.get("assets") != plan["ownedAssets"]
                    or not isinstance(plymouth, dict)
                    or set(plymouth) != {"status", "configuredTheme", "defaultThemeLinkTarget",
                                         "scriptPlugin", "checks", "reason"}
                    or plymouth.get("status") != "passed"
                    or plymouth.get("configuredTheme") != expected_theme
                    or plymouth.get("defaultThemeLinkTarget") != f"{expected_theme}/{expected_theme}.plymouth"
                    or not plugin_valid or plymouth.get("checks") != expected_checks
                    or plymouth.get("reason") is not None):
                return False
        elif receipt is not None or receipt_text is not None or image.get("branding") is not None:
            return False
    parity = report_family.get("stockParity")
    if not isinstance(parity, dict) or parity.get("status") != "passed":
        return False
    stock_receipt = parity.get("stockInventoryReceipt")
    custom_receipt = parity.get("customInventoryReceipt")
    if not isinstance(stock_receipt, str) or not isinstance(custom_receipt, str):
        return False
    stock_bytes, custom_bytes = stock_receipt.encode("utf-8"), custom_receipt.encode("utf-8")
    if (sha256(stock_bytes) != parity.get("stockInventorySha256")
            or sha256(custom_bytes) != parity.get("customInventorySha256")):
        return False
    stock_inventory = _inventory_from_receipt(stock_bytes, plan_cell["family"], plan_cell["variant"])
    custom_inventory = _inventory_from_receipt(custom_bytes, plan_cell["family"], plan_cell["variant"])
    missing = sorted(name for name, version in stock_inventory.items() if custom_inventory.get(name) != version)
    added = sorted(set(custom_inventory) - set(stock_inventory))
    if (missing or parity.get("missingOrChanged") != missing or parity.get("added") != added
            or parity.get("stockPackageCount") != len(stock_inventory)
            or parity.get("customPackageCount") != len(custom_inventory)
            or plan_cell["package"] not in added):
        return False
    return True


def gate(plan_path: Path, report_path: Path) -> None:
    plan = validate_plan(read_json(plan_path))
    report = read_json(report_path)
    required = {"schemaVersion", "generatedAt", "planSha256", "sourceGate", "families", "summary",
                "qualificationPass", "scope"}
    need(isinstance(report, dict) and set(report) == required, "report: invalid fields")
    need(report["schemaVersion"] == SCHEMA_VERSION and report["planSha256"] == sha256(plan_path.read_bytes()),
         "report: stale or mismatched qualification plan")
    need(report["scope"] == "image-build-only; no install, boot, recovery, update, initramfs-rendering claim, publish, or production qualification",
         "report: invalid qualification scope")
    source = report["sourceGate"]
    need(isinstance(source, dict) and set(source) == {"status", "reason", "evidence"}
         and source["status"] == "passed" and source["reason"] is None,
         "source gate did not pass")
    evidence = source["evidence"]
    need(isinstance(evidence, dict) and evidence.get("stockCommit") == plan["stockCommit"]
         and evidence.get("modifiedCommit") == plan["modifiedCommit"]
         and evidence.get("stockConfigSha256") == plan["stockConfigSha256"]
         and evidence.get("modifiedConfigSha256") == plan["modifiedConfigSha256"]
         and evidence.get("stockAdapterSha256") == plan["stockAdapterSha256"]
         and evidence.get("modifiedAdapterSha256") == plan["modifiedAdapterSha256"]
         and evidence.get("changedPaths") == plan["changedPaths"],
         "source evidence is stale or mismatched")
    families = report["families"]
    need(isinstance(families, list) and len(families) == len(plan["families"]),
         "report: missing family result")
    results = {item.get("family"): item for item in families if isinstance(item, dict)}
    need(set(results) == {cell["family"] for cell in plan["families"]}, "report: family set mismatch")
    for cell in plan["families"]:
        need(_valid_passed_family(results[cell["family"]], cell, plan),
             f"{cell['family']}: failed, not-run, stale, or mismatched evidence")
    need(report["summary"] == {"passed": 2, "failed": 0, "not-run": 0}
         and report["qualificationPass"] is True, "report summary is not a complete pass")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--source", type=Path, default=ROOT)
    prepare_parser.add_argument("--plan", required=True, type=Path)
    build_prepare_parser = sub.add_parser("prepare-build")
    build_prepare_parser.add_argument("--source", type=Path, default=ROOT)
    build_prepare_parser.add_argument("--commit", required=True)
    qualify_parser = sub.add_parser("qualify")
    qualify_parser.add_argument("--source", required=True, type=Path)
    qualify_parser.add_argument("--plan", required=True, type=Path)
    qualify_parser.add_argument("--output", required=True, type=Path)
    gate_parser = sub.add_parser("gate")
    gate_parser.add_argument("--plan", required=True, type=Path)
    gate_parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            print(json.dumps(prepare(args.source, args.plan), sort_keys=True))
        elif args.command == "prepare-build":
            print(prepare_build(args.source, args.commit))
        elif args.command == "qualify":
            report, passed = qualify(args.plan, args.source, args.output)
            print(json.dumps(report["summary"], sort_keys=True))
            return 0 if passed else 1
        else:
            gate(args.plan, args.report)
            print("rpm: passed; apt: passed")
    except (QualificationError, _HARNESS.QualificationError, tunaos_config.ConfigError, OSError) as exc:
        print(f"ERROR: config-only image qualification: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
