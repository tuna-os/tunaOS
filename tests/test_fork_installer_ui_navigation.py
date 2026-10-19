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
        value["nodes"] *= 181
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
def test_snapshot_label_relations_accept_unhashable_gi_wrappers(monkeypatch, capsys, relation_case):
    import sys
    import types

    class Accessible:
        __hash__ = None

        def __init__(self, key, role, name, children=()):
            self.key, self.role, self.name, self.children = key, role, name, children

        def __eq__(self, other):
            return isinstance(other, Accessible) and self.key == other.key

        def get_process_id(self):
            return PID

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
        exec(UI.SNAPSHOT.replace("__PIDS__", repr([PID])), {})  # noqa: S102 - execute the owned read-only observer against fixture GI

    if relation_case == "duplicate":
        with pytest.raises(ValueError, match="unresolved target|duplicate accessibility"):
            observe()
        assert capsys.readouterr().out == ""
        return
    observe()
    value = json.loads(capsys.readouterr().out)
    assert value["nodes"][1]["relations"] == {"labelled_by": [2]}
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
