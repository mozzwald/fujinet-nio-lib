"""Launcher contract tests; no Docker, SDK acquisition or license acceptance."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def launch(self, toolchain, *args, **env):
        return subprocess.run(['bash', str(ROOT / 'scripts/palmos-build.sh'), *args],
                              cwd=ROOT, capture_output=True, text=True,
                              env=dict(os.environ, PALMOS_BUILDER='container',
                                       PALMDEV_TOOLCHAIN=str(toolchain), **env))

    def test_missing_checkout_fails_without_installing(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'not installed'
            p = self.launch(missing, 'make', PALMOS_SDK_VERSION='3.1')
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('setup.sh', p.stderr)
            self.assertFalse(missing.exists())

    def test_sdk_workspace_and_command_arguments_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            toolchain = Path(directory)
            wrapper = toolchain / 'palm-build'
            wrapper.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            wrapper.chmod(0o755)
            p = self.launch(toolchain, 'make', 'value=two words', 'literal=$HOME',
                            PALMOS_SDK_VERSION='3.5', NIO_WORKSPACE=str(ROOT.parent))
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout), ['--sdk', '3.5', '--workspace', str(ROOT.parent),
                             '--project', str(ROOT), '--', 'make', 'value=two words', 'literal=$HOME'])
            p = self.launch(toolchain, 'make', PALMOS_SDK_VERSION='9')
            self.assertNotEqual(p.returncode, 0)


class ConservativeBuildTests(unittest.TestCase):
    def test_payload_intervals_are_checked_and_forwarded_without_enabling_bursts(self):
        for value in ('0', '8', '16', '32', '64', '1', '7', '128', '-1', '32 64'):
            with self.subTest(value=value):
                p = subprocess.run(['make', '-n', '-f', 'makefiles/palmos-shared.mk',
                                    'PALMOS_CS1_PAYLOAD_WORDS=' + value],
                                   cwd=ROOT, capture_output=True, text=True)
                if value in ('0','8','16','32','64'):
                    self.assertEqual(p.returncode, 0, p.stderr)
                    self.assertIn('-DNL_CS1_PAYLOAD_WORDS=' + value, p.stdout)
                else:
                    self.assertNotEqual(p.returncode, 0)
                    self.assertIn('PALMOS_CS1_PAYLOAD_WORDS must be', p.stderr)
        # GNU make executes recursive $(MAKE) recipes even under -n. Stub the
        # explicit toolchain boundary so this contract test never starts Docker.
        with tempfile.TemporaryDirectory() as directory:
            wrapper = Path(directory) / 'palm-build'
            wrapper.write_text('#!/usr/bin/env python3\nimport sys\nprint(sys.argv[1:])\n')
            wrapper.chmod(0o755)
            p = subprocess.run(['make', '-n', 'palmos-shared', 'PALMOS_CS1_PAYLOAD_WORDS=16'],
                               cwd=ROOT, capture_output=True, text=True,
                               env=dict(os.environ, PALMOS_BUILDER='container',
                                        PALMDEV_TOOLCHAIN=directory))
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn('PALMOS_CS1_PAYLOAD_WORDS=16', p.stdout)

    def test_experimental_settings_are_rejected_before_building(self):
        for words, write in (('8', '0'), ('16', '0'), ('32', '1'), ('0', '1')):
            with self.subTest(words=words, write=write):
                p = subprocess.run(
                    ['make', '-n', '-f', 'makefiles/palmos-shared.mk',
                     'PALMOS_CS1_BURST_WORDS=' + words,
                     'PALMOS_CS1_BURST_WRITE=' + write],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn('CS1 bursts are unsupported', p.stderr)


if __name__ == '__main__':
    unittest.main()
