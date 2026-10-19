#!/usr/bin/env python3
"""The image installs workloadctl and moatery, which it requires, from their
Copr projects with each signature checked, and caches both for VM seed ISOs."""
import re
import unittest

from tests import REPO_ROOT

CONTAINERFILE = REPO_ROOT / "hypervisor.Containerfile"
COPR = REPO_ROOT / "copr"
PROJECTS = ("workloadctl", "moatery")


class TestTheImageInstallsThePinnedRPMs(unittest.TestCase):

    def test_each_is_fetched_at_its_pin_installed_and_cached(self):
        """Each fetch stage is named as its project, fetches it at the
        version its ARG pins, and the image installs the RPM and caches it
        where workload-ensure-user reads it for a VM's seed ISO."""
        containerfile = CONTAINERFILE.read_text()
        install = re.search(r"(?m)^RUN .*\n(?:.*\\\n)*.*dnf install -y (.*) &&",
                            containerfile)
        self.assertIsNotNone(install)
        for project in PROJECTS:
            with self.subTest(project=project):
                arg = f"{project.upper()}_VERSION"
                self.assertRegex(containerfile, rf"(?m)^ARG {arg}=\d+(\.\d+)+$")
                self.assertRegex(containerfile,
                                 rf"(?m)^FROM \S+ AS {project}$")
                self.assertIn(f'/tmp/copr/fetch {project} "${{{arg}}}" '
                              f"/{project}.rpm", containerfile)
                self.assertEqual(containerfile.count(
                    f"COPY --from={project} /{project}.rpm "
                    f"/tmp/{project}.rpm"), 1)
                self.assertIn(f"/tmp/{project}.rpm", install.group(1))
                self.assertIn(f"/tmp/{project}.rpm "
                              f"/usr/share/workloadctl/{project}.rpm",
                              containerfile)

    def test_the_fetch_refuses_what_the_project_key_did_not_sign(self):
        """dnf download checks no signature, so the fetch's rpmkeys is the
        only check between Copr and the image. It reads the project's key
        committed beside it, and _pkgverify_level makes it refuse an
        unsigned package, which `rpmkeys -K` alone passes on its digests
        (both seen 2026-10-06: a package signed by another key and an
        unsigned one, each served from a local repository, were refused)."""
        fetch = (COPR / "fetch").read_text()
        self.assertIn('key=$(dirname "$(realpath "$0")")/$project.gpg', fetch)
        self.assertIn("--define '_pkgverify_level signature' -K", fetch)
        self.assertIn('install -m 0644 "$1" "$dest"', fetch)
        # A package the project builds beside its namesake is checked
        # against the same key.
        self.assertIn('package=${4:-$project}', fetch)
        self.assertIn('--repo="$project" "$package-$version"', fetch)

    def test_every_project_fetched_has_its_key(self):
        """A project with no key fails the fetch, and with it every image
        build that does not replace the stage."""
        for project in PROJECTS:
            with self.subTest(project=project):
                self.assertTrue((COPR / f"{project}.gpg").read_text()
                                .startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----"))

    def test_a_local_build_stands_in_for_each_copr_stage(self):
        """build-base-local's WORKLOADCTL_LOCAL and MOATERY_LOCAL hand podman
        a build context named as the fetch stage, holding the RPM where the
        stage puts it. podman then takes the context for every --from= of
        that name and does not build the stage (seen with podman 5.8.7,
        2026-10-06); a context of any other name is ignored and the image
        quietly gets the Copr release."""
        justfile = (REPO_ROOT / "justfile").read_text()
        for project in PROJECTS:
            with self.subTest(project=project):
                self.assertIn(f'{project.upper()}_LOCAL', justfile)
                self.assertIn(f'--build-context "{project}=$context"',
                              justfile)
                self.assertIn(f'"$context/{project}.rpm"', justfile)


if __name__ == "__main__":
    unittest.main()
