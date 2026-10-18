"""Every Forgejo hypervisor build carries the homelab root CA, or fails.

The base image takes the CA, and the registry.local mirror gated on it, only
when the build drops a .crt into ca-trust-inject/. A homelab host's /etc copies
of both are unmodified image defaults, so upgrading it to an image built
without them removes them at the reboot, and the host can then no longer
verify registry.local to pull the image that would put them back. These run
the step's own script.
"""
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests import REPO_ROOT
from tests.test_ci_shared_runner import HYPERVISOR, jobs, steps

STEP = "Inject homelab CA trust"


def inject_scripts():
    """{(workflow, job): the CA step's run script}, for every job that has one."""
    found = {}
    for workflow in HYPERVISOR:
        text = (REPO_ROOT / ".forgejo" / "workflows" / workflow).read_text()
        for name, job in jobs(text).items():
            for step in steps(job):
                if step.startswith(STEP + "\n"):
                    run = step.split("        run: |\n", 1)[1]
                    found[(workflow, name)] = textwrap.dedent(run)
    return found


class HomelabCa(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.scripts = inject_scripts()
        cls.tmp = Path(tempfile.mkdtemp())
        key, crt = cls.tmp / "ca.key", cls.tmp / "ca.crt"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "ec",
             "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
             "-subj", "/CN=Test Root CA", "-days", "1",
             "-keyout", str(key), "-out", str(crt)],
            check=True, capture_output=True)
        cls.pem = crt.read_text().strip()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def run_step(self, script, secret):
        """(returncode, the .crt it left) for one run, as the runner runs it."""
        work = Path(tempfile.mkdtemp(dir=self.tmp))
        (work / "ca-trust-inject").mkdir()
        env = dict(os.environ, HOMELAB_ROOT_CA=secret)
        done = subprocess.run(["bash", "-e", "-c", script], cwd=work, env=env,
                              capture_output=True, text=True)
        crts = list((work / "ca-trust-inject").glob("*.crt"))
        return done.returncode, crts

    def test_both_hypervisor_workflows_have_the_step_in_one_job(self):
        self.assertEqual(sorted(w for w, _ in self.scripts), sorted(HYPERVISOR))

    def test_an_unset_secret_fails_the_build(self):
        for where, script in self.scripts.items():
            with self.subTest(where=where):
                rc, crts = self.run_step(script, "")
                self.assertNotEqual(rc, 0)
                self.assertEqual(crts, [])

    def test_a_secret_that_is_not_a_certificate_fails_the_build(self):
        for where, script in self.scripts.items():
            with self.subTest(where=where):
                rc, _ = self.run_step(script, "not a certificate")
                self.assertNotEqual(rc, 0)

    def test_a_certificate_lands_in_the_build_context(self):
        for where, script in self.scripts.items():
            with self.subTest(where=where):
                rc, crts = self.run_step(script, self.pem)
                self.assertEqual(rc, 0)
                self.assertEqual([c.name for c in crts], ["homelab-root.crt"])
                self.assertEqual(crts[0].read_text().strip(), self.pem)


if __name__ == "__main__":
    unittest.main()
