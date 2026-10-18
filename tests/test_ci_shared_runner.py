"""The Forgejo runner runs two jobs at once, in one root image store and one
/tmp, so a name two jobs can both write is a race.

On 2026-10-18 the two NVIDIA variants of one nightly build both rechunked to
localhost/hypervisor-nvidia:rechunked-44; the first to finish untagged it in
its cleanup, and the other's push, eight seconds later, found no image. With
the timing shifted the same overlap pushes one variant's image, signed, under
the other's tag. Every push also wrote /tmp/digest.txt, where a job could read
another's digest and copy it onto its own floating tag.
"""
import re
import unittest

from tests import REPO_ROOT

WORKFLOWS = sorted((REPO_ROOT / ".forgejo" / "workflows").glob("*.yml"))
HYPERVISOR = ("build-hypervisor.yml", "build-hypervisor-f44-quick.yml")
NAMING = "Name this job's local images"


def jobs(text):
    """{job name: its text}, for the jobs under `jobs:`."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([\w-]+):\n", body)[1:]
    return dict(zip(parts[::2], parts[1::2]))


def steps(job):
    return job.split("\n      - name: ")[1:]


class SharedRunner(unittest.TestCase):

    def test_no_workflow_writes_a_fixed_tmp_path(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                self.assertNotIn("/tmp/", path.read_text())

    def test_every_push_writes_its_digest_in_its_own_directory(self):
        pushes = 0
        for path in WORKFLOWS:
            for name, job in jobs(path.read_text()).items():
                for step in steps(job):
                    if "--digestfile" not in step:
                        continue
                    pushes += 1
                    with self.subTest(workflow=path.name, job=name,
                                      step=step.split("\n", 1)[0]):
                        self.assertIn("WORK=$(mktemp -d)", step)
                        for arg in re.findall(r"--digestfile (\S+)", step):
                            self.assertEqual(arg, '"$WORK/digest"')
        self.assertGreaterEqual(pushes, 6)

    def test_hypervisor_jobs_name_their_local_images_per_run_and_entry(self):
        named = 0
        for workflow in HYPERVISOR:
            text = (REPO_ROOT / ".forgejo" / "workflows" / workflow).read_text()
            for name, job in jobs(text).items():
                if "localhost/" not in job:
                    continue
                with self.subTest(workflow=workflow, job=name):
                    first = steps(job)[0]
                    # First, so the always() cleanup has the names even when
                    # an early step failed.
                    self.assertTrue(first.startswith(NAMING), first[:60])
                    self.assertEqual(job.count("localhost/"),
                                     first.count("localhost/"))
                    ref = re.search(r'ref="(localhost/[^"]+)"', first).group(1)
                    self.assertIn("${GITHUB_RUN_ID}", ref)
                    self.assertIn("${VERSION}", ref)
                    if "matrix.variant" in job:
                        self.assertIn("${NAME}", ref)
                        self.assertIn("NAME: ${{ matrix.variant.name }}",
                                      first)
                    named += 1
        self.assertEqual(named, 4)


if __name__ == "__main__":
    unittest.main()
