"""tunaOS#3812: slow runner downloads must not interrupt a dpkg transaction.

Falsification: behavioural — stalled acquisition exhausts its deadline without installation.
"""

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import time

import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('runner_apt', ROOT / 'scripts/setup-runner-podman.py')
apt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(apt)


def runner(tmp_path):
    (tmp_path / 'usr/lib').mkdir(parents=True)
    (tmp_path / 'usr/lib/os-release').write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
    sources = tmp_path / 'etc/apt/sources.list.d'
    sources.mkdir(parents=True)
    (sources / 'resolute.list').write_text('original source\n')
    cache = tmp_path / 'var/cache/apt/archives'
    cache.mkdir(parents=True)
    calls = []
    state = {'failures': 0, 'arch': 'amd64', 'metadata_error': False, 'install_error': False,
             'corrupt_download': False}
    payload = b'authenticated package fixture'
    digest = hashlib.sha256(payload).hexdigest()

    def fake(args, timeout=None):
        calls.append((args, timeout))
        if args[:2] == ['dpkg', '--print-architecture']:
            return state['arch']
        if args[0] == 'podman':
            return 'podman version 5.7.0'
        if args[0] == 'dpkg-query':
            return 'installed' if 'Status' in args[2] else '5.7.0'
        source_arg = next(x for x in args if x.startswith('Dir::Etc::sourceparts='))
        source_path = Path(source_arg.split('=', 1)[1])
        state['temporary_sources'] = source_path
        expected_mirror = ('https://archive.ubuntu.com/ubuntu' if state['arch'] == 'amd64' else 'https://ports.ubuntu.com/ubuntu-ports')
        assert (source_path / 'resolute.list').read_text() == f'deb {expected_mirror} resolute universe main\n'
        if 'update' in args:
            if state['metadata_error']:
                raise subprocess.CalledProcessError(100, args, 'signature verification failed')
            return ''
        assert all(selector in args for selector in ('crun/resolute', 'buildah/resolute', 'podman/resolute', 'skopeo/resolute'))
        assert '--allow-downgrades' in args
        if '--simulate' in args:
            return 'Inst podman [4.9.0] (5.7.0 Ubuntu:26.04/resolute [amd64])\n'
        if '--print-uris' in args:
            return f"'{expected_mirror}/pool/p.deb' p.deb {len(payload)} SHA256:{digest}\n"
        if '--download-only' in args:
            if state['failures']:
                state['failures'] -= 1
                raise subprocess.TimeoutExpired(args, timeout)
            (cache / 'p.deb').write_bytes(b'corrupt' if state['corrupt_download'] else payload)
            return ''
        assert '--no-download' in args
        assert timeout is None
        configs = list((tmp_path / 'etc/needrestart/conf.d').glob('99-tunaos-*.conf'))
        assert len(configs) == 1
        assert configs[0].read_text() == '$nrconf{restart} = "l";\n'
        assert (cache / 'p.deb').read_bytes() == payload
        if state['install_error']:
            raise subprocess.CalledProcessError(100, args)
        return ''

    return (tmp_path, calls, state), fake


class RunnerAptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runner, fake = runner(Path(self.temp.name))
        self.patcher = patch.object(apt, 'run', fake)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_official_archives(self):
        root, calls, state = self.runner
        for arch in ('amd64', 'arm64', 'armhf', 'ppc64el', 'riscv64', 's390x'):
            with self.subTest(arch=arch):
                state['arch'] = arch
                apt.upgrade(root)
                self.assertEqual((root / 'etc/apt/sources.list.d/resolute.list').read_text(), 'original source\n')
                self.assertFalse(state['temporary_sources'].exists())
                self.assertFalse(list((root / 'etc/needrestart/conf.d').glob('99-tunaos-*.conf')))
        self.assertEqual(sum('--no-download' in args for args, _ in calls), 6)

    def test_reject_unsupported_architecture(self):
        for arch in ('i386', 'https://evil.test', 'amd64\ntrusted=yes', ''):
            with self.subTest(arch=arch), self.assertRaises(ValueError):
                apt.archive(arch)

    def test_retry_is_download_only(self):
        root, calls, state = self.runner
        state['failures'] = 2
        apt.upgrade(root)
        downloads = [(args, timeout) for args, timeout in calls if '--download-only' in args and '--print-uris' not in args]
        self.assertEqual(len(downloads), 3)
        self.assertTrue(all(0 < timeout <= 200 for _, timeout in downloads))

    def test_exhausted_retries_never_install(self):
        root, calls, state = self.runner
        state['failures'] = 3
        with self.assertRaises(subprocess.TimeoutExpired):
            apt.upgrade(root)
        self.assertFalse(any('--no-download' in args for args, _ in calls))
        self.assertFalse(state['temporary_sources'].exists())

    def test_overall_deadline(self):
        root, calls, _ = self.runner
        with patch.object(apt.time, 'monotonic', side_effect=[0, 601, 602]):
            with self.assertRaises(TimeoutError):
                apt.upgrade(root)
        self.assertEqual(len(calls), 1)

    def test_final_cache_verification_must_finish_before_deadline(self):
        root, calls, state = self.runner
        clock = [0.0]
        original_verify = apt.verify_cache
        checks = [0]

        def slow_verify(cache, entries):
            valid = original_verify(cache, entries)
            checks[0] += 1
            if checks[0] == 2:
                clock[0] = 600.0  # Download succeeded; final hash check used the budget.
            return valid

        with patch.object(apt.time, 'monotonic', side_effect=lambda: clock[0]):
            with patch.object(apt, 'verify_cache', side_effect=slow_verify):
                with self.assertRaisesRegex(TimeoutError, 'deadline exhausted'):
                    apt.upgrade(root)
        self.assertEqual(checks[0], 2)
        self.assertFalse(any('--no-download' in args for args, _ in calls))
        self.assertFalse(state['temporary_sources'].exists())
        self.assertFalse((root / 'etc/needrestart/conf.d').exists())

    def test_installation_can_finish_after_acquisition_budget(self):
        root, calls, _ = self.runner
        clock = [0.0]
        original_run = apt.run

        def install_past_budget(args, timeout=None):
            if '--no-download' in args:
                self.assertIsNone(timeout)
                clock[0] = 601.0
            return original_run(args, timeout=timeout)

        with patch.object(apt.time, 'monotonic', side_effect=lambda: clock[0]):
            with patch.object(apt, 'run', side_effect=install_past_budget):
                apt.upgrade(root)
        self.assertEqual(sum('--no-download' in args for args, _ in calls), 1)
        self.assertFalse(list((root / 'etc/needrestart/conf.d').glob('99-tunaos-*.conf')))

    def test_signature_refusal_never_downloads(self):
        root, calls, state = self.runner
        state['metadata_error'] = True
        with self.assertRaises(subprocess.CalledProcessError):
            apt.upgrade(root)
        self.assertFalse(any('install' in args for args, _ in calls))

    def test_cache_miss_hit_corruption(self):
        root, _, _ = self.runner
        for content in (None, b'authenticated package fixture', b'corrupt'):
            with self.subTest(content=content):
                if content is not None:
                    (root / 'var/cache/apt/archives/p.deb').write_bytes(content)
                apt.upgrade(root)

    def test_repeated_corruption_never_installs(self):
        root, calls, state = self.runner
        state['corrupt_download'] = True
        with self.assertRaisesRegex(RuntimeError, 'cache verification'):
            apt.upgrade(root)
        self.assertFalse(any('--no-download' in args for args, _ in calls))

    def test_failed_install_cleans_only_owned_suppression(self):
        root, _, state = self.runner
        directory = root / 'etc/needrestart/conf.d'
        directory.mkdir(parents=True)
        prior = directory / '99-no-restarts.conf'
        prior.write_text('existing config')
        state['install_error'] = True
        with self.assertRaises(subprocess.CalledProcessError):
            apt.upgrade(root)
        self.assertEqual(list(directory.iterdir()), [prior])
        self.assertEqual(prior.read_text(), 'existing config')
        self.assertFalse(state['temporary_sources'].exists())

    def test_2604_verifies_without_apt(self):
        root, calls, _ = self.runner
        (root / 'usr/lib/os-release').write_text('ID=ubuntu\nVERSION_ID=26.04\n')
        apt.upgrade(root)
        self.assertEqual(calls, [(['podman', '--version'], None)])

    def test_real_slow_inert_process_is_bounded(self):
        self.patcher.stop()
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            apt.run(['python3', '-c', 'import time; time.sleep(10)'], timeout=0.05)
        self.assertLess(time.monotonic() - started, 2)

    def test_reject_unverifiable_manifest(self):
        for line in ("'https://archive.ubuntu.com/p' ../p 1 SHA256:abc", "'https://archive.ubuntu.com/p' p 1 MD5Sum:abc"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                apt.manifest(line)

    def test_official_uri_validation(self):
        for uri in ('http://archive.ubuntu.com/ubuntu', 'https://azure.archive.ubuntu.com/ubuntu',
                    'https://archive.ubuntu.com.evil/ubuntu', 'https://evil@archive.ubuntu.com/ubuntu',
                    'https://ports.ubuntu.com/ubuntu', 'https://archive.ubuntu.com/ubuntu?x=1'):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                apt.official_uri(uri)

    def test_termination_defers_until_cleanup(self):
        root, _, _ = self.runner
        directory = root / 'etc/needrestart/conf.d'
        with self.assertRaises(SystemExit):
            with apt.defer_termination(), apt.suppress_restarts(directory):
                apt.os.kill(apt.os.getpid(), apt.signal.SIGTERM)
                self.assertTrue(list(directory.glob('99-tunaos-*.conf')))
        self.assertFalse(list(directory.glob('99-tunaos-*.conf')))

    def test_workflow_boundary(self):
        workflow = (ROOT / '.github/workflows/reusable-build-image.yml').read_text()
        self.assertIn('setup-runner@209517dda44829f126e25da28f11245c34458ac3', workflow)
        self.assertIn('update-podman: "false"', workflow)
        self.assertIn('sudo python3 scripts/setup-runner-podman.py', workflow)
        self.assertIn('actions/cache/restore@55cc8345863c7cc4c66a329aec7e433d2d1c52a9', workflow)
        self.assertIn('actions/cache/save@55cc8345863c7cc4c66a329aec7e433d2d1c52a9', workflow)
        self.assertIn('apt-resolute-podman-${{ runner.os }}-${{ runner.arch }}-', workflow)
        self.assertLess(workflow.index('Restore runner apt cache'), workflow.index('Upgrade runner podman stack'))
        self.assertLess(workflow.index('Upgrade runner podman stack'), workflow.index('Save runner apt cache'))
        self.assertNotIn('native-overlay:', workflow)
        self.assertNotIn('podman-version', workflow)


if __name__ == '__main__':
    unittest.main()


def test_original_four_package_selectors_are_preserved():
    assert apt.SELECTORS == ('crun/resolute', 'buildah/resolute', 'podman/resolute', 'skopeo/resolute')
