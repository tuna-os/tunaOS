"""tuna-desktop#989: wheel membership must authorize password-required sudo.

Use sudo's actual parser and local membership matcher, with isolated account
files. No privileges, host accounts, or mocked policy evaluation are needed.
The image build separately runs visudo against the installed configuration.
"""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


POLICY = Path(__file__).resolve().parents[1] / "system_files/etc/sudoers.d/10-tunaos-wheel"


@pytest.fixture
def policy_for_user(tmp_path):
    converter = shutil.which("cvtsudoers")
    if converter is None:
        pytest.skip("sudo's native cvtsudoers is not installed")

    passwd = tmp_path / "passwd"
    groups = tmp_path / "group"
    passwd.write_text(
        "admin:x:1001:1001:Admin:/home/admin:/bin/bash\n"
        "regular:x:1002:1002:Regular:/home/regular:/bin/bash\n"
    )
    groups.write_text("wheel:x:10:admin\nadmin:x:1001:\nregular:x:1002:\n")

    def evaluate(user):
        result = subprocess.run(
            [converter, "-M", f"--passwd-file={passwd}", f"--group-file={groups}",
             "-f", "json", "-m", f"user={user}", str(POLICY)],
            check=True, capture_output=True, text=True,
        )
        # cvtsudoers emits no document when no policy matches the user.
        return json.loads(result.stdout) if result.stdout.strip() else {}

    return evaluate


def test_wheel_member_can_run_any_command_as_any_user_and_group(policy_for_user):
    policy = policy_for_user("admin")
    specs = policy["User_Specs"]
    assert len(specs) == 1
    assert specs[0]["Host_List"] == [{"hostname": "ALL"}]
    command_specs = specs[0]["Cmnd_Specs"]
    assert len(command_specs) == 1
    assert command_specs[0]["runasusers"] == [{"username": "ALL"}]
    assert command_specs[0]["runasgroups"] == [{"usergroup": "ALL"}]
    assert command_specs[0]["Commands"] == [{"command": "ALL"}]


def test_non_wheel_member_receives_no_sudo_authorization(policy_for_user):
    assert not policy_for_user("regular").get("User_Specs")


def test_wheel_grant_requires_authentication(policy_for_user):
    policy = policy_for_user("admin")
    # In sudo's JSON, NOPASSWD is represented as authenticate=false. Absent
    # that override, authentication is required by sudo's default policy.
    assert not policy.get("Defaults")
    specs = policy["User_Specs"]
    assert specs
    for spec in specs:
        for command_spec in spec["Cmnd_Specs"]:
            for option in command_spec.get("Options", []):
                assert option.get("authenticate", True)
