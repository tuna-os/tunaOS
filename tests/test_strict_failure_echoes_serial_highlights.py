"""A failed strict run echoes a bounded tail of telling serial lines.

The serial logs sit in an artifact that some readers of the job log cannot
download (guppy:gnome, iso-builder run 45709610455), so the EXIT-trap debug
block prints the lines that usually explain a desktop failure.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_source():
    text = (ROOT / 'scripts/iso-e2e.sh').read_text()
    match = re.search(r'^_echo_serial_highlights\(\) \{\n.*?^\}\n', text, re.S | re.M)
    assert match, '_echo_serial_highlights must exist in iso-e2e.sh'
    return match.group(0)


def _run(tmp_path, env=None):
    script = _function_source() + f'\n_echo_serial_highlights "{tmp_path}"\n'
    return subprocess.run(['bash', '-c', script], text=True, capture_output=True,
                          env={'PATH': '/usr/bin:/bin', **(env or {})})


def test_the_debug_block_calls_it():
    text = (ROOT / 'scripts/iso-e2e.sh').read_text()
    block = re.search(r'^_agent_debug_instructions\(\) \{\n.*?^\}\n', text, re.S | re.M).group(0)
    assert '_echo_serial_highlights "${OUTPUT_DIR:-}"' in block


def test_prints_matching_lines_without_control_bytes(tmp_path):
    (tmp_path / 'strict-plain-live-serial.log').write_bytes(
        b'boot ok\n\x1b[0mgdm.service: Failed with result exit-code\nnoise\nflatpak run: error: x\n')
    r = _run(tmp_path)
    assert r.returncode == 0
    lines = r.stdout.splitlines()
    assert lines[0].startswith('── serial highlights: strict-plain-live-serial.log')
    assert lines[1:] == ['[0mgdm.service: Failed with result exit-code', 'flatpak run: error: x']


def test_bounded_per_file_and_per_line(tmp_path):
    (tmp_path / 'serial.log').write_text(''.join(f'error {i} ' + 'x' * 400 + '\n' for i in range(50)))
    r = _run(tmp_path, {'SERIAL_HIGHLIGHT_LINES': '5'})
    body = r.stdout.splitlines()[1:]
    assert len(body) == 5 and body[0].startswith('error 45 ')
    assert all(len(line) <= 300 for line in body)


def test_missing_dir_prints_nothing(tmp_path):
    r = _run(tmp_path / 'absent')
    assert r.returncode == 0 and r.stdout == ''
