"""A step that resolves an image through verified-ref.sh fails when it does.

The script exits non-zero when the image is missing or not signed by
cosign.pub, and the step hands the build the digest it printed. Written as
`echo "ref=$(bash verified-ref.sh ...)"`, the step went on with an empty ref:
the exit status of that line is echo's. For the negativo17 variant an empty
ref drops the build argument, and the build fetched the driver from
negativo17.org instead, unannounced. These run each such step's own script
against a stand-in for verified-ref.sh that fails.
"""
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests import REPO_ROOT
from tests.test_ci_shared_runner import WORKFLOWS, jobs, steps

SCRIPT = ".forgejo/scripts/verified-ref.sh"


def resolve_steps():
    """{(workflow, job, step name): run script}, for every Resolve step
    calling it. publish-negativo-rpms calls it too, as a bare command after
    its push, where its failure already fails the step."""
    found = {}
    for path in WORKFLOWS:
        for name, job in jobs(path.read_text()).items():
            for step in steps(job):
                if step.startswith("Resolve ") and SCRIPT in step:
                    run = textwrap.dedent(step.split("        run: |\n", 1)[1])
                    found[(path.name, name, step.split("\n", 1)[0])] = run
    return found


class VerifiedRef(unittest.TestCase):

    def test_every_resolve_step_fails_when_the_image_does_not_verify(self):
        found = resolve_steps()
        # Both hypervisor workflows: homelab packages, negativo17 packages.
        self.assertEqual(len(found), 4)
        for where, run in found.items():
            with self.subTest(where=where), tempfile.TemporaryDirectory() as work:
                stub = Path(work) / SCRIPT
                stub.parent.mkdir(parents=True)
                stub.write_text("exit 1\n")
                output = Path(work) / "output"
                env = dict(os.environ, REGISTRY="registry.local", VERSION="44",
                           GITHUB_OUTPUT=str(output))
                done = subprocess.run(["bash", "-e", "-c", run], cwd=work, env=env,
                                      capture_output=True, text=True)
                self.assertNotEqual(done.returncode, 0)


if __name__ == "__main__":
    unittest.main()
