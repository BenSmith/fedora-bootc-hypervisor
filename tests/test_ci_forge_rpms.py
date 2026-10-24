"""The Forgejo hypervisor builds install main's workloadctl and moatery.

Each repository's Forgejo CI publishes main's RPMs to the forge's RPM
registry. Both Forgejo hypervisor workflows fetch the newest with
forge-rpms.sh, and hand them to the build as contexts named as hypervisor.Containerfile's fetch
stages: a context of any other name is ignored, and the image quietly gets
the Copr release. The runtime gate checks workloadctl out at the commit the
image's label names. The registry signs its metadata, not its packages, so
dnf checks the metadata against the registry's key and each package against
the metadata's checksum. These run the steps' own scripts, and
forge-rpms.sh against stand-ins for dnf and rpm.
"""
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests import REPO_ROOT
from tests.test_ci_shared_runner import HYPERVISOR, jobs, steps

WORKFLOWS = REPO_ROOT / ".forgejo" / "workflows"
SCRIPT = REPO_ROOT / ".forgejo" / "scripts" / "forge-rpms.sh"
FETCH = "Fetch forge RPMs"
BUILD = "Build base hypervisor"
LABEL = "workloadctl.commit"

DNF = """#!/bin/bash
[ -z "$STUB_REFUSE" ] || exit 1
case "$1" in
  repoquery) [ -z "$STUB_VR" ] || echo "$STUB_VR" ;;
  download)
    for a; do case "$a" in --destdir=*) d=${a#--destdir=} ;; esac; done
    mkdir -p "$d"
    for n in workloadctl-1.0-1 workloadctl-vm-1.0-1 moatery-2.0-1; do
      echo "$n" > "$d/$n.noarch.rpm"
    done ;;
esac
"""
RPM = """#!/bin/bash
printf '%s' "$STUB_VCS"
"""


def run_script(step):
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def base_steps(workflow):
    job = jobs((WORKFLOWS / workflow).read_text())["base"]
    return {step.split("\n", 1)[0]: step for step in steps(job)}


class ForgeRpms(unittest.TestCase):

    def setUp(self):
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.work)])
        self.bin = self.work / "bin"
        self.bin.mkdir()
        for name, text in (("dnf", DNF), ("rpm", RPM)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)

    def env(self, **extra):
        return {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
                "STUB_VR": "1.0-1", "STUB_VCS": "(none)", **extra}

    def fetch(self, **extra):
        dest = self.work / "dest"
        done = subprocess.run(["bash", str(SCRIPT), "https://forge.example/rpm",
                               str(dest)], env=self.env(**extra),
                              capture_output=True, text=True)
        return done, dest

    def test_it_lays_out_what_the_fetch_stages_leave(self):
        done, dest = self.fetch()
        self.assertEqual(done.returncode, 0, done.stderr)
        containerfile = (REPO_ROOT / "hypervisor.Containerfile").read_text()
        for stage, rpm, built in (
                ("workloadctl", "workloadctl", "workloadctl-1.0-1"),
                ("workloadctl", "workloadctl-vm", "workloadctl-vm-1.0-1"),
                ("moatery", "moatery", "moatery-2.0-1")):
            with self.subTest(rpm=rpm):
                self.assertIn(f"COPY --from={stage} /{rpm}.rpm ", containerfile)
                self.assertEqual((dest / stage / f"{rpm}.rpm").read_text(),
                                 built + "\n")

    def test_it_prints_the_commit_the_workloadctl_rpm_names(self):
        done, _ = self.fetch(STUB_VCS="0123abc")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "0123abc")
        done, _ = self.fetch()
        self.assertEqual(done.stdout, "")

    def test_metadata_the_registry_key_did_not_sign_is_refused(self):
        """The packages are unsigned: gpgcheck would refuse every one, and
        without repo_gpgcheck nothing is checked at all."""
        text = SCRIPT.read_text()
        for opt in ("--setopt=forge.repo_gpgcheck=1",
                    "--setopt=forge.gpgcheck=0",
                    '--setopt=forge.gpgkey="file://$key"'):
            self.assertIn(opt, text)
        self.assertIn('/../rpm-registry.gpg")', text)
        self.assertTrue((REPO_ROOT / ".forgejo" / "rpm-registry.gpg").read_text()
                        .startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----"))
        done, dest = self.fetch(STUB_REFUSE="1")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(list(dest.rglob("*.rpm")), [])

    def test_a_registry_without_workloadctl_is_refused(self):
        done, _ = self.fetch(STUB_VR="")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no workloadctl", done.stderr)

    def test_an_unreachable_registry_is_an_error_not_an_empty_one(self):
        """dnf skips a repository it cannot load and reports what the others
        hold: here, nothing, the same as an empty registry."""
        self.assertIn("--setopt=forge.skip_if_unavailable=0", SCRIPT.read_text())

    def test_workloadctl_vm_is_fetched_at_workloadctls_version(self):
        self.assertIn('"workloadctl-$vr" "workloadctl-vm-$vr"', SCRIPT.read_text())

    def test_both_workflows_fetch_them_unless_dispatched_for_copr(self):
        for workflow in HYPERVISOR:
            with self.subTest(workflow=workflow):
                named = base_steps(workflow)
                names = list(named)
                self.assertLess(names.index(FETCH), names.index(BUILD))
                self.assertIn("        if: inputs.rpms != 'copr'\n", named[FETCH])
                text = (WORKFLOWS / workflow).read_text()
                self.assertRegex(text, r"rpms:\n(?:        .*\n)*?"
                                       r"        default: 'forge'\n")

    def test_a_fetch_that_fails_fails_the_build(self):
        for workflow in HYPERVISOR:
            with self.subTest(workflow=workflow):
                stub = self.work / workflow / ".forgejo" / "scripts" / SCRIPT.name
                stub.parent.mkdir(parents=True)
                stub.write_text("exit 1\n")
                output = self.work / workflow / "output"
                done = subprocess.run(
                    ["bash", "-e", "-c", run_script(base_steps(workflow)[FETCH])],
                    cwd=self.work / workflow, capture_output=True, text=True,
                    env=dict(os.environ, GITHUB_OUTPUT=str(output),
                             GITHUB_WORKSPACE=str(self.work / workflow)))
                self.assertNotEqual(done.returncode, 0)

    def build_args(self, workflow, **env):
        """What the build step hands `sudo`, given the fetch's outputs."""
        argv = self.work / "argv"
        sudo = self.bin / "sudo"
        sudo.write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" > {argv}\n')
        sudo.chmod(0o755)
        named = base_steps(workflow)
        self.assertIn("FORGE_RPMS: ${{ steps.forge.outputs.dir }}", named[BUILD])
        self.assertIn("WORKLOADCTL_COMMIT: ${{ steps.forge.outputs.commit }}",
                      named[BUILD])
        subprocess.run(["bash", "-e", "-c", run_script(named[BUILD])],
                       cwd=self.work, check=True, env=self.env(**env))
        return argv.read_text().splitlines()

    def test_the_build_is_given_them_as_the_fetch_stages(self):
        stages = re.findall(r"(?m)^FROM \S+ AS (\S+)$",
                            (REPO_ROOT / "hypervisor.Containerfile").read_text())
        for workflow in HYPERVISOR:
            with self.subTest(workflow=workflow):
                args = self.build_args(workflow, FORGE_RPMS="/f",
                                       WORKLOADCTL_COMMIT="0123abc")
                contexts = [args[i + 1] for i, a in enumerate(args)
                            if a == "--build-context"]
                self.assertEqual(contexts, ["workloadctl=/f/workloadctl",
                                            "moatery=/f/moatery"])
                for context in contexts:
                    self.assertIn(context.split("=")[0], stages)
                self.assertIn(f"{LABEL}=0123abc", args)

    def test_a_copr_build_is_given_neither(self):
        for workflow in HYPERVISOR:
            with self.subTest(workflow=workflow):
                args = self.build_args(workflow, FORGE_RPMS="",
                                       WORKLOADCTL_COMMIT="")
                self.assertNotIn("--build-context", args)
                self.assertNotIn("--label", args)

    def test_github_builds_fetch_none(self):
        for path in (REPO_ROOT / ".github" / "workflows").glob("*.yml"):
            with self.subTest(workflow=path.name):
                self.assertNotIn(SCRIPT.name, path.read_text())

    def test_the_gate_checks_out_the_commit_the_image_is_labelled_with(self):
        job = jobs((WORKFLOWS / "runtime-gate.yml").read_text())["runtime-gate"]
        named = {step.split("\n", 1)[0]: step for step in steps(job)}
        pin = named["workloadctl at the image's commit or pin"]
        self.assertIn("ref: ${{ steps.pin.outputs.ref }}",
                      named["Checkout workloadctl"])
        sudo = self.bin / "sudo"
        sudo.write_text('#!/bin/bash\n[ "$2" != image ] || echo "$STUB_LABEL"\n')
        sudo.chmod(0o755)
        output = self.work / "output"
        output.touch()
        done = subprocess.run(["bash", "-e", "-c", run_script(pin)],
                              cwd=self.work, capture_output=True, text=True,
                              env=self.env(GITHUB_OUTPUT=str(output),
                                           STUB_LABEL="0123abc"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(output.read_text(), "ref=0123abc\n")
        self.assertIn(f'index .Labels "{LABEL}"', pin)


if __name__ == "__main__":
    unittest.main()
