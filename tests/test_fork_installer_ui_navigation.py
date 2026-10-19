"""Native run15 pixels plus source-shaped AT-SPI trees; no UI setters or guest actions."""

import copy
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fork_native_ui", ROOT / "scripts/fork-installer-ui.py"
)
UI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UI)
LOGIN_SPEC = importlib.util.spec_from_file_location(
    "fork_ui_login", ROOT / "scripts/qualify-fork-login.py"
)
LOGIN = importlib.util.module_from_spec(LOGIN_SPEC)
LOGIN_SPEC.loader.exec_module(LOGIN)
FIXTURES = ROOT / "tests/fixtures/fork-installer"
SIZE = (1280, 800)
PID = 200


def node(index, parent, role, name, bounds, **states):
    return {
        "id": index,
        "parent": parent,
        "pid": PID,
        "role": role,
        "name": name,
        "bounds": bounds,
        "states": {
            "visible": True,
            "showing": True,
            "enabled": True,
            "sensitive": True,
            "active": False,
            "focused": False,
            "checked": False,
            "defunct": False,
            **states,
        },
    }


def label_relation(value, row, title):
    value["nodes"][row]["relations"] = {"labelled_by": [title]}
    return value


def encryption_tree():
    # Shape verified from installer243 + libadwaita source. Coordinates are
    # measured screenshot bounds, not a claim that run15 captured this tree.
    return label_relation(
        {
            "schema_version": 1,
            "nodes": [
                node(0, None, "application", "Installer", None),
                node(1, 0, "frame", "Installer", [223, 32, 900, 768], active=True),
                node(2, 1, "list item", "", [384, 351, 576, 56]),
                node(3, 2, "panel", "", [384, 351, 576, 56]),
                node(4, 3, "label", "Encrypt this disk", [399, 362, 112, 19]),
                node(5, 3, "panel", "", [897, 351, 63, 56]),
                node(6, 5, "switch", "", [900, 366, 46, 26], checked=True, focused=True),
                node(7, 1, "list item", "", [384, 407, 576, 56]),
                node(8, 7, "password text", "Password", [399, 420, 460, 35]),
                node(9, 1, "push button", "Next", [929, 37, 68, 36]),
            ],
        },
        2,
        4,
    )


def welcome_tree(*, active=True):
    return label_relation(
        {
            "schema_version": 1,
            "nodes": [
                node(0, None, "application", "Installer", None),
                node(1, 0, "frame", "Installer", [223, 32, 900, 768], active=active),
                node(2, 1, "label", "Welcome to Harbor Canary", [450, 245, 450, 30]),
                node(3, 1, "list item", "", [384, 300, 576, 56], focused=active),
                node(4, 3, "label", "Install Harbor Canary", [400, 310, 200, 20]),
            ],
        },
        3,
        4,
    )


def words(phrase, x=400, y=365, *, line=1):
    result = []
    for word in phrase.split():
        result.append(
            {
                "text": word,
                "left": x,
                "top": y,
                "width": len(word) * 7,
                "height": 15,
                "conf": 96,
                "page_num": 1,
                "block_num": 1,
                "par_num": 1,
                "line_num": line,
            }
        )
        x += len(word) * 7 + 5
    return result


def mock_ui(monkeypatch, before, after=None, text=None):
    events = []
    instance = UI.UI(
        SimpleNamespace(key=lambda *k: events.append(("key", k))),
        None,
        lambda: after or before,
        None,
        app_pid=PID,
    )
    monkeypatch.setattr(
        instance, "capture", lambda _: (Path("fixture.png"), SIZE, text or [], before)
    )
    monkeypatch.setattr(instance, "point", lambda p, s: events.append(("point", p)))
    return instance, events


def test_unnamed_encryption_suffix_resolves_by_exact_row_ancestry(monkeypatch):
    before = encryption_tree()
    after = copy.deepcopy(before)
    after["nodes"][6]["states"]["checked"] = False
    instance, events = mock_ui(monkeypatch, before, after, words("Encrypt this disk"))
    result = instance.toggle_off("Encrypt this disk")
    assert events == [("point", (923, 379))]
    assert result["checked_before"] is True and result["checked_after"] is False
    assert result["pid"] == PID


@pytest.mark.parametrize(
    "change",
    [
        "wrong_pid",
        "wrong_row",
        "nested_row",
        "duplicate_switch",
        "duplicate_title",
        "other_title",
        "hidden",
        "disabled",
        "defunct",
        "outside_row",
        "outside_window",
        "wrong_label",
        "unchecked",
        "inactive",
        "no_focus",
        "ocr_other_row",
    ],
)
def test_encryption_binding_rejects_ambiguous_or_unrelated_controls(monkeypatch, change):
    value = encryption_tree()
    rows = value["nodes"]
    text = words("Encrypt this disk")
    if change == "wrong_pid":
        rows[6]["pid"] += 1
    elif change == "wrong_row":
        rows[6]["parent"] = 1
    elif change == "nested_row":
        rows[5]["role"] = "list item"
    elif change == "duplicate_switch":
        extra = copy.deepcopy(rows[6])
        extra["id"] = 10
        rows.append(extra)
    elif change == "duplicate_title":
        extra = copy.deepcopy(rows[4])
        extra["id"] = 10
        rows.append(extra)
    elif change == "other_title":
        rows[4]["name"] = "Use hardware-backed encryption"
    elif change in ("hidden", "disabled", "defunct"):
        rows[6]["states"][
            {"hidden": "showing", "disabled": "enabled", "defunct": "defunct"}[change]
        ] = change == "defunct"
    elif change == "outside_row":
        rows[6]["bounds"][1] = 420
    elif change == "outside_window":
        rows[1]["bounds"] = [223, 32, 200, 100]
    elif change == "wrong_label":
        rows[6]["name"] = "Another switch"
    elif change == "unchecked":
        rows[6]["states"]["checked"] = False
    elif change == "inactive":
        rows[1]["states"]["active"] = False
    elif change == "no_focus":
        rows[6]["states"]["focused"] = False
    elif change == "ocr_other_row":
        text = words("Encrypt this disk", y=450)
    instance, events = mock_ui(monkeypatch, value, text=text)
    with pytest.raises(ValueError):
        instance.toggle_off("Encrypt this disk")
    assert events == []


@pytest.mark.parametrize("change", ["still_on", "moved", "wrong_pid", "inactive", "different_row"])
def test_toggle_rechecks_native_state_and_binding_after_real_pointer(monkeypatch, change):
    before, after = encryption_tree(), encryption_tree()
    after["nodes"][6]["states"]["checked"] = False
    if change == "still_on":
        after["nodes"][6]["states"]["checked"] = True
    elif change == "moved":
        after["nodes"][6]["bounds"][0] -= 5
    elif change == "wrong_pid":
        after["nodes"][6]["pid"] += 1
    elif change == "inactive":
        after["nodes"][1]["states"]["active"] = False
    elif change == "different_row":
        after["nodes"][4]["name"] = "Other"
    instance, events = mock_ui(monkeypatch, before, after, words("Encrypt this disk"))
    with pytest.raises(ValueError):
        instance.toggle_off("Encrypt this disk")
    assert len(events) == 1


def test_welcome_escapes_overview_then_clicks_bound_title_not_enter(monkeypatch):
    monkeypatch.setattr(UI.time, "sleep", lambda _: None)
    before, after = welcome_tree(active=False), welcome_tree()
    instance, events = mock_ui(monkeypatch, before)
    captures = iter(
        [
            (Path("overview.png"), SIZE, words("Type to search", y=60), before),
            (Path("welcome.png"), SIZE, words("Install Harbor Canary", y=312), after),
        ]
    )
    monkeypatch.setattr(instance, "capture", lambda _: next(captures))
    result = instance.start_welcome()
    assert events[0] == ("key", ("esc",)) and events[1][0] == "point"
    assert len(events) == 2 and result["overview_escape"] is True
    assert result["active_window_and_focus_verified"] is True


def test_welcome_activates_bound_heading_before_primary_row(monkeypatch):
    before, after = welcome_tree(active=False), welcome_tree()
    text = words("Welcome to Harbor Canary", x=460, y=250) + words(
        "Install Harbor Canary", y=312, line=2
    )
    instance, events = mock_ui(monkeypatch, before)
    captures = iter(
        [(Path("welcome.png"), SIZE, text, before), (Path("focused.png"), SIZE, text, after)]
    )
    monkeypatch.setattr(instance, "capture", lambda _: next(captures))
    assert instance.start_welcome()["overview_escape"] is False
    assert len(events) == 2 and all(event[0] == "point" for event in events)


def test_welcome_never_clicks_when_overview_remains(monkeypatch):
    monkeypatch.setattr(UI.time, "sleep", lambda _: None)
    instance, events = mock_ui(
        monkeypatch, welcome_tree(active=False), text=words("Type to search")
    )
    with pytest.raises(ValueError, match="overview is still visible"):
        instance.start_welcome()
    assert events == [("key", ("esc",))]


@pytest.mark.parametrize("change", ["wrong_pid", "duplicate_row", "outside_frame", "other_title"])
def test_welcome_row_requires_exact_unique_pid_and_window_binding(monkeypatch, change):
    value = welcome_tree()
    if change == "wrong_pid":
        value["nodes"][4]["pid"] += 1
    elif change == "duplicate_row":
        value["nodes"] += [
            node(5, 1, "list item", "", [384, 400, 576, 56]),
            node(6, 5, "label", "Install Harbor Canary", [400, 410, 200, 20]),
        ]
    elif change == "outside_frame":
        value["nodes"][1]["bounds"] = [223, 32, 200, 100]
    elif change == "other_title":
        value["nodes"][4]["name"] = "Install stock image"
    instance, events = mock_ui(monkeypatch, value, text=words("Install Harbor Canary", y=312))
    with pytest.raises(ValueError):
        instance.start_welcome()
    assert events == []


def test_failure_diagnostics_omit_arbitrary_names_and_credential_values():
    value = encryption_tree()
    value["nodes"][8].update(
        name="temporary-secret", value="temporary-secret", text="temporary-secret"
    )
    value["nodes"][6]["relations"] = {"labelled_by": [4]}
    value["nodes"][6]["role_id"] = 129
    safe = UI.safe_snapshot(value)
    text = json.dumps(safe)
    assert "temporary-secret" not in text and '"value"' not in text and '"text"' not in text
    assert safe["nodes"][6]["relations"] == {"labelled_by": [4]}
    assert safe["nodes"][1]["states"]["active"] is True
    assert safe["nodes"][8]["name"] == "<omitted>"
    assert len(text) < 512 * 1024


@pytest.mark.parametrize(
    "change", ["limit", "cycle", "duplicate", "bad_parent", "cross_pid", "bad_relation"]
)
def test_diagnostic_tree_limits_and_ancestry_fail_closed(change):
    value = encryption_tree()
    if change == "limit":
        value["nodes"] *= (UI.MAX_NODES // len(value["nodes"]) + 1)
    elif change == "cycle":
        value["nodes"][1]["parent"] = 1
    elif change == "duplicate":
        value["nodes"][1]["id"] = 0
    elif change == "bad_parent":
        value["nodes"][2]["parent"] = 999
    elif change == "cross_pid":
        value["nodes"][2]["pid"] += 1
    elif change == "bad_relation":
        value["nodes"][6]["relations"] = {"labelled_by": [999]}
    with pytest.raises(ValueError):
        UI.safe_snapshot(value)


def test_native_snapshot_never_reads_text_values_or_invokes_widget_actions():
    compile(UI.SNAPSHOT.replace("__PIDS__", "[200]"), "<snapshot>", "exec")
    for token in (
        "get_text(",
        "get_text_iface(",
        "get_editable_text",
        "do_action(",
        "set_active(",
        "grab_focus(",
    ):
        assert token not in UI.SNAPSHOT
    assert "Atspi.StateType.ACTIVE" in UI.SNAPSHOT
    assert "Atspi.RelationType.LABELLED_BY" in UI.SNAPSHOT


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract is not installed")
def test_actual_run15_screenshots_and_exact_control_crop(tmp_path):
    provenance = json.loads((FIXTURES / "run15-navigation-provenance.json").read_text())
    assert provenance["run_id"] == 39253040831 and provenance["artifact_id"] == 12189877355
    for entry in provenance["files"]:
        data = (FIXTURES / entry["file"]).read_bytes()
        assert len(data) == entry["bytes"] and hashlib.sha256(data).hexdigest() == entry["sha256"]
    overview = LOGIN.words(FIXTURES / "run15-yellowfin-overview.png")
    assert UI.phrase_rows(overview, "Type to search")
    frame = FIXTURES / "run15-grouper-encryption.png"
    rows = LOGIN.words(frame)
    assert UI.phrase_rows(rows, "Encrypt this disk")
    # Force the crop branch; a newer Tesseract may repair the measured full-frame miss.
    instance = UI.UI(None, None, None, LOGIN.words, private=tmp_path)
    assert instance.label_point(frame, encryption_tree()["nodes"][9], [], "Next", SIZE) == (
        963,
        55,
    )
    with pytest.raises(ValueError):
        instance.label_point(frame, encryption_tree()["nodes"][9], [], "Install", SIZE)


def test_duplicate_visible_text_is_not_overridden_by_crop(monkeypatch, tmp_path):
    instance = UI.UI(
        None,
        None,
        None,
        lambda *a, **k: pytest.fail("ambiguous OCR cannot fall back"),
        private=tmp_path,
    )
    rows = words("Next", x=935, y=40) + words("Next", x=935, y=55, line=2)
    with pytest.raises(ValueError, match="ambiguous"):
        instance.label_point(Path("unused.png"), encryption_tree()["nodes"][9], rows, "Next", SIZE)


@pytest.mark.parametrize("action", ["welcome", "encryption", "install", "field"])
def test_overlapping_inactive_sibling_window_cannot_supply_control(monkeypatch, action):
    value = welcome_tree() if action == "welcome" else encryption_tree()
    nodes = value["nodes"]
    # Keep a genuinely focused child in active frame 1; move the target subtree
    # to another window with identical pixels/geometry and the same process ID.
    control_id = {"welcome": 3, "encryption": 2, "install": 9, "field": 7}[action]
    target = nodes[control_id]
    nodes.insert(2, node(100, 0, "frame", "Other installer window", nodes[1]["bounds"]))
    target["parent"] = 100
    nodes.append(node(101, 1, "push button", "Back", [230, 40, 40, 30], focused=True))
    if action == "install":
        target["name"] = "Install"
    text = (
        words("Install Harbor Canary", y=312) if action == "welcome" else words("Encrypt this disk")
    )
    instance, events = mock_ui(monkeypatch, value, text=text)
    with pytest.raises(ValueError, match="active installer window"):
        if action == "welcome":
            instance.start_welcome()
        elif action == "encryption":
            instance.toggle_off("Encrypt this disk")
        elif action == "install":
            instance.click("Install")
        else:
            instance.field("Password", "temporary-secret", secret=True)
    assert events == []


def test_final_install_rejects_focus_loss_before_click(monkeypatch):
    value = encryption_tree()
    value["nodes"][9]["name"] = "Install"
    value["nodes"][1]["states"]["active"] = False
    instance, events = mock_ui(monkeypatch, value, text=words("Install", x=940, y=45))
    with pytest.raises(ValueError, match="active visible window"):
        instance.click("Install")
    assert events == []


def test_second_titled_encryption_row_is_ambiguous(monkeypatch):
    value = encryption_tree()
    value["nodes"] += [
        node(10, 1, "list item", "", [384, 500, 576, 56]),
        node(11, 10, "label", "Encrypt this disk", [399, 510, 112, 19]),
    ]
    instance, events = mock_ui(monkeypatch, value, text=words("Encrypt this disk"))
    with pytest.raises(ValueError, match="one visible titled action row"):
        instance.toggle_off("Encrypt this disk")
    assert events == []


@pytest.mark.parametrize(
    "role", ["application", "panel", "password text", "frame", "list item", "label", "switch"]
)
def test_safe_diagnostic_accepts_native_gtk_role_names(role):
    value = encryption_tree()
    value["nodes"][3]["role"] = role
    assert UI.safe_snapshot(value)["nodes"][3]["role"] == role


@pytest.mark.parametrize("relation_case", ["valid", "unresolved", "duplicate"])
@pytest.mark.parametrize("mapping", ["direct", "proxy", "wrong", "collision", "missing", "ambiguous"])
def test_snapshot_label_relations_accept_unhashable_gi_wrappers(monkeypatch, capsys, relation_case, mapping):
    import sys
    import types

    class Accessible:
        __hash__ = None

        def __init__(self, key, role, name, children=()):
            self.key, self.role, self.name, self.children = key, role, name, children

        def __eq__(self, other):
            return isinstance(other, Accessible) and self.key == other.key

        def get_process_id(self):
            return 700 if mapping != "direct" else PID

        def get_role_name(self):
            return self.role

        def get_role(self):
            return 1

        def get_name(self):
            return self.name

        def get_child_count(self):
            return len(self.children)

        def get_child_at_index(self, index):
            return self.children[index]

        def get_state_set(self):
            return SimpleNamespace(contains=lambda value: value != "defunct")

        def get_component_iface(self):
            return SimpleNamespace(
                get_extents=lambda _: SimpleNamespace(x=1, y=1, width=30, height=20)
            )

        def get_relation_set(self):
            if self.key != 1:
                return []
            # Distinct wrapper, equal native object, deliberately unhashable.
            relation = SimpleNamespace(
                get_relation_type=lambda: 1,
                get_n_targets=lambda: 2 if relation_case == "unresolved" else 1,
                get_target=lambda offset: Accessible(2 + offset, "label", "Encrypt this disk"),
            )
            return [relation, relation] if relation_case == "duplicate" else [relation]

    label = Accessible(2, "label", "Encrypt this disk")
    row = Accessible(1, "list item", "", [label])
    root = Accessible(9, "desktop", "", [Accessible(0, "application", "Installer", [row])])
    if mapping == "ambiguous":
        root.children.append(Accessible(10, "application", "Installer", []))
    if mapping == "missing":
        root.children.clear()
    atspi = SimpleNamespace(
        set_timeout=lambda *a: None,
        get_desktop=lambda _: root,
        StateType=SimpleNamespace(
            **{
                key.upper(): key
                for key in (
                    "showing",
                    "visible",
                    "enabled",
                    "sensitive",
                    "focused",
                    "checked",
                    "active",
                    "defunct",
                )
            }
        ),
        CoordType=SimpleNamespace(SCREEN=0),
        RelationType=SimpleNamespace(LABELLED_BY=1, DESCRIBED_BY=2),
    )
    gi = types.ModuleType("gi")
    gi.require_version = lambda *a: None
    repository = types.ModuleType("gi.repository")
    repository.Atspi = atspi
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)

    def observe():
        bindings = [PID] if mapping == "direct" else {PID: 700}
        if mapping == "wrong":
            bindings = {PID: 701}
        if mapping == "collision":
            bindings = {PID: 700, PID + 1: 700}
        exec(UI.SNAPSHOT.replace("__PIDS__", repr(bindings)), {})  # noqa: S102 - execute the owned read-only observer against fixture GI

    if mapping in {"wrong", "collision", "missing", "ambiguous"}:
        with pytest.raises(ValueError, match="process bindings collide|exactly one application root"):
            observe()
        assert capsys.readouterr().out == ""
        return
    if relation_case == "duplicate":
        with pytest.raises(ValueError, match="unresolved target|duplicate accessibility"):
            observe()
        assert capsys.readouterr().out == ""
        return
    observe()
    value = json.loads(capsys.readouterr().out)
    assert value["nodes"][1]["relations"] == {"labelled_by": [2]}
    assert value["nodes"][1]["pid"] == PID
    assert value["nodes"][1]["bus_pid"] == (PID if mapping == "direct" else 700)
    assert UI.safe_snapshot(value)["nodes"][1]["relations"] == {"labelled_by": [2]}
    if relation_case == "unresolved":
        assert value["nodes"][1]["unresolved_relations"] == {"labelled_by": 1}
        with pytest.raises(ValueError, match="selected control has an unresolved"):
            UI.complete_labels(value["nodes"][1])


@pytest.mark.parametrize("change", ["row_name", "row_relation", "switch_relation", "unbound_title"])
def test_row_title_contradictions_are_rejected(monkeypatch, change):
    value = encryption_tree()
    if change == "row_name":
        value["nodes"][2]["name"] = "Use hardware-backed encryption"
    elif change == "row_relation":
        value["nodes"][2]["relations"]["labelled_by"] = [8]
    elif change == "switch_relation":
        value["nodes"][6]["relations"] = {"labelled_by": [8]}
    else:
        del value["nodes"][2]["relations"]
    instance, events = mock_ui(monkeypatch, value, text=words("Encrypt this disk"))
    with pytest.raises(ValueError):
        instance.toggle_off("Encrypt this disk")
    assert events == []


def test_exact_row_name_can_bind_title_without_relation():
    value = encryption_tree()
    del value["nodes"][2]["relations"]
    value["nodes"][2]["name"] = "Encrypt this disk"
    assert UI.row_switch(value, "Encrypt this disk", PID, SIZE)[2]["id"] == 6


@pytest.mark.parametrize("change", ["two_active", "two_inactive", "frame_only_focus"])
def test_welcome_ambiguous_or_frame_only_focus_cannot_trigger_recovery(monkeypatch, change):
    value = welcome_tree()
    if change == "frame_only_focus":
        value["nodes"][1]["states"]["focused"] = True
        value["nodes"][3]["states"]["focused"] = False
    else:
        value["nodes"].append(node(5, 0, "frame", "Other", [223, 32, 900, 768], active=True))
        if change == "two_inactive":
            for row in value["nodes"]:
                row["states"]["active"] = False
    text = words("Welcome to Harbor Canary", x=460, y=250)
    instance, events = mock_ui(monkeypatch, value, text=text)
    with pytest.raises(ValueError):
        instance.start_welcome()
    assert events == []


@pytest.mark.parametrize("change", ["inactive", "moved", "role", "sibling", "success"])
def test_field_rechecks_active_window_and_exact_control_before_typing(monkeypatch, change):
    before, after = encryption_tree(), encryption_tree()
    after["nodes"][6]["states"]["focused"] = False
    after["nodes"][8]["states"]["focused"] = True
    if change == "inactive":
        after["nodes"][1]["states"]["active"] = False
    elif change == "moved":
        after["nodes"][8]["bounds"][0] += 1
    elif change == "role":
        after["nodes"][8]["role"] = "text"
    elif change == "sibling":
        after["nodes"].insert(2, node(100, 0, "frame", "Other", [223, 32, 900, 768]))
        next(n for n in after["nodes"] if n["id"] == 8)["parent"] = 100
        after["nodes"].append(node(101, 1, "push button", "Back", [230, 40, 40, 30], focused=True))
    instance, events = mock_ui(monkeypatch, before, after)
    instance.qmp.type = lambda value: events.append(("typed", value))
    if change == "success":
        assert instance.field("Password", "temporary-secret", secret=True)["typed"] is True
        assert events[1:] == [("key", ("ctrl", "a")), ("typed", "temporary-secret")]
    else:
        with pytest.raises(ValueError):
            instance.field("Password", "temporary-secret", secret=True)
        assert len(events) == 1 and events[0][0] == "point"


def test_unit_workflow_installs_native_ocr_dependency():
    workflow = (ROOT / '.github/workflows/test.yml').read_text()
    assert 'sudo apt-get install -y python3-gi dbus-daemon dbus-bin tesseract-ocr' in workflow


@pytest.mark.parametrize('program,expected', [
    ('raise ValueError("accessibility relation target total exceeds bound")', 'accessibility relation target total exceeds bound'),
    ('raise RuntimeError("private-field-value")', '<omitted>'),
    ('raise AttributeError("private-field-value")', '<omitted>'),
])
def test_probe_failure_keeps_structural_trace_without_field_values(capsys, program, expected):
    exec(UI.diagnostic_program(program, '<fork-accessibility>'), {})
    output = capsys.readouterr().out
    assert 'private-field-value' not in output
    error = json.loads(output)['probe_error']
    assert error['message'] == expected
    assert error['traceback'][-1] == {'file': '<fork-accessibility>', 'line': 1}
    assert len(error['message_sha256']) == 64
    assert error['exception_type'] in {'ValueError', 'RuntimeError', 'AttributeError'}


def test_probe_wrapper_preserves_success_json(capsys):
    exec(UI.diagnostic_program('print(json.dumps({"schema_version": 1, "nodes": []}))', '<fork-accessibility>'), {})
    assert json.loads(capsys.readouterr().out) == {'schema_version': 1, 'nodes': []}


def test_unrelated_off_tree_relation_does_not_authorize_selected_control():
    value = encryption_tree()
    value['nodes'][8]['unresolved_relations'] = {'labelled_by': 1}
    assert UI.safe_snapshot(value)['nodes'][8]['unresolved_relations'] == {'labelled_by': 1}
    assert UI.row_switch(value, 'Encrypt this disk', PID, SIZE)[2]['id'] == 6


@pytest.mark.parametrize('index', [2, 4, 6])
def test_selected_row_title_or_switch_with_off_tree_label_stays_rejected(index):
    value = encryption_tree()
    value['nodes'][index]['unresolved_relations'] = {'labelled_by': 1}
    with pytest.raises(ValueError, match='selected control has an unresolved'):
        UI.row_switch(value, 'Encrypt this disk', PID, SIZE)


def test_selected_install_button_with_off_tree_label_is_rejected():
    value = encryption_tree()
    value['nodes'][9]['name'] = 'Install'
    value['nodes'][9]['unresolved_relations'] = {'described_by': 1}
    with pytest.raises(ValueError, match='selected control has an unresolved'):
        UI.select(value, 'Install', ('push button',), pid=PID)


@pytest.mark.parametrize('mismatch', [None, 'uid', 'exe', 'socket', 'app', 'restart'])
def test_proxy_binding_uses_exact_pinned_process_socket(monkeypatch, tmp_path, mismatch):
    import socket
    import stat
    import struct

    app = {'pid': 200, 'uid': 1000, 'application': 'org.bootcinstaller.Installer', 'app_commit': 'a' * 64}
    for pid, start in [(200, 123), (700, 456)]:
        proc = tmp_path / str(pid)
        proc.mkdir()
        (proc / 'stat').write_text(str(pid) + ' (name with spaces) S ' + '0 ' * 18 + str(start))
    (tmp_path / '700/exe').symlink_to('/usr/bin/' + ('other' if mismatch == 'exe' else 'xdg-dbus-proxy'))
    endpoint = tmp_path / '200/root/run/flatpak/at-spi-bus'
    actual_stat = Path.stat
    def fake_stat(path, *args, **kwargs):
        if path == endpoint:
            return SimpleNamespace(st_mode=stat.S_IFSOCK if mismatch != 'socket' else stat.S_IFREG, st_uid=1000, st_dev=1, st_ino=27)
        if path == tmp_path / '700':
            return SimpleNamespace(st_uid=1000)
        return actual_stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', fake_stat)
    class Peer:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, seconds): assert seconds == 3
        def connect(self, path): assert path == str(endpoint)
        def getsockopt(self, level, option, size):
            assert (level, option, size) == (socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            if mismatch == 'restart':
                (tmp_path / '200/stat').write_text('200 (changed) S ' + '0 ' * 18 + '124')
            return struct.pack('3i', 700, 1001 if mismatch == 'uid' else 1000, 1000)
    monkeypatch.setattr(socket, 'socket', lambda *args: Peer())
    scope = {'PROC_ROOT': tmp_path, 'uid': 1000, 'stat': stat, 'instances': lambda: [] if mismatch == 'app' else [app]}
    exec(UI.PROXY_BINDING, scope)
    if mismatch:
        with pytest.raises(ValueError, match='installer process changed|not its user|binding changed'):
            scope['bind_accessibility'](app)
    else:
        proof = scope['bind_accessibility'](app)
        assert proof['host_pid'] == 200 and proof['bus_pid'] == 700
        assert proof['app_commit'] == app['app_commit']
        assert proof['process_start'] == '123' and proof['proxy_start'] == '456'


@pytest.mark.parametrize('peers,expected', [([700, 43], [700, 43]), (['private'], []), (list(range(1, 70)), [])])
def test_failed_probe_exposes_only_bounded_numeric_bus_peers(capsys, peers, expected):
    program = 'observed_bus_pids = ' + repr(peers) + '\nraise ValueError("accessibility process must have exactly one application root")'
    exec(UI.diagnostic_program(program, '<fork-accessibility>'), {})
    value = json.loads(capsys.readouterr().out)
    assert value['probe_error']['observed_bus_pids'] == expected
    assert 'private' not in json.dumps(value)


@pytest.mark.parametrize('case', ['deep', 'cycle', 'depth_limit', 'node_limit'])
def test_collector_bounds_deep_gtk_tree_and_rejects_cycles(monkeypatch, capsys, case):
    import sys
    import types

    class Accessible:
        __hash__ = None
        serial = 0
        def __init__(self, children=(), *, key=None):
            type(self).serial += 1
            self.key = key if key is not None else type(self).serial
            self.children = list(children)
        def __eq__(self, other):
            return isinstance(other, Accessible) and self.key == other.key
        def get_process_id(self): return PID
        def get_role_name(self): return 'panel'
        def get_role(self): return 1
        def get_name(self): return ''
        def get_child_count(self): return len(self.children)
        def get_child_at_index(self, index): return self.children[index]
        def get_relation_set(self): return []
        def get_state_set(self): return SimpleNamespace(contains=lambda _: True)
        def get_component_iface(self): raise ValueError('no component')

    app = Accessible()
    if case in {'deep', 'depth_limit'}:
        cursor = app
        for _ in range(35 if case == 'deep' else UI.MAX_DEPTH + 1):
            child = Accessible()
            cursor.children.append(child)
            cursor = child
    elif case == 'cycle':
        # Same native accessible, a different unhashable GI wrapper.
        app.children.append(Accessible([Accessible(key=app.key)]))
    else:
        app.children.extend(Accessible() for _ in range(UI.MAX_NODES))
    root = Accessible([app])
    states = ('showing', 'visible', 'enabled', 'sensitive', 'focused', 'checked', 'active', 'defunct')
    atspi = SimpleNamespace(set_timeout=lambda *a: None, get_desktop=lambda _: root,
        StateType=SimpleNamespace(**{k.upper(): k for k in states}),
        RelationType=SimpleNamespace(LABELLED_BY=1, DESCRIBED_BY=2))
    gi = types.ModuleType('gi')
    gi.require_version = lambda *a: None
    repository = types.ModuleType('gi.repository')
    repository.Atspi = atspi
    monkeypatch.setitem(sys.modules, 'gi', gi)
    monkeypatch.setitem(sys.modules, 'gi.repository', repository)
    program = UI.SNAPSHOT.replace('__PIDS__', repr({PID: PID}))
    exec(UI.diagnostic_program(program, '<fork-accessibility>'), {})
    value = json.loads(capsys.readouterr().out)
    if case == 'deep':
        assert value['traversal'] == {'visited_nodes': 36, 'max_depth': 35}
        nodes = UI.tree(value)
        assert len(UI.ancestors(nodes[35], nodes)) == 35
        assert UI.safe_snapshot(value)['traversal'] == value['traversal']
    else:
        expected = {'cycle': 'accessibility child cycle detected',
                    'depth_limit': 'accessibility depth exceeds bound',
                    'node_limit': 'accessibility node count exceeds bound'}
        error = value['probe_error']
        assert error['message'] == expected[case]
        assert error['traversal']['visited_nodes'] <= UI.MAX_NODES
        assert error['traversal']['max_depth'] <= UI.MAX_DEPTH + 1


def run20_tree():
    # Actual read-only run39301862725, artifact12214686184. Known static
    # labels/structure only; unrelated names were filtered by safe_snapshot.
    return json.loads((FIXTURES / "run20-accessibility.json").read_text())


def test_real_gtk4_tree_has_page_scoped_keyboard_targets():
    value = run20_tree()
    pid = value["nodes"][0]["pid"]
    window, focused = UI.keyboard_window(value, pid)
    assert window["id"] == 1 and focused["id"] == 29
    target, focused = UI.keyboard_target(value, "Welcome to Harbor Canary", "Install Harbor Canary", ("list item",), pid)
    assert target == focused
    password, _ = UI.keyboard_target(value, "Create User", "Password", ("password text",), pid)
    assert password["id"] == 134  # Encryption Password81 must never match.
    install, _ = UI.keyboard_target(value, "Confirm installation", "Install", ("push button",), pid)
    assert install["id"] == 172 and install["states"]["enabled"] is False


@pytest.mark.parametrize("change", ["disabled", "wrong_process", "duplicate", "inactive"])
def test_keyboard_target_keeps_identity_uniqueness_and_sensitivity(change):
    value = run20_tree()
    pid = value["nodes"][0]["pid"]
    if change == "disabled":
        value["nodes"][29]["states"]["sensitive"] = False
    elif change == "wrong_process":
        value["nodes"][29]["pid"] += 1
    elif change == "duplicate":
        extra = copy.deepcopy(value["nodes"][29]); extra["id"] = 300; value["nodes"].append(extra)
    else:
        value["nodes"][1]["states"]["active"] = False
    with pytest.raises(ValueError):
        UI.keyboard_target(value, "Welcome to Harbor Canary", "Install Harbor Canary", ("list item",), pid)


def test_keyboard_hidden_matching_field_never_receives_secret(monkeypatch):
    value = run20_tree()
    pid = value["nodes"][0]["pid"]
    for node in value["nodes"]:
        node["states"]["focused"] = node["id"] == 81
    calls = []
    driver = UI.KeyboardUI(SimpleNamespace(key=lambda *a: calls.append(a), type=lambda *a: calls.append(a)),
                           None, lambda: copy.deepcopy(value), None, app_pid=pid)
    monkeypatch.setattr(driver, "page", lambda expected=None: ("Create User", copy.deepcopy(value)))
    monkeypatch.setattr(UI.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="cycled"):
        driver.field("Password", "synthetic-secret", secret=True)
    assert calls == [("tab",)]


def test_keyboard_real_focus_before_input_and_no_pointer(monkeypatch):
    initial = run20_tree()
    pid = initial["nodes"][0]["pid"]
    fresh = copy.deepcopy(initial)
    for node in fresh["nodes"]:
        node["states"]["focused"] = node["id"] == 134
    calls = []
    driver = UI.KeyboardUI(SimpleNamespace(key=lambda *a: calls.append(a), type=lambda *a: calls.append(a)),
                           None, lambda: copy.deepcopy(fresh), None, app_pid=pid)
    pages = iter([("Create User", initial), ("Create User", fresh)])
    monkeypatch.setattr(driver, "page", lambda expected=None: next(pages))
    monkeypatch.setattr(UI.time, "sleep", lambda _: None)
    assert driver.field("Password", "synthetic-secret", secret=True)["focused"]
    assert calls == [("tab",), ("ctrl", "a"), ("synthetic-secret",)]


def test_install_never_traverses_after_final_disk_guard(monkeypatch):
    value = run20_tree()
    pid = value["nodes"][0]["pid"]
    calls = []
    driver = UI.KeyboardUI(SimpleNamespace(key=lambda *a: calls.append(a)), None, None, None, app_pid=pid)
    monkeypatch.setattr(driver, "page", lambda expected=None: ("Confirm installation", copy.deepcopy(value)))
    with pytest.raises(ValueError, match="final disk guard"):
        driver.click("Install")
    assert calls == []
    for node in value["nodes"]:
        node["states"]["focused"] = node["id"] == 172
    assert driver.click("Install")["focused"]
    assert calls == [("ret",)]


def test_header_next_excludes_hidden_per_page_buttons():
    value = run20_tree()
    pid = value["nodes"][0]["pid"]
    for ident, parent in ((300, 241), (301, 92)):
        button = node(ident, parent, "button", "Next", [0, 0, 80, 40], enabled=False)
        button.update(pid=pid, role_id=43)
        value["nodes"].append(button)
    selected, _ = UI.keyboard_target(value, "Create User", "Next", ("push button",), pid, header=True)
    assert selected["id"] == 300


def test_entire_keyboard_sequence_handles_disabled_header_focus(monkeypatch):
    """Run21 reaches Create User with active frame but zero focused widgets.

    Extend the approved native tree with the source-defined header Next button.
    This exercises every remaining input phase without a guest or disk writes.
    """
    value = run20_tree()
    pid = value["nodes"][0]["pid"]
    next_button = node(300, 241, "button", "Next", [0, 0, 80, 40], enabled=False)
    next_button.update(pid=pid, role_id=43)
    value["nodes"].append(next_button)
    phase = ["Welcome to Harbor Canary"]
    typed = set()
    events = []
    disk_guard = [False]

    def focused():
        return next((n["id"] for n in value["nodes"] if n["states"].get("focused")), None)

    def focus(ident):
        for n in value["nodes"]:
            n["states"]["focused"] = n["id"] == ident

    def key(*keys):
        events.append(keys)
        current = focused()
        if keys == ("tab",):
            order = {
                "Welcome to Harbor Canary": [29],
                "Disk Encryption": [75, 300],
                "Create User": [122, 128, 134, 147] + ([300] if len(typed) == 4 else []),
                "Confirm installation": [172],
            }[phase[0]]
            focus(order[(order.index(current) + 1) % len(order)] if current in order else order[0])
        elif keys == ("spc",):
            assert current == 75
            value["nodes"][75]["states"]["checked"] = False
        elif keys == ("ret",):
            if current == 29:
                phase[0] = "Disk Encryption"
            elif current == 300:
                phase[0] = "Create User" if phase[0] == "Disk Encryption" else "Confirm installation"
            else:
                assert current == 172 and disk_guard[0]
                return
            next_button["states"]["sensitive"] = phase[0] != "Create User"
            focus(None)  # The new empty form disables the formerly focused Next.
        else:
            assert keys == ("ctrl", "a") and current in (122, 128, 134, 147)

    def type_text(text):
        assert focused() in (122, 128, 134, 147)
        typed.add(focused())
        next_button["states"]["sensitive"] = len(typed) == 4
        events.append(("typed",))  # Never save supplied field text.

    driver = UI.KeyboardUI(SimpleNamespace(key=key, type=type_text), None,
                           lambda: copy.deepcopy(value), None, app_pid=pid)
    monkeypatch.setattr(driver, "capture", lambda label: (Path("fixture.png"), SIZE,
                                                         words(phase[0]), copy.deepcopy(value)))
    monkeypatch.setattr(UI.time, "sleep", lambda _: None)
    driver.start_welcome()
    driver.toggle_off("Encrypt this disk")
    driver.click("Next")
    for name, secret in (("Name", False), ("Username", False), ("Password", True), ("Confirm Password", True)):
        driver.field(name, "synthetic-test-value", secret=secret)
    driver.click("Next")
    driver.focus("Install", ("push button",), heading="Confirm installation")
    disk_guard[0] = True
    driver.click("Install")
    assert typed == {122, 128, 134, 147}
    assert [event["page"] for event in driver.navigation_events] == ["Disk Encryption", "Create User", "Confirm installation"]
    assert events.count(("ret",)) == 4


@pytest.mark.parametrize("case", ["no_transition", "same_page", "inactive", "ambiguous_focus", "no_focus_after_tab", "changed_page", "changed_app_after_tab", "ambiguous_after_tab", "deadline", "unapproved_transition"])
def test_focus_bootstrap_is_narrow_nonactivating_and_bounded(monkeypatch, case):
    value = run20_tree()
    pid = value["nodes"][0]["pid"]
    for n in value["nodes"]:
        n["states"]["focused"] = False
    events = []
    def key(*keys):
        events.append(keys)
        if case == "changed_app_after_tab":
            value["nodes"][1]["states"]["active"] = False
        if case == "ambiguous_after_tab":
            for ident in (122, 128):
                value["nodes"][ident]["states"]["focused"] = True
    driver = UI.KeyboardUI(SimpleNamespace(key=key, type=lambda *a: events.append(("typed",))),
                           None, lambda: copy.deepcopy(value), None, app_pid=pid)
    if case != "no_transition":
        driver.focus_transition = {"from": "Create User" if case == "same_page" else "Disk Encryption",
                                   "action": "unrelated" if case == "unapproved_transition" else "Next"}
    if case == "inactive":
        value["nodes"][1]["states"]["active"] = False
    if case == "ambiguous_focus":
        for ident in (122, 128):
            value["nodes"][ident]["states"]["focused"] = True
    count = [0]
    clock = [0]
    monkeypatch.setattr(UI.time, "monotonic", lambda: clock[0])
    def capture(label):
        count[0] += 1
        if case == "deadline" and count[0] > 1:
            clock[0] = 100
        heading = "Confirm installation" if case == "changed_page" and count[0] > 1 else "Create User"
        return Path("fixture.png"), SIZE, words(heading), copy.deepcopy(value)
    monkeypatch.setattr(driver, "capture", capture)
    monkeypatch.setattr(UI.time, "sleep", lambda _: None)
    with pytest.raises(ValueError):
        driver.field("Password", "synthetic-test-value", secret=True)
    assert events == ([("tab",)] if case in {"no_focus_after_tab", "changed_app_after_tab", "ambiguous_after_tab"} else [])


def confirmation_tree(path="/dev/vdb"):
    return {"schema_version": 1, "nodes": [
        node(0, None, "application", "Installer", None),
        node(1, 0, "frame", "Installer", [0, 0, 900, 768], active=True),
        node(2, 1, "panel", "", [0, 0, 900, 700]),
        node(3, 2, "panel", "", [0, 0, 900, 700]),
        node(4, 3, "label", "Create User", [0, 0, 200, 30]),
        node(5, 2, "panel", "", [0, 0, 900, 700]),
        node(6, 5, "label", "Confirm installation", [0, 0, 200, 30]),
        node(7, 5, "list item", "", [0, 0, 576, 56]),
        node(8, 7, "label", "Disk", [0, 0, 100, 20]),
        node(9, 7, "label", f"{path} (64 GiB)", [0, 0, 150, 20]),
        node(10, 5, "list item", "", [0, 0, 576, 56]),
        node(11, 10, "label", f"Everything on {path} will be erased. This cannot be undone.",
             [0, 0, 576, 20]),
    ]}


@pytest.mark.parametrize("change", ["wrong_device", "similar_path", "duplicate_warning", "inactive",
                                   "wrong_process", "wrong_page", "unbound_disk", "wrong_size"])
def test_confirmation_disk_requires_exact_bound_selected_target(change):
    value = confirmation_tree()
    if change == "wrong_device":
        value = confirmation_tree("/dev/vda")
    elif change == "similar_path":
        value = confirmation_tree("/dev/vdb1")
    elif change == "duplicate_warning":
        value["nodes"].append(dict(value["nodes"][11], id=12))
    elif change == "inactive":
        value["nodes"][1]["states"]["active"] = False
    elif change == "wrong_process":
        value["nodes"][9]["pid"] += 1
    elif change == "wrong_page":
        value["nodes"][7]["parent"] = 3
    elif change == "unbound_disk":
        value["nodes"][8]["parent"] = 5
    elif change == "wrong_size":
        value["nodes"][9]["name"] = "/dev/vdb (32 GiB)"
    with pytest.raises(ValueError):
        UI.confirmation_disk(value, PID, "/dev/vdb")


@pytest.mark.parametrize("change", ["valid", "wrong_ocr", "suffix", "confusable", "duplicate",
                                   "low_confidence", "stale_app", "wrong_heading"])
def test_confirmation_warning_ocr_never_sends_input(tmp_path, change):
    from PIL import Image

    frame = tmp_path / "frame.png"
    Image.new("RGB", SIZE, "white").save(frame)
    value = confirmation_tree()
    warning = UI.confirmation_disk(value, PID, "/dev/vdb")
    rows = words(warning)
    if change == "wrong_ocr":
        rows[2]["text"] = "/dev/vda"
    elif change == "suffix":
        rows[2]["text"] = "/dev/vdb1"
    elif change == "confusable":
        rows[2]["text"] = "/dev/vdß"
    elif change == "duplicate":
        rows += words(warning, y=500, line=2)
    elif change == "low_confidence":
        rows[2]["conf"] = "79"
    after = copy.deepcopy(value)
    if change == "stale_app":
        after["nodes"][1]["states"]["active"] = False
    events = []

    def read_words(path, **kwargs):
        assert kwargs == {"psm": 11, "confidence": 80}
        assert Image.open(path).size == (SIZE[0] * 2, SIZE[1] * 2)
        return [r for r in rows if float(r["conf"]) >= kwargs["confidence"]]

    instance = UI.KeyboardUI(SimpleNamespace(key=events.append), None, lambda: after,
                             read_words, app_pid=PID, private=tmp_path)
    heading = "Create User" if change == "wrong_heading" else "Confirm installation"
    instance.capture = lambda label: (frame, SIZE, words(heading), value)
    if change == "valid":
        result = instance.confirmation_target("/dev/vdb")
        assert result["warning_visible"] and result["disk_row_bound"]
    else:
        with pytest.raises(ValueError):
            instance.confirmation_target("/dev/vdb")
    assert events == []


def polkit_tree():
    return {"schema_version": 1, "nodes": [
        node(0, None, "application", "Shell", None),
        node(1, 0, "dialog", "", [410, 163, 459, 473]),
        node(2, 1, "label", "Authentication Required", [434, 199, 411, 28]),
        node(3, 1, "label", "canary", [434, 398, 411, 25]),
        node(4, 1, "password text", "", [493, 459, 263, 21], focused=True),
    ]}


@pytest.mark.parametrize("change", ["wrong_user", "wrong_agent", "extra_password", "lost_focus",
                                   "wrong_dialog", "zero_bounds", "outside_frame", "duplicate_title"])
def test_polkit_rejects_unbound_or_unfocused_password(change):
    value = polkit_tree()
    if change == "wrong_user":
        value["nodes"][3]["name"] = "root"
    elif change == "wrong_agent":
        value["nodes"][4]["pid"] += 1
    elif change == "extra_password":
        value["nodes"].append(dict(value["nodes"][4], id=5))
    elif change == "lost_focus":
        value["nodes"][4]["states"]["focused"] = False
    elif change == "wrong_dialog":
        value["nodes"][2]["parent"] = 0
    elif change == "zero_bounds":
        value["nodes"][3]["bounds"] = [0, 0, 0, 0]
    elif change == "outside_frame":
        value["nodes"][3]["bounds"][0] = SIZE[0]
    elif change == "duplicate_title":
        value["nodes"].append(dict(value["nodes"][2], id=5))
    with pytest.raises(ValueError):
        UI.polkit_prompt(value, PID, SIZE)


@pytest.mark.parametrize("change", ["valid", "lost_focus", "moved", "changed_dialog", "wrong_user"])
def test_polkit_rechecks_exact_prompt_after_bound_ocr_before_typing(tmp_path, change):
    from PIL import Image

    frame = tmp_path / "prompt.png"
    Image.new("RGB", SIZE, "white").save(frame)
    value, after = polkit_tree(), polkit_tree()
    if change == "lost_focus":
        after["nodes"][4]["states"]["focused"] = False
    elif change == "moved":
        after["nodes"][4]["bounds"][0] += 1
    elif change == "changed_dialog":
        after["nodes"][1]["id"] = 10
        for n in after["nodes"][2:]:
            n["parent"] = 10
    elif change == "wrong_user":
        after["nodes"][3]["name"] = "root"
    events, reads = [], []
    instance = UI.KeyboardUI(SimpleNamespace(type=lambda s: events.append("typed"), key=events.append),
                             None, lambda: after, None, private=tmp_path)
    instance.capture = lambda label: (frame, SIZE, [], value)
    instance.label_point = lambda frame, node, rows, phrase, size: reads.append((node["id"], phrase))
    if change == "valid":
        assert instance.authentication_ready(PID)
        assert instance.authenticate("synthetictest", PID)["password_typed"]
        assert events == ["typed", "ret"]
        assert reads == [(2, "Authentication Required"), (3, "canary")] * 2
    else:
        with pytest.raises(ValueError):
            instance.authenticate("synthetictest", PID)
        assert events == []


def test_polkit_waits_only_for_missing_or_unfocused_prompt():
    empty = {"schema_version": 1, "nodes": [node(0, None, "application", "Shell", None)]}
    assert UI.polkit_prompt(empty, PID, SIZE, waiting=True) is None
    value = polkit_tree()
    value["nodes"][4]["states"]["focused"] = False
    assert UI.polkit_prompt(value, PID, SIZE, waiting=True) is None
    value["nodes"].append(dict(value["nodes"][4], id=5))
    with pytest.raises(ValueError):
        UI.polkit_prompt(value, PID, SIZE, waiting=True)


def test_polkit_supplemental_hint_is_not_an_identity_label():
    value = polkit_tree()
    value["nodes"][4]["unresolved_relations"] = {"described_by": 1}
    assert UI.polkit_prompt(value, PID, SIZE)[3]["id"] == 4
    for unresolved in ({"labelled_by": 1}, {"described_by": 2}, {"described_by": 1, "labelled_by": 1}):
        value["nodes"][4]["unresolved_relations"] = unresolved
        with pytest.raises(ValueError, match="unresolved identity"):
            UI.polkit_prompt(value, PID, SIZE)


def test_polkit_unexpected_password_identity_relation_is_rejected():
    value = polkit_tree()
    value["nodes"][4]["relations"] = {"labelled_by": [3]}
    with pytest.raises(ValueError, match="unresolved identity"):
        UI.polkit_prompt(value, PID, SIZE)
