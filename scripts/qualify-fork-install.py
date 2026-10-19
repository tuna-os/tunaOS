#!/usr/bin/env python3
"""Real GNOME installation to one guarded disposable disk, then target-only boot.

Opt-in qualification only. Uses the normal installer UI, pkexec password dialog,
original digest-preserving OCI payload, and native user-creation controls. No
production account/policy changes, public registry, or target SSH injection.
"""

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import signal
import string
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from secrets import choice, token_hex

ROOT = Path(__file__).resolve().parents[1]
USER = "canary"
GUEST_ROOT = "/var/tmp/fork-install-source"
GUEST_LAYOUT = GUEST_ROOT + "/source"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


LOGIN = module("fork_login", "qualify-fork-login.py")
INSTALLER = module("fork_installer", "qualify-fork-installer.py")
EXPORT = module("fork_export", "export-fork-source.py")
DISK = module("fork_disk", "qualify-fork-disk.py")
UI_MODULE = module("fork_ui", "fork-installer-ui.py")


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_image_id(value):
    """Podman inspect may omit sha256:, but no other ID spelling is admitted."""
    match = re.fullmatch(r"(?:sha256:)?([0-9a-f]{64})", value) if isinstance(value, str) else None
    require(match is not None, "source image has an invalid SHA-256 config ID")
    return "sha256:" + match[1]


def identity(image):
    data = json.loads(LOGIN.run(["podman", "image", "inspect", image], timeout=60))
    require(isinstance(data, list) and len(data) == 1, "source image inspection is ambiguous")
    info = data[0]
    require(isinstance(info, dict), "source image inspection is not an object")
    return {
        "reference": image,
        "id": canonical_image_id(info.get("Id")),
        "digest": info.get("Digest", ""),
        "repo_digests": info.get("RepoDigests", []),
        "repo_tags": info.get("RepoTags", []) or [],
    }


def validate_source_binding(source, inspected, reference):
    """Keep config identity, platform manifest digest and tracking ref distinct."""
    require(
        isinstance(source, dict) and isinstance(inspected, dict), "source provenance is malformed"
    )
    image_id = canonical_image_id(inspected.get("id"))
    manifest = inspected.get("digest")
    require(
        isinstance(manifest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", manifest),
        "source image has no exact inspected platform manifest digest",
    )
    require(
        source.get("source_image_id") == image_id
        and source.get("target_imgref") == reference
        and inspected.get("reference") == reference,
        "export is not the same finalized original image",
    )
    verified = source.get("verified_oci")
    require(
        isinstance(verified, dict) and verified.get("config_digest") == image_id,
        "verified OCI config differs from inspected original image",
    )
    require(
        source.get("source_manifest_digest") == manifest
        and verified.get("manifest_digest") == manifest,
        "verified OCI platform manifest differs from inspected original image",
    )
    require(
        source.get("preserved_digest") is True,
        "export did not preserve the original platform manifest",
    )


def selected_catalog_name(catalog, target_ref):
    """Name of the exact default catalog leaf in installer243's image screen.

    Direct references use the leaf name. Tag references use the nearest
    registry-owning node's name, never the channel or an unrelated group.
    Unlike the UI's neutral fallback, this qualification requires a real
    catalog name. It never derives the expected Done text from an OCI slug.
    """
    import copy

    if not isinstance(catalog, dict):
        raise ValueError("installer catalog is not an object")  # noqa: TRY004 - invalid serialized evidence
    catalog = copy.deepcopy(catalog)
    aliases = catalog.get("aliases", {})
    if not isinstance(aliases, dict):
        raise ValueError("installer catalog aliases are malformed")  # noqa: TRY004 - invalid serialized evidence

    # Match the native catalog loader's one-pass alias replacement. Do not
    # follow unresolved or recursive aliases into a guessed name/ref.
    def resolve(obj, depth=0):
        if depth > 32:
            raise ValueError("installer catalog aliases exceed depth bound")
        if isinstance(obj, dict):
            items = obj.items()
        elif isinstance(obj, list):
            items = enumerate(obj)
        else:
            return
        for key, value in items:
            if isinstance(value, str) and value.startswith("@"):
                if value[1:] not in aliases:
                    raise ValueError("installer catalog has an unresolved alias")
                obj[key] = copy.deepcopy(aliases[value[1:]])
            else:
                resolve(value, depth + 1)

    resolve(catalog)
    if (
        catalog.get("default_image") != target_ref
        or not isinstance(target_ref, str)
        or not target_ref
    ):
        raise ValueError("installer catalog default differs from the exact selected image")
    names = []
    count = 0

    def walk(nodes, registry="", registry_name="", depth=0):
        nonlocal count
        if not isinstance(nodes, list) or depth > 32:
            raise ValueError("installer catalog tree is malformed or too deep")
        for node in nodes:
            count += 1
            if not isinstance(node, dict) or count > 4096:
                raise ValueError("installer catalog node is malformed or exceeds bound")
            current_registry = node.get("registry", registry)
            current_name = node.get("name", "") if "registry" in node else registry_name
            ref = node.get("imgref")
            tagged = ref is None and "tag" in node
            if tagged and current_registry:
                if not isinstance(current_registry, str) or not isinstance(node["tag"], str):
                    raise ValueError("installer catalog tag reference is malformed")
                ref = current_registry + ":" + node["tag"]
            if ref is not None:
                if ref == target_ref:
                    name = current_name if tagged else node.get("name")
                    if (
                        not isinstance(name, str)
                        or not name.strip()
                        or name.strip().startswith("@")
                    ):
                        raise ValueError("selected catalog image has no explicit display name")
                    names.append(name.strip())
            else:
                walk(node.get("children", []), current_registry, current_name, depth + 1)

    walk(catalog.get("images"))
    if len(names) != 1:
        raise ValueError("exact selected catalog image is missing or ambiguous")
    return names[0]


def export_source(manifest, private):
    """Bound the unchanged exporter and its podman/skopeo child process group."""
    log = private / "source-export.log"
    with log.open("xb") as stream:
        process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "scripts/export-fork-source.py"),
                "--manifest",
                str(manifest),
                "--output",
                str(private / "export"),
            ],
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 1800
            while process.poll() is None:
                require(log.stat().st_size <= 16 * 1024 * 1024, "source export log exceeds bound")
                if time.monotonic() >= deadline:
                    raise TimeoutError("exact original OCI export timed out")
                time.sleep(1)
            require(process.returncode == 0, "exact original OCI export failed")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=30)
    receipt = private / "export/source-receipt.json"
    require(receipt.stat().st_size <= 2 * 1024 * 1024, "source receipt exceeds bound")
    return json.loads(receipt.read_text())


def bounded_serial_text(path):
    require(path.stat().st_size <= 64 * 1024 * 1024, "serial evidence exceeds bound")
    with path.open("rb") as stream:
        data = stream.read(64 * 1024 * 1024 + 1)
    require(len(data) <= 64 * 1024 * 1024, "serial evidence grew beyond bound")
    text = data.decode("utf-8", errors="replace")
    return text[: text.rfind("\n") + 1]


def redact(value, secrets=()):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "<redacted>")
        # No credential-bearing recipe/log line is ever admitted as evidence.
        return re.sub(r"\$6\$[./A-Za-z0-9]+\$[./A-Za-z0-9]+", "<redacted-hash>", value)
    if isinstance(value, dict):
        return {
            key: redact(item, secrets)
            for key, item in value.items()
            if key not in ("password", "passphrase", "recovery_key")
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    return value


def admin_group(image):
    LOGIN.admit_image(image)
    return "sudo" if "/grouper:" in image else "wheel"


def validate_recipe(recipe, source, target_path, group):
    """Validate the actual bundled Processor's non-secret preflight output."""
    expected = {
        "disk": target_path,
        "image": "oci:" + GUEST_LAYOUT,
        "targetImgref": source["target_imgref"],
        **source["storage"],
    }
    require(
        all(type(recipe.get(k)) is type(v) and recipe.get(k) == v for k, v in expected.items()),
        "bundled Processor output differs from exact source/target/storage",
    )
    require(recipe.get("encryption", {}).get("type") == "none", "unexpected encryption mode")
    require(
        recipe.get("user", {}).get("username") == USER and recipe["user"].get("groups") == [group],
        "native user recipe has unexpected account or groups",
    )
    require(
        recipe.get("imageType", "bootc") == "bootc"
        and not recipe.get("customMounts")
        and not recipe.get("varDisk"),
        "unexpected installation mode",
    )
    return {key: recipe[key] for key in expected}


def _nodes(lsblk):
    result = []

    def walk(node, disk):
        result.append((node, disk))
        for child in node.get("children", []):
            walk(child, disk)

    for disk in lsblk.get("blockdevices", []):
        walk(disk, disk)
    return result


def root_binding(observation, serial):
    """Bind a running root without pretending composefs '/' is block-backed.

    A kernel root=UUID token must resolve uniquely in lsblk to this serialized
    disk. An independently observed block mount at /, /sysroot or /var must
    resolve to that same partition. The actual '/' mount remains in evidence.
    """
    lsblk = observation["lsblk"]
    mounts = observation["findmnt"]
    require(
        lsblk.get("status") == "ok" and mounts.get("status") == "ok", "root collectors unavailable"
    )
    devices = _nodes(lsblk["output"])
    roots = [
        disk for disk in lsblk["output"].get("blockdevices", []) if disk.get("serial") == serial
    ]
    require(len(roots) == 1, "root disk serial is not unique")
    kernel = observation.get("kernel_root", {})
    require(
        kernel.get("status") == "ok" and kernel.get("kind") in ("uuid", "device"),
        "kernel root is not unambiguously observable",
    )
    matching = [
        (node, disk)
        for node, disk in devices
        if (
            (node.get("uuid") or "").casefold() == kernel["value"].casefold()
            if kernel["kind"] == "uuid"
            else node.get("path") == kernel["value"]
        )
    ]
    require(
        len(matching) == 1 and matching[0][1] is roots[0],
        "kernel root belongs to another or ambiguous disk",
    )
    node = matching[0][0]
    all_mounts = []

    def visit(mount):
        all_mounts.append(mount)
        for child in mount.get("children", []):
            visit(child)

    for item in mounts["output"].get("filesystems", []):
        visit(item)
    actual = [m for m in all_mounts if m.get("target") == "/"]
    require(len(actual) == 1, "actual running root mount is ambiguous")
    backing = [
        m
        for m in all_mounts
        if m.get("target") in ("/", "/sysroot", "/var") and m.get("maj:min") == node.get("maj:min")
    ]
    require(backing, "kernel root lacks an independently observed block mount")
    require(
        all(
            m.get("source", "").split("[", 1)[0] == node.get("path")
            and m.get("target") in node.get("mountpoints", [])
            for m in backing
        ),
        "backing mount source or observed mountpoint differs from root partition",
    )
    require(
        actual[0].get("maj:min") == node.get("maj:min")
        or actual[0].get("fstype") in ("overlay", "composefs", "erofs"),
        "unsupported non-block running root",
    )
    return {
        "serial": serial,
        "kernel_root": kernel,
        "partition": node["path"],
        "uuid": node.get("uuid"),
        "major_minor": node["maj:min"],
        "actual_root": actual[0],
        "backing_mounts": backing,
    }


def validate_target(observation, source, target_serial, observer_sha, source_boot_id):
    require(observation.get("boot_id") != source_boot_id, "target reused source boot ID")
    require(
        observation.get("observer_sha256") == observer_sha,
        "target observer differs from exact original payload",
    )
    require(
        observation.get("fork_config_sha256")
        in (source["fork_manifest_sha256"], source["fork_manifest_sha256"].removeprefix("sha256:")),
        "target fork config differs from source receipt",
    )
    bootc = observation.get("bootc", {})
    require(bootc.get("status") == "ok", "target bootc status is unavailable")
    output = bootc.get("output")
    require(
        isinstance(output, dict) and isinstance(output.get("status"), dict),
        "target bootc deployment status is unavailable",
    )
    booted = output["status"].get("booted")
    require(
        isinstance(booted, dict) and isinstance(booted.get("image"), dict),
        "target booted image is not ready",
    )
    image = booted["image"]
    require(
        image.get("imageDigest") == source["source_manifest_digest"],
        "observed installed digest differs from original platform manifest",
    )
    require(
        isinstance(image.get("image"), dict)
        and image["image"].get("image") == source["target_imgref"],
        "installed tracking reference differs from configured source",
    )
    block_result = observation.get("lsblk", {})
    require(
        block_result.get("status") == "ok" and isinstance(block_result.get("output"), dict),
        "target block-device observation is unavailable",
    )
    devices = block_result["output"].get("blockdevices", [])
    require(
        len(devices) == 1 and devices[0].get("serial") == target_serial,
        "target-only guest contains another system disk",
    )
    binding = root_binding(observation, target_serial)
    expected_groups = sorted([USER, admin_group(source["target_imgref"])])
    require(
        observation.get("account_status") == "ok"
        and type(observation.get("uid")) is int
        and observation["uid"] >= 1000
        and observation.get("account_groups_status") == "ok"
        and observation.get("account_primary_group") == USER
        and observation.get("account_groups") == expected_groups,
        "native target account groups differ from approved family groups",
    )
    verified = observation.get("identity_verifier", {})
    require(
        verified.get("status") == "ok" and verified.get("returncode") == 0,
        "target fork identity verifier failed",
    )
    return {
        "boot_id": observation["boot_id"],
        "installed_manifest_digest": image["imageDigest"],
        "tracking_reference": image["image"]["image"],
        "root_binding": binding,
        "observer_sha256": observer_sha,
        "fork_identity": "passed",
        "native_account_groups": expected_groups,
    }


GUEST_ADMIN = r"""
import grp, hashlib, json, os, pwd, subprocess
from pathlib import Path
group = __GROUP__
user = pwd.getpwnam("canary")
if user.pw_uid < 1000 or user.pw_name == "root":
    raise ValueError("not the isolated synthetic desktop account")
grp.getgrnam(group)
files = []
matching = False
for base in ("/etc/polkit-1/rules.d", "/usr/share/polkit-1/rules.d"):
    for path in sorted(Path(base).glob("*.rules")):
        data = path.read_bytes()
        if len(data) > 65536:
            raise ValueError("unbounded polkit rule")
        text = data.decode("utf-8")
        if "addAdminRule" in text:
            match = "unix-group:" + group in text
            matching = matching or match
            files.append({"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "names_expected_group": match})
if not matching:
    raise ValueError("existing polkit admin rules do not name the expected family group")
action = subprocess.check_output(["pkaction", "--action-id", "org.freedesktop.policykit.exec", "--verbose"], text=True)
if "auth_admin" not in action:
    raise ValueError("generic exec policy does not require administrator authentication")
before = subprocess.check_output(["id", "-nG", "canary"], text=True).split()
# Explicit approved existing group only. No sudoers, policy or root-password writes.
subprocess.run(["usermod", "-a", "-G", group, "canary"], check=True)
after = subprocess.check_output(["id", "-nG", "canary"], text=True).split()
if set(after) != set(before) | {group}:
    raise ValueError("unexpected supplementary-group change")
print(json.dumps({"user":"canary", "uid":user.pw_uid, "group":group, "before":before, "after":after, "admin_rules":files,
                  "policy_action":"org.freedesktop.policykit.exec", "passwordless_policy_written":False}))
"""


def guest_call(access, private, program, timeout=90):
    result = LOGIN.run(
        LOGIN.ssh_command(access, private) + ["python3 -"], input=program, timeout=timeout
    )
    return json.loads(result)


def source_observer(access, private):
    return LOGIN.observer(access, private)


def typed_login(qmp, screenshot, observe, private, out, password, label):
    deadline = time.monotonic() + 240
    selected = False
    while time.monotonic() < deadline:
        frame = screenshot(label + "-greeter.png")
        rows = LOGIN.words(frame)
        if LOGIN.password_prompt(frame, rows, private)["verified"]:
            break
        if not selected and LOGIN.find_word(rows, "username"):
            qmp.type(USER)
            qmp.key("ret")
            selected = True
        elif not selected and LOGIN.find_word(rows, USER):
            qmp.key("ret")
            selected = True
        time.sleep(3)
    else:
        raise ValueError("visible synthetic-user GDM Password prompt unavailable")
    before = observe()
    LOGIN.assert_no_login(before)
    frame = screenshot(label + "-password-prompt.png")
    prompt = LOGIN.password_prompt(frame, LOGIN.words(frame), private)
    require(prompt["verified"], "GDM prompt changed before secret input")
    qmp.type(password)
    qmp.key("ret")
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        after = observe()
        if LOGIN.session(after):
            actual = LOGIN.validate_login(before, after)
            (out / (label + "-login.json")).write_text(
                json.dumps(
                    {"before": before, "after": after, "session": actual, "prompt": prompt},
                    indent=2,
                )
                + "\n"
            )
            return before, after, actual
        time.sleep(3)
    raise ValueError("typed password did not produce a native gdm-password session")


def transfer_source(access, private, exported, receipt):
    layout = exported / "source"
    verified = EXPORT.verify_layout(
        layout,
        receipt["verified_oci"]["platform"],
        receipt["source_manifest_digest"],
        receipt["source_image_id"],
    )
    require(verified == receipt["verified_oci"], "source OCI changed before transfer")
    files = {"oci-layout": layout / "oci-layout", "index.json": layout / "index.json"}
    manifest = json.loads((exported / "source-manifest.json").read_text())
    for item in [
        {"digest": receipt["source_manifest_digest"]},
        manifest["config"],
        *manifest["layers"],
    ]:
        name = "blobs/sha256/" + item["digest"].split(":")[1]
        files[name] = layout / name
    expected = {
        name: {"sha256": digest(path), "size": path.stat().st_size} for name, path in files.items()
    }
    program = r"""
import hashlib,json,os,sys,tarfile
from pathlib import Path
root=Path(__ROOT__)
expected=__EXPECTED__
root.mkdir(mode=0o700)
seen=set()
with tarfile.open(fileobj=sys.stdin.buffer,mode="r|") as archive:
    for member in archive:
        if member.name not in expected or member.name in seen or not member.isfile() or member.size != expected[member.name]["size"]:
            raise ValueError("unexpected transferred OCI entry")
        destination=root/member.name
        destination.parent.mkdir(parents=True,exist_ok=True)
        h=hashlib.sha256(); count=0
        with archive.extractfile(member) as source,destination.open("xb") as target:
            while chunk:=source.read(1024*1024):
                target.write(chunk);h.update(chunk);count+=len(chunk)
        if count != member.size or h.hexdigest()!=expected[member.name]["sha256"]:
            raise ValueError("transferred OCI blob differs from pinned source")
        destination.chmod(0o444)
        seen.add(member.name)
if seen!=set(expected):raise ValueError("incomplete OCI transfer")
for directory in sorted((p for p in root.rglob("*") if p.is_dir()),reverse=True):directory.chmod(0o555)
root.chmod(0o555)
print(json.dumps({"files_verified":len(seen),"bytes_verified":sum(v["size"] for v in expected.values()),"layout":str(root)}))
""".replace("__ROOT__", repr(GUEST_LAYOUT)).replace("__EXPECTED__", repr(expected))
    # Parent directory is run-owned and fresh; archive never extracts links or
    # trusts supplied names. Secret-free source program is a shell-quoted argument.
    import shlex

    LOGIN.run(
        LOGIN.ssh_command(access, private) + ["umask 022; mkdir -m 0755 " + GUEST_ROOT], timeout=30
    )
    command = LOGIN.ssh_command(access, private) + ["python3 -c " + shlex.quote(program)]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # The wall-clock bound starts before streaming, including a blocked write.
    timed_out = threading.Event()

    def expire():
        timed_out.set()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)

    timer = threading.Timer(1800, expire)
    timer.start()
    try:
        with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
            for name, path in files.items():
                entry = tarfile.TarInfo(name)
                entry.size = path.stat().st_size
                entry.mode = 0o400
                with path.open("rb") as data:
                    archive.addfile(entry, data)
        process.stdin.close()
        process.stdin = None
        output, _ = process.communicate(timeout=1800)
        require(
            not timed_out.is_set() and process.returncode == 0,
            "exact OCI transfer failed or timed out",
        )
        return json.loads(output)
    finally:
        timer.cancel()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=30)


def prepare_guest_recipe(access, private, source, group):
    program = (
        r"""
import copy,hashlib,json,subprocess
from pathlib import Path
expected=__SOURCE__
group=__GROUP__
recipe_path=Path("/etc/bootc-installer/recipe.json")
catalog_path=Path("/etc/bootc-installer/images.json")
original=recipe_path.read_bytes(); catalog_original=catalog_path.read_bytes()
if "sha256:"+hashlib.sha256(original).hexdigest()!=expected["recipe_sha256"] or "sha256:"+hashlib.sha256(catalog_original).hexdigest()!=expected["catalog_sha256"]:
    raise ValueError("running source recipe/catalog differs from exported original")
recipe=json.loads(original);catalog=json.loads(catalog_original)
if recipe["imgref"]!=expected["target_imgref"] or recipe["local_imgref"]!=expected["original_local_imgref"]:
    raise ValueError("running source routing differs from export")
recipe["local_imgref"]=__LOCAL__
recipe["user"]={"groups":[group]}
recipe["steps"]["user"]={"template":"user"}
# Existing schema metadata requests the real user-creation page. No username,
# password, finals, synthetic probe or automatic widget advancement is supplied.
def enable(nodes):
    matched=0
    if isinstance(nodes,dict):
        if nodes.get("imgref")==expected["target_imgref"]:
            nodes["needs_user_creation"]=True;matched+=1
        for child in nodes.values():
            if isinstance(child,(dict,list)):matched+=enable(child)
    elif isinstance(nodes,list):
        for child in nodes:matched+=enable(child)
    return matched
if enable(catalog)!=1:raise ValueError("default source catalog leaf is ambiguous")
if "images" in recipe and enable(recipe["images"])!=1:raise ValueError("recipe source catalog leaf is ambiguous")
recipe_path.write_text(json.dumps(recipe,indent=2)+"\n")
catalog_path.write_text(json.dumps(catalog,indent=2)+"\n")
print(json.dumps({"scope":"disposable source guest only","local_imgref":recipe["local_imgref"],"target_imgref":recipe["imgref"],
 "source_recipe_sha256":expected["recipe_sha256"],"guest_recipe_sha256":hashlib.sha256(recipe_path.read_bytes()).hexdigest(),
 "native_user_step":True,"target_user_groups":[group],"username_or_password_prefilled":False}))
""".replace("__SOURCE__", repr(source))
        .replace("__GROUP__", repr(group))
        .replace("__LOCAL__", repr("oci:" + GUEST_LAYOUT))
    )
    return guest_call(access, private, program)


GUEST_PROCESSES = r"""
import hashlib,json,os,pwd
from pathlib import Path
user=pwd.getpwnam("canary")
expected=__HELPER__
rows=[]
for path in Path("/proc").glob("[0-9]*"):
    try:
        argv=[a.decode() for a in (path/"cmdline").read_bytes().split(b"\0") if a]
        if not argv:continue
        executable=Path(argv[0]).name
        if executable not in ("pkexec","fisherman","bootc"):continue
        # Only these known invocations; never report arbitrary command args.
        if executable=="pkexec" and argv[1:]==[expected,"-"]:
            rows.append({"pid":int(path.name),"kind":"pkexec","helper":expected})
        elif executable=="fisherman" and argv==[expected,"-"]:
            rows.append({"pid":int(path.name),"kind":"fisherman"})
        elif executable=="bootc" and argv[1:3]==["install","to-filesystem"]:
            fields={}
            for flag in ("--source-imgref","--target-imgref","--bootloader"):
                if flag in argv:
                    index=argv.index(flag)
                    if index+1<len(argv):fields[flag]=argv[index+1]
            rows.append({"pid":int(path.name),"kind":"bootc","fields":fields})
    except (OSError,UnicodeError):pass
print(json.dumps(rows))
"""


def bundled_preflight(access, private, source, target_path, group):
    # This executes the pinned app's pure mapper and non-destructive backend
    # validator; it does not touch the live UI's object state or install.
    code = (
        inspect.getsource(selected_catalog_name)
        + r"""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,"/app/share/org.bootcinstaller.Installer")
from bootc_installer.utils.processor import Processor
from bootc_installer.utils.fisherman_runner import HOST_PATH, LOG_PATH
from bootc_installer.utils.recipe import RecipeLoader
from types import SimpleNamespace
from bootc_installer.utils import copy as copy_text
recipe=RecipeLoader().raw
user_catalog=Path(os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config")))/"bootc-installer/images.json"
if user_catalog.exists():raise ValueError("unexpected per-user catalog overrides the source image catalog")
catalog_path=Path("/run/host/etc/bootc-installer/images.json")
def unique_pairs(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError("duplicate installer catalog key")
        value[key]=item
    return value
catalog=json.loads(catalog_path.read_text(),object_pairs_hook=unique_pairs)
selected_name=selected_catalog_name(catalog,__IMAGE__)
final={"disk":{"auto":{"disk":__TARGET__,"pretty_size":"64 GiB"},"filesystem":__FS__},
       "selected_image":__IMAGE__,"composefs_backend":__COMPOSEFS__,"bootloader":__BOOTLOADER__,"image_filesystem":__FS__,
       "hostname":"canary","encryption":{"type":"none"},"user":{"username":"canary","fullname":"canary","password":"","groups":[__GROUP__]}}
result=Processor.gen_install_recipe("/tmp/fork-preflight.log",[final],recipe)
print(json.dumps({"recipe":result,"helper":HOST_PATH,"log_path":LOG_PATH,
 "bundled_helper_sha256":hashlib.sha256(Path("/app/bin/fisherman").read_bytes()).hexdigest(),
 "selected_catalog_name":selected_name,"selected_catalog_ref":__IMAGE__,
 "selected_catalog_sha256":hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
 "done_title":copy_text.text(SimpleNamespace(recipe=recipe),"done_title",name=selected_name)}))
"""
    )
    replace = {
        "__TARGET__": target_path,
        "__FS__": source["storage"]["filesystem"],
        "__IMAGE__": source["target_imgref"],
        "__COMPOSEFS__": source["storage"]["composeFsBackend"],
        "__BOOTLOADER__": source["storage"]["bootloader"],
        "__GROUP__": group,
    }
    for key, value in replace.items():
        code = code.replace(key, repr(value))
    program = (
        INSTALLER.GUEST_COMMON
        + "\nvalue=json.loads(run(user_env()+"
        + repr(["flatpak", "run", "--system", "--command=python3", INSTALLER.APP, "-c", code])
        + ",timeout=180))\n"
        + r"""
helper=Path(value["helper"])
if not helper.is_absolute() or not helper.is_relative_to(user.pw_dir) or helper.resolve()!=helper or not helper.is_file() or helper.is_symlink():
    raise ValueError("unexpected staged backend executable")
info=helper.stat()
if info.st_uid!=uid or info.st_mode & 0o022:raise ValueError("staged backend ownership or mode is unsafe")
if Path(value["log_path"])!=helper.parent/"fisherman-output.log":raise ValueError("unexpected native backend log path")
validation=subprocess.run(user_env()+[str(helper),"validate","--json","-"],input=json.dumps(value["recipe"]),capture_output=True,text=True,timeout=30)
value["validation"]={"returncode":validation.returncode,"result":json.loads(validation.stdout)}
value["helper_sha256"]=hashlib.sha256(helper.read_bytes()).hexdigest()
if value["helper_sha256"]!=value["bundled_helper_sha256"]:raise ValueError("staged backend differs from pinned bundle")
probe=subprocess.run(user_env()+[str(helper),"probe","--json"],capture_output=True,text=True,timeout=60)
if probe.returncode:raise ValueError("native ordinary-user disk probe failed")
value["probe"]=json.loads(probe.stdout)
print(json.dumps(value))
"""
    )
    value = guest_call(access, private, program, 240)
    validate_recipe(value["recipe"], source, target_path, group)
    require(
        value["validation"]["returncode"] == 0 and not value["validation"]["result"].get("errors"),
        "bundled fisherman rejected preflight",
    )
    probe = value["probe"]
    require(probe.get("protocol_version") == 1, "unsupported native disk probe protocol")
    eligible = [disk for disk in probe.get("disks", []) if disk.get("eligible") is True]
    require(
        len(eligible) == 1
        and eligible[0].get("path") == target_path
        and eligible[0].get("size_bytes") == DISK.TARGET_BYTES
        and eligible[0].get("read_only") is False,
        "native installer does not have exactly one eligible guarded target",
    )
    return value


def accessibility(access, private, pids):
    require(
        pids and all(type(pid) is int and pid > 0 for pid in pids),
        "missing accessibility process binding",
    )
    code = UI_MODULE.SNAPSHOT.replace("__PIDS__", repr(pids))
    program = (
        INSTALLER.GUEST_COMMON
        + "\nprint(run(user_env()+"
        + repr(["python3", "-c", code])
        + ",timeout=90))\n"
    )
    return guest_call(access, private, program, 120)


def current_app(access, private, installed):
    observed = guest_call(access, private, INSTALLER.GUEST_OBSERVE)
    matches = [
        p
        for p in observed["instances"]
        if p["app_commit"] == installed["app_commit"] and p["application"] == INSTALLER.APP
    ]
    require(len(matches) == 1, "normal pinned installer process is not unique")
    return matches[0]


def guarded_disks(vm, creation, access, private, observer):
    host = DISK.validate_host_target(
        str(private), vm.source_spec["path"], vm.target_spec["path"], creation
    )
    qmp = vm.disk_evidence()
    mapped = DISK.validate_qmp_disks(
        qmp["query_block"], qmp["serial_queries"], vm.source_spec, vm.target_spec
    )
    facts = guest_call(
        access,
        private,
        r"""
import json,subprocess
serial=__SERIAL__
def run(args):return subprocess.check_output(args,text=True).strip()
blocks=json.loads(run(["lsblk","--json","--bytes","--paths","--output","NAME,KNAME,PATH,TYPE,SIZE,RO,SERIAL,MAJ:MIN,PKNAME,MOUNTPOINTS,FSTYPE,PTTYPE,UUID"]))
path="/dev/disk/by-id/virtio-"+serial
resolved=run(["readlink","-e","--",path])
print(json.dumps({"lsblk":blocks,"by_id":{"path":path,"resolved":resolved,"returncode":0},
 "wipefs":{"device":resolved,"returncode":0,"output":json.loads(run(["wipefs","--no-act","--json","--",resolved]))}}))
""".replace("__SERIAL__", repr(vm.target_spec["serial"])),
    )
    blocks = facts["lsblk"].get("blockdevices", [])
    require(
        len(blocks) == 2 and all(d.get("type") == "disk" for d in blocks),
        "guest must contain exactly two system disks",
    )
    target = [d for d in blocks if d.get("serial") == vm.target_spec["serial"]]
    source = [d for d in blocks if d.get("serial") == vm.source_spec["serial"]]
    require(len(target) == len(source) == 1, "guest serial mapping is ambiguous")
    target = target[0]
    require(
        target.get("size") == DISK.TARGET_BYTES
        and target.get("ro") is False
        and not target.get("children")
        and target.get("fstype") in (None, "")
        and target.get("pttype") in (None, "")
        and isinstance(target.get("mountpoints"), list)
        and not any(target["mountpoints"]),
        "target is not an empty writable 64 GiB disk",
    )
    require(
        facts["by_id"].get("returncode") == 0
        and facts["by_id"].get("path") == "/dev/disk/by-id/virtio-" + vm.target_spec["serial"]
        and facts["wipefs"].get("returncode") == 0
        and facts["wipefs"].get("device") == target.get("path"),
        "blank-disk evidence targets another device or failed",
    )
    require(
        facts["by_id"]["resolved"] == target.get("path")
        and target.get("path") == target.get("kname") == target.get("name"),
        "target by-id and kernel path disagree",
    )
    require(facts["wipefs"]["output"].get("signatures") == [], "target has existing signatures")
    require(
        mapped["source"]["virtual_size"] == source[0]["size"],
        "source size differs between host and guest",
    )
    binding = root_binding(observer(), vm.source_spec["serial"])
    require(binding["partition"] != target["path"], "target unexpectedly backs running root")
    require(
        host
        == DISK.validate_host_target(
            str(private), vm.source_spec["path"], vm.target_spec["path"], creation
        ),
        "target file changed during preflight",
    )
    return {
        "host_target": host,
        "qmp": qmp,
        "guest": facts,
        "source_root": binding,
        "target_path": target["path"],
        "preflight": "passed",
    }


def serial_observer(vm, module):
    last_seq = -1
    boot_id = None

    def read():
        nonlocal last_seq, boot_id
        deadline = time.monotonic() + (480 if boot_id is None else 30)
        while time.monotonic() < deadline:
            if vm.process.poll() is not None:
                raise ValueError("guest exited before fresh serial evidence")
            if vm.serial_path.exists():
                text = bounded_serial_text(vm.serial_path)
                # Ignore only an unfinished final write. Malformed complete rows
                # are fatal, and latest() never falls back to an earlier boot.
                text = text[: text.rfind("\n") + 1]
                if module.PREFIX in text:
                    try:
                        value = module.latest(text, boot_id=boot_id, after_seq=last_seq)
                    except ValueError as error:
                        if str(error) != "no fresh observer evidence":
                            raise
                    else:
                        boot_id, last_seq = value["boot_id"], value["seq"]
                        return value
            time.sleep(1)
        raise TimeoutError("no fresh bounded target observer evidence")

    return read


def wait_ssh(access, private):
    deadline = time.monotonic() + 480
    while time.monotonic() < deadline:
        try:
            return guest_call(access, private, 'import json; print(json.dumps({"ready":True}))', 15)
        except (OSError, subprocess.SubprocessError, ValueError):
            time.sleep(3)
    raise TimeoutError("restricted source SSH did not become ready")


def park_corral(access, private, name):
    directory = Path.home() / ".local/share/corral/vms" / name
    pid_path = directory / "qemu.pid"
    pid = int(pid_path.read_text().strip())
    require(pid > 1, "Corral QEMU PID is invalid")
    proc = Path("/proc") / str(pid)
    command = (proc / "cmdline").read_bytes().split(b"\0")
    require(
        command
        and b"qemu" in command[0]
        and any(str(directory).encode() in part for part in command),
        "Corral PID is not bound to this disposable VM",
    )
    start = (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]
    # This normal guest poweroff does not claim a committed install. The later
    # lifecycle requires an independently observed guest SHUTDOWN event.
    try:
        LOGIN.run(LOGIN.ssh_command(access, private) + ["systemctl poweroff"], timeout=30)
    except subprocess.CalledProcessError:
        pass  # SSH may close before systemctl returns; process exit is checked.
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if not proc.exists():
            break
        try:
            fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            require(fields[19] == start, "Corral PID was reused before parking")
            if fields[0] == "Z":
                break
        except FileNotFoundError:
            break
        time.sleep(1)
    else:
        raise TimeoutError("Corral source did not power off; refusing concurrent disk writer")
    path = directory / "disk.qcow2"
    require(path.is_file() and not path.is_symlink(), "Corral source disk is unavailable")
    return path, {"pid": pid, "guest_poweroff_requested": True, "writer_exited": True}


def launch_ui(access, private, installed, screenshot, logo):
    # Enable GTK's standard accessibility bridge; this is the normal app
    # entrypoint, not BOOTC_TEST, a preview, a widget setter, or an autoinstall.
    program = INSTALLER.GUEST_LAUNCH.replace(
        '["flatpak", "run", "--system", APP]',
        '["flatpak", "run", "--system", "--env=GTK_A11Y=atspi", APP]',
    )
    launched = guest_call(access, private, program)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        observation = guest_call(access, private, INSTALLER.GUEST_OBSERVE)
        frame = screenshot("cold-installer-welcome.png")
        pixels = INSTALLER.visible_branding(
            frame, logo, LOGIN.words(frame), ocr=LOGIN.words, private=private
        )
        if INSTALLER.validate_window(observation, launched, installed) and pixels["passed"]:
            return {"launch": launched, "window": observation, "welcome": pixels}
        time.sleep(3)
    raise ValueError("cold source normal installer window did not render verified branding")


def process_evidence(access, private, helper):
    return guest_call(access, private, GUEST_PROCESSES.replace("__HELPER__", repr(helper)))


def progress_evidence(access, private, log_path):
    program = r"""
import json
from pathlib import Path
path=Path(__PATH__)
result={"complete":False,"error":False,"events":0,"bytes":0}
if path.exists():
    size=path.stat().st_size
    if size>16*1024*1024:raise ValueError("backend log exceeds bound")
    result["bytes"]=size
    for line in path.read_text(errors="replace").splitlines():
        try:value=json.loads(line)
        except ValueError:continue
        if not isinstance(value,dict):continue
        result["events"]+=1
        if value.get("type")=="complete" and value.get("overall_pct")==100:result["complete"]=True
        if value.get("type")=="error":result["error"]=True
# Do not export log messages, argv, recipes or password hashes.
print(json.dumps(result))
""".replace("__PATH__", repr(log_path))
    return guest_call(access, private, program)


def run_wizard(vm, access, private, out, source, creation, observe, installed, password, report):
    app = current_app(access, private, installed)
    session = LOGIN.session(observe())
    require(session, "source desktop session disappeared")
    # Read actual shell PID through the admitted source SSH, never infer a PID
    # from a label or accept another user's authentication agent.
    shells = guest_call(
        access,
        private,
        INSTALLER.GUEST_COMMON
        + r"""
values=[]
for p in Path("/proc").glob("[0-9]*"):
    try:
        if p.stat().st_uid==uid and (p/"comm").read_text().strip()=="gnome-shell":values.append(int(p.name))
    except OSError:pass
if len(values)!=1:raise ValueError("synthetic desktop shell is not unique")
print(json.dumps(values))
""",
    )
    shell = shells[0]

    def screenshot(name):
        path = out / name
        vm.screenshot(path)
        return path

    ui = UI_MODULE.UI(
        vm.qmp, screenshot, lambda: accessibility(access, private, [app["pid"], shell]), LOGIN.words
    )
    # Probe accessibility before any navigation, so a missing platform bridge
    # fails without touching the install confirmation.
    require(ui.snapshot()["nodes"], "native accessibility bridge is unavailable")
    first = guarded_disks(vm, creation, access, private, observe)
    preflight = bundled_preflight(
        access, private, source, first["target_path"], admin_group(source["target_imgref"])
    )
    report["initial_disk_guard"] = first
    report["bundled_preflight"] = redact(preflight)
    helper = preflight["helper"]
    require(
        not process_evidence(access, private, helper), "privileged installer was already running"
    )
    # Welcome's selected primary row is the real app default. A fresh verified
    # welcome frame above precedes this ordinary Enter key.
    vm.qmp.key("ret")
    user_entered = False
    encryption_off = False
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        _, _, words, _ = ui.capture("wizard-page")
        if UI_MODULE.phrase_rows(words, "Create User"):
            require(not user_entered, "native user page did not advance")
            report["native_user_controls"] = [
                ui.field("Name", USER),
                ui.field("Username", USER),
                ui.field("Password", password, secret=True),
                ui.field("Confirm Password", password, secret=True),
            ]
            user_entered = True
            time.sleep(3)  # Native async fisherman field validation.
            ui.click("Next")
        elif UI_MODULE.phrase_rows(words, "Disk Encryption"):
            require(not encryption_off, "native encryption page did not advance")
            report["encryption_control"] = ui.toggle_off("Encrypt this disk")
            encryption_off = True
            ui.click("Next")
        elif UI_MODULE.phrase_rows(words, "Choose an Image"):
            require(
                UI_MODULE.phrase_rows(words, "Harbor Canary"),
                "image selection does not visibly name the fork",
            )
            ui.click("Next")
        elif UI_MODULE.phrase_rows(words, "Confirm installation"):
            require(user_entered, "native account creation page was not completed")
            require(
                UI_MODULE.phrase_rows(words, first["target_path"]),
                "confirmation does not visibly identify guarded target path",
            )
            # This repeats every host/QMP/serial/signature check immediately
            # before the single destructive native Install click.
            final = guarded_disks(vm, creation, access, private, observe)
            require(
                final["target_path"] == first["target_path"],
                "target mapping changed before confirmation",
            )
            repeated = bundled_preflight(
                access, private, source, final["target_path"], admin_group(source["target_imgref"])
            )
            require(
                repeated["helper_sha256"] == preflight["helper_sha256"]
                and repeated["helper"] == helper,
                "bundled backend changed before confirmation",
            )
            require(
                not process_evidence(access, private, helper),
                "privileged execution predates final click",
            )
            report["confirmation_disk_guard"] = final
            report["install_control"] = ui.click("Install")
            break
        elif UI_MODULE.phrase_rows(words, "Install Location"):
            raise ValueError("native probe did not auto-select the sole eligible disposable disk")
        time.sleep(2)
    else:
        raise TimeoutError("native wizard did not reach guarded install confirmation")
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        processes = process_evidence(access, private, helper)
        require(
            not any(p["kind"] in ("fisherman", "bootc") for p in processes),
            "privileged execution bypassed required password prompt",
        )
        if len([p for p in processes if p["kind"] == "pkexec"]) == 1:
            _, _, words, _ = ui.capture("authentication-wait")
            if UI_MODULE.phrase_rows(words, "Authentication Required"):
                report["pkexec_before_authentication"] = processes
                report["authentication"] = ui.authenticate(password, shell)
                break
        time.sleep(1)
    else:
        raise TimeoutError("normal pkexec did not request a native administrator password")
    invoked = []
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        for process in process_evidence(access, private, helper):
            if process["kind"] == "bootc":
                fields = process["fields"]
                require(
                    fields.get("--source-imgref") == "oci:" + GUEST_LAYOUT
                    and fields.get("--target-imgref") == source["target_imgref"],
                    "actual bootc invocation differs from exact admitted source",
                )
                if process not in invoked:
                    invoked.append(process)
        progress = progress_evidence(access, private, preflight["log_path"])
        require(not progress["error"], "native backend reported installation error")
        frame = screenshot("installation-progress.png")
        words = LOGIN.words(frame)
        if UI_MODULE.phrase_rows(words, preflight["done_title"]):
            require(
                progress["complete"] and invoked,
                "success UI lacks completed backend and observed exact bootc invocation",
            )
            require(
                not any(
                    p["kind"] in ("fisherman", "bootc", "pkexec")
                    for p in process_evidence(access, private, helper)
                ),
                "native backend is still running after success UI",
            )
            report["backend_completion"] = progress
            report["observed_bootc_invocations"] = invoked
            report["success_frame"] = frame.name
            report["observed_done_title"] = preflight["done_title"]
            report["installer_done_branding"] = (
                "passed" if preflight["done_title"] == "Harbor Canary is installed" else "failed"
            )
            report["installer_committed_install"] = "passed"
            return
        time.sleep(2)
    raise TimeoutError("native installation did not reach backend exit and visible success")


PASS_PHASES = (
    "installer_committed_install",
    "installed_target_identity",
    "target_typed_login",
    "target_wallpaper",
    "cleanup",
)


def qualification_passed(report):
    if report.get("error") or not all(report.get(key) == "passed" for key in PASS_PHASES):
        return False
    for phase in ("source", "target"):
        lifecycle = report.get(phase + "_lifecycle", {})
        shutdown = lifecycle.get("shutdown_event", {})
        if (
            lifecycle.get("clean_exit") is not True
            or shutdown.get("guest") is not True
            or shutdown.get("reason") != "guest-shutdown"
        ):
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--installer-artifact", type=Path, required=True)
    parser.add_argument("--wallpaper", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--corral", default="corral")
    args = parser.parse_args()
    group = admin_group(args.image)
    if os.geteuid() != 0:
        parser.error("run only on the isolated root qualification runner")
    for tool in (
        args.corral,
        "podman",
        "skopeo",
        "openssl",
        "ssh",
        "tesseract",
        "qemu-system-x86_64",
        "qemu-img",
    ):
        if not shutil.which(tool):
            parser.error("required qualification tool is missing: " + tool)
    if (
        shutil.which("tailscale")
        and subprocess.run(
            ["tailscale", "ip", "-4"], check=False, capture_output=True, timeout=10
        ).returncode
        == 0
    ):
        parser.error("refusing a runner with a connected Tailscale interface")
    from types import SimpleNamespace

    import yaml
    from PIL import Image

    with Image.open(args.wallpaper) as fixture:
        fixture.verify()
    vm_module = module("fork_vm", "qualify-fork-vm.py")
    observer_module = module("fork_serial", "fork-install-observer.py")
    args.output.mkdir(parents=True, exist_ok=False)
    out = args.output.resolve()
    private = Path(tempfile.mkdtemp(prefix="fork-install-"))
    private.chmod(0o700)
    name = "fork-install-" + token_hex(6)
    pinned = "localhost/fork-install-source/" + name + ":latest"
    derived = "localhost/corral-vmtest/" + name + ":latest"
    report = {
        "schema_version": 1,
        "scope": "functional installation on two disposable local qualification disks",
        "production_installer_qualified": False,
        "installer_done_branding": "not-run",
        "publishing": False,
        "target_ssh_injected": False,
        "installer_committed_install": "not-run",
        "installed_target_identity": "not-run",
        "target_typed_login": "not-run",
        "target_wallpaper": "not-run",
        "cleanup": "not-run",
    }
    source_vm = target_vm = None
    password = hashed = ""
    started = pinned_created = False

    def interrupted(signum, frame):
        raise InterruptedError("full installation proof interrupted")

    old_signal = signal.signal(signal.SIGTERM, interrupted)
    try:
        report["source_image"] = identity(args.image)
        source_id = report["source_image"]["id"]
        # Original source cannot contain the synthetic user or runtime secret.
        LOGIN.run(
            [
                "podman",
                "run",
                "--rm",
                "--pull=never",
                "--network=none",
                "--read-only",
                "--cap-drop=all",
                "--entrypoint",
                "sh",
                source_id,
                "-ec",
                "command -v getent >/dev/null; if getent passwd canary; then exit 1; fi",
            ],
            timeout=60,
        )
        observer_sha = LOGIN.run(
            [
                "podman",
                "run",
                "--rm",
                "--pull=never",
                "--network=none",
                "--read-only",
                "--cap-drop=all",
                "--entrypoint",
                "sha256sum",
                source_id,
                "/usr/libexec/tunaos/fork-install-observer.py",
            ],
            timeout=60,
        ).split()[0]
        require(
            observer_sha == digest(ROOT / "scripts/fork-install-observer.py"),
            "original payload lacks the exact canary-only serial observer",
        )
        report["observer_sha256"] = observer_sha
        source = export_source(args.manifest, private)
        # Retain both independent observations even if an exact binding fails.
        report["source_receipt"] = source
        validate_source_binding(source, report["source_image"], args.image)
        LOGIN.run(["podman", "tag", source_id, pinned], timeout=30)
        pinned_created = True
        require(
            identity(pinned)["id"] == source_id,
            "private source tag did not pin the original image",
        )
        password = "".join(choice(string.ascii_lowercase + string.digits) for _ in range(24))
        hashed = LOGIN.run(
            ["openssl", "passwd", "-6", "-stdin"], input=password + "\n", timeout=10
        ).strip()
        spec = LOGIN.make_spec(
            pinned,
            name,
            private / "corral",
            source["storage"]["filesystem"],
            "ssh.service" if group == "sudo" else "sshd.service",
        )
        spec.update(memory="8G", disk="64G")
        spec_path = private / "spec.yaml"
        spec_path.write_text(yaml.safe_dump(spec))
        spec_path.chmod(0o600)
        started = True
        with (private / "corral.log").open("w") as stream:
            result = subprocess.run(
                [args.corral, "vmtest", name, "-f", str(spec_path)],
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=2400,
                check=False,
            )
        raw = json.loads((private / "corral/result.json").read_text())
        report["corral_boot"] = {
            key: raw.get(key)
            for key in ("status", "exitCode", "ready", "readyBy", "bootSeconds", "kept")
        }
        require(
            result.returncode == 0
            and raw.get("status") == "passed"
            and raw.get("ready") is True
            and raw.get("readyBy") == "ssh"
            and raw.get("kept") is True,
            "derived preparation guest did not boot normally",
        )
        report["derived_image"] = identity(derived)
        require(
            report["derived_image"]["id"] != source_id
            and raw["layer"]["derived"]
            and raw["layer"]["base"] == pinned
            and identity(pinned)["id"] == source_id,
            "preparation guest is not derived from original image",
        )
        access = raw["ssh"]
        LOGIN.ssh_command(access, private)  # Admit loopback/key boundary now.
        report["test_admin"] = guest_call(
            access, private, GUEST_ADMIN.replace("__GROUP__", repr(group))
        )
        LOGIN.install_password(access, private, hashed)
        report["test_password"] = {
            "scope": "ephemeral source guest and native target account",
            "source_image_modified": False,
            "passwordless_policy_written": False,
            "logged": False,
        }
        observe = LOGIN.observer(access, private)
        qmp = LOGIN.QMP(Path.home() / ".local/share/corral/vms" / name / "qmp.sock")

        def corral_screen(filename):
            path = out / filename
            LOGIN.run(
                [args.corral, "screenshot", name, "-o", str(path), "--require-paint"], timeout=30
            )
            return path

        before, _after, active = typed_login(
            qmp, corral_screen, observe, private, out, password, "prepare"
        )
        installer_report = report.setdefault("prepared_installer", {})
        INSTALLER.qualify(
            SimpleNamespace(
                run=LOGIN.run,
                ssh_command=LOGIN.ssh_command,
                validate_login=LOGIN.validate_login,
                words=LOGIN.words,
            ),
            access,
            private,
            args.installer_artifact,
            out,
            corral_screen,
            observe,
            before,
            active["Id"],
            source_id,
            installer_report,
        )
        installed = installer_report["installed_bundle"]
        guest_call(
            access,
            private,
            INSTALLER.GUEST_COMMON
            + '\nrun(user_env()+["flatpak","kill",APP]); print(json.dumps({"stopped":True}))\n',
        )
        report["oci_transfer"] = transfer_source(access, private, private / "export", source)
        # Podman's supported OCI transport is exercised without installing,
        # privileges, host bind mounts, or a network registry.
        report["guest_oci_transport"] = guest_call(
            access,
            private,
            'import json,subprocess; value=subprocess.check_output(["podman","run","--rm","--network=none","--entrypoint","bootc",'
            + repr("oci:" + GUEST_LAYOUT)
            + ',"--version"],text=True,timeout=600); print(json.dumps({"transport":"oci","bootc_version":value.strip()}))',
            660,
        )
        report["guest_recipe"] = prepare_guest_recipe(access, private, source, group)
        source_disk, report["parked_preparation_guest"] = park_corral(access, private, name)
        qmp.close()
        target_disk, creation = vm_module.create_target(private)
        report["target_creation"] = creation
        source_vm = vm_module.VM(
            private,
            "source",
            source_disk,
            target_disk,
            ssh_port=int(access["port"]),
            target_creation=creation,
        )
        source_vm.start()
        wait_ssh(access, private)
        source_observe = serial_observer(source_vm, observer_module)

        def source_screen(filename):
            path = out / filename
            source_vm.screenshot(path)
            return path

        _, source_after, _ = typed_login(
            source_vm.qmp, source_screen, source_observe, private, out, password, "cold-source"
        )
        report["cold_source_ui"] = launch_ui(
            access, private, installed, source_screen, out / "installer-logo-reference.png"
        )
        report["installer_committed_install"] = "running"
        run_wizard(
            source_vm,
            access,
            private,
            out,
            source,
            creation,
            source_observe,
            installed,
            password,
            report,
        )
        # Do not click Restart now: a clean guest shutdown, no reset, must be
        # recorded before reopening precisely these target disk bytes.
        source_vm.stop(clean=True)
        report["source_lifecycle"] = source_vm.receipt
        expected_bytes = source_vm.receipt["disk_sha256_after"][str(target_disk)]
        require(
            digest(target_disk) == expected_bytes, "target disk changed after clean source stop"
        )
        target_vm = vm_module.VM(private, "target", None, target_disk, target_creation=creation)
        target_vm.start()
        report["target_lifecycle"] = target_vm.receipt
        require(
            target_vm.receipt["disk_sha256_before"][str(target_disk)] == expected_bytes,
            "cold target boot did not preserve exact installed disk bytes",
        )
        target_observe = serial_observer(target_vm, observer_module)
        deadline = time.monotonic() + 600
        last_error = "no observation"
        while time.monotonic() < deadline:
            observation = target_observe()
            try:
                verified = validate_target(
                    observation,
                    source,
                    target_vm.target_spec["serial"],
                    observer_sha,
                    source_after["boot_id"],
                )
            except ValueError as error:
                last_error = str(error)
                time.sleep(2)
            else:
                break
        else:
            raise ValueError("target identity did not become verifiable: " + last_error)
        report["installed_target"] = verified
        report["installed_target_identity"] = "passed"

        def target_screen(filename):
            path = out / filename
            target_vm.screenshot(path)
            return path

        target_before, _target_after, target_session = typed_login(
            target_vm.qmp, target_screen, target_observe, private, out, password, "installed-target"
        )
        report["target_typed_login"] = "passed"
        report["target_session"] = target_session
        target_vm.qmp.key("esc")
        time.sleep(8)
        frame = target_screen("installed-target-desktop.png")
        final = target_observe()
        require(
            LOGIN.validate_login(target_before, final)["Id"] == target_session["Id"],
            "target desktop observation changed authenticated session",
        )
        report["installed_target_final"] = validate_target(
            final, source, target_vm.target_spec["serial"], observer_sha, source_after["boot_id"]
        )
        require(
            all(
                final["wallpaper"].get(key) == "'" + LOGIN.WALLPAPER + "'"
                for key in ("picture-uri", "picture-uri-dark")
            ),
            "native target user's wallpaper setting differs from original payload",
        )
        report["target_wallpaper_pixels"] = LOGIN.wallpaper_match(frame, args.wallpaper)
        require(
            report["target_wallpaper_pixels"]["passed"],
            "cold installed desktop does not render the original canary wallpaper",
        )
        report["target_wallpaper"] = "passed"
        target_vm.stop(clean=True)
        report["target_lifecycle"] = target_vm.receipt
    except Exception as error:  # noqa: BLE001 - fail closed while preserving unconditional cleanup
        report["error"] = redact(str(error)[:4000], (password, hashed))
        if report["installer_committed_install"] == "running":
            report["installer_committed_install"] = "failed"
    finally:
        try:
            errors = []
            # Always reap every lifecycle process, including start/verification
            # failures. Forced cleanup never earns a clean shutdown receipt.
            for vm in (target_vm, source_vm):
                if vm is not None:
                    try:
                        vm.close()
                        report[vm.phase + "_lifecycle"] = vm.receipt
                        if vm.serial_path.exists():
                            rows = observer_module.parse_lines(bounded_serial_text(vm.serial_path))
                            # Only schema-validated nonsecret observer records leave
                            # private storage; raw console logs are never uploaded.
                            (out / (vm.phase + "-observations.json")).write_text(
                                json.dumps(rows, indent=2) + "\n"
                            )
                    except Exception as error:  # noqa: BLE001 - fail closed while preserving unconditional cleanup
                        errors.append(vm.phase + " VM cleanup/evidence: " + type(error).__name__)
            if started:
                try:
                    report["corral_cleanup"] = LOGIN.delete_vm(args.corral, name)
                    if not report["corral_cleanup"]["passed"]:
                        errors.append("Corral cleanup failed")
                except Exception as error:  # noqa: BLE001 - continue all independent cleanup
                    report["corral_cleanup"] = {"passed": False, "error": type(error).__name__}
                    errors.append("Corral cleanup raised " + type(error).__name__)
                try:
                    present = subprocess.run(
                        ["podman", "image", "exists", derived],
                        check=False,
                        capture_output=True,
                        timeout=30,
                    )
                    require(present.returncode in (0, 1), "derived image existence check failed")
                    if present.returncode == 0:
                        subprocess.run(
                            ["podman", "rmi", "--force", derived],
                            capture_output=True,
                            timeout=60,
                            check=True,
                        )
                        require(
                            subprocess.run(
                                ["podman", "image", "exists", derived],
                                check=False,
                                capture_output=True,
                                timeout=30,
                            ).returncode
                            == 1,
                            "derived image remains or its absence cannot be verified",
                        )
                except Exception as error:  # noqa: BLE001 - fail closed while preserving unconditional cleanup
                    errors.append("derived image cleanup: " + type(error).__name__)
            if pinned_created:
                try:
                    LOGIN.run(["podman", "untag", report["source_image"]["id"], pinned], timeout=30)
                    retained = identity(args.image)
                    report["source_image_after_cleanup"] = retained
                    require(
                        retained["id"] == report["source_image"]["id"]
                        and set(report["source_image"].get("repo_tags", [])).issubset(
                            retained.get("repo_tags", [])
                        ),
                        "original source identity or aliases changed",
                    )
                except Exception as error:  # noqa: BLE001 - fail closed while preserving unconditional cleanup
                    errors.append("source retention: " + type(error).__name__)
            # If a process could still be writing, retain the private directory and
            # fail cleanup rather than unlink a live disk underneath it.
            running = [
                vm
                for vm in (source_vm, target_vm)
                if vm is not None and vm.process is not None and vm.process.poll() is None
            ]
            if not running and (not started or report.get("corral_cleanup", {}).get("passed")):
                try:
                    shutil.rmtree(private)
                except OSError:
                    errors.append("private run cleanup failed")
            else:
                errors.append("private artifacts retained because VM cleanup is unverified")
            report["cleanup"] = "failed" if errors else "passed"
            if errors:
                report["cleanup_errors"] = errors
            report["screenshots"] = {path.name: digest(path) for path in out.glob("*.png")}
            # App's preparation report can contain ordinary debug messages but
            # cannot carry credentials. Sanitize the full final report regardless.
            report["status"] = "passed" if qualification_passed(report) else "failed"
            (out / "install-proof.json").write_text(
                json.dumps(redact(report, (password, hashed)), indent=2) + "\n"
            )
            password = hashed = ""
        finally:
            signal.signal(signal.SIGTERM, old_signal)
    print(json.dumps({key: report[key] for key in (*PASS_PHASES, "status")}))
    return 0 if qualification_passed(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
