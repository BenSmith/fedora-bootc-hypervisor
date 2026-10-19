"""Every Forgejo hypervisor build installs the homelab's packages, or fails.

registry.local/homelab-rpms is an image of RPMs a homelab repository
publishes. hypervisor.Containerfile installs every RPM in the image it is
given (HOMELAB_RPMS), and none when it is given nothing, as on GitHub. A
host's packages come from its image, so upgrading it to one built without
them removes them. These run the resolve step's own script, against a
stand-in for verified-ref.sh.
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

STEP = "Resolve homelab packages"
BUILD = "Build base hypervisor"
REF = "registry.local/homelab-rpms@sha256:" + "0" * 64


def job_steps():
    """{(workflow, job): {step name: its text}}, for every job resolving it."""
    found = {}
    for workflow in HYPERVISOR:
        text = (REPO_ROOT / ".forgejo" / "workflows" / workflow).read_text()
        for name, job in jobs(text).items():
            named = {step.split("\n", 1)[0]: step for step in steps(job)}
            if STEP in named:
                found[(workflow, name)] = named
    return found


class HomelabRpms(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.jobs = job_steps()
        cls.tmp = Path(tempfile.mkdtemp())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def run_step(self, step, verified_ref):
        """(returncode, what it wrote to GITHUB_OUTPUT), with verified-ref.sh
        replaced by VERIFIED_REF."""
        work = Path(tempfile.mkdtemp(dir=self.tmp))
        script = work / ".forgejo" / "scripts" / "verified-ref.sh"
        script.parent.mkdir(parents=True)
        script.write_text(verified_ref)
        output = work / "output"
        output.touch()
        env = dict(os.environ, REGISTRY="registry.local", GITHUB_OUTPUT=str(output))
        run = textwrap.dedent(step.split("        run: |\n", 1)[1])
        done = subprocess.run(["bash", "-e", "-c", run], cwd=work, env=env,
                              capture_output=True, text=True)
        return done.returncode, output.read_text()

    def test_both_hypervisor_workflows_resolve_it_in_one_job(self):
        self.assertEqual(sorted(w for w, _ in self.jobs), sorted(HYPERVISOR))

    def test_an_image_that_does_not_verify_fails_the_build(self):
        for where, named in self.jobs.items():
            with self.subTest(where=where):
                rc, _ = self.run_step(named[STEP], "exit 1\n")
                self.assertNotEqual(rc, 0)

    def test_the_verified_digest_is_what_the_build_is_given(self):
        for where, named in self.jobs.items():
            with self.subTest(where=where):
                rc, output = self.run_step(named[STEP], f"echo {REF}\n")
                self.assertEqual(rc, 0)
                self.assertEqual(output, f"ref={REF}\n")
                self.assertIn("        id: homelab\n", named[STEP])
                self.assertIn("HOMELAB_RPMS: ${{ steps.homelab.outputs.ref }}",
                              named[BUILD])
                self.assertIn("--build-arg HOMELAB_RPMS=${HOMELAB_RPMS}",
                              named[BUILD])

    def test_github_builds_install_none(self):
        for path in (REPO_ROOT / ".github" / "workflows").glob("*.yml"):
            with self.subTest(workflow=path.name):
                self.assertNotIn("HOMELAB_RPMS", path.read_text())

    def test_they_install_after_workloadctl(self):
        text = (REPO_ROOT / "hypervisor.Containerfile").read_text()
        self.assertIn("ARG HOMELAB_RPMS=homelab-rpms-none\n", text)
        self.assertLess(text.index("dnf install -y /tmp/workloadctl.rpm"),
                        text.index("COPY --from=homelab-rpms / "))


if __name__ == "__main__":
    unittest.main()
