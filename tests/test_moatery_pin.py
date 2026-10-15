#!/usr/bin/env python3
"""The image installs moatery, which workloadctl requires, from its Copr
repository with its signature checked, at a version workloadctl accepts."""
import re
import unittest

from tests import REPO_ROOT

CONTAINERFILE = REPO_ROOT / "hypervisor.Containerfile"
SPEC = REPO_ROOT / "workloadctl" / "rpm" / "workloadctl.spec"


class TestTheImageInstallsMoatery(unittest.TestCase):

    def test_the_pinned_moatery_satisfies_the_spec(self):
        """The hypervisor image fetches moatery's RPM at the version its
        build pins, installs it in the stage that runs this suite and in the
        image, and caches it for VM seed ISOs. The pinned version satisfies
        the spec's minimum, or the image's `dnf install` refuses
        workloadctl."""
        spec = SPEC.read_text()
        minimum = re.search(
            r"(?m)^Requires:\s+moatery >= (\S+)$", spec).group(1)
        containerfile = CONTAINERFILE.read_text()
        pinned = re.search(
            r"(?m)^ARG MOATERY_VERSION=(\S+)$", containerfile).group(1)

        def version(text):
            return tuple(int(part) for part in text.split("."))

        self.assertGreaterEqual(version(pinned), version(minimum))
        self.assertIn('/tmp/moatery-copr/fetch "${MOATERY_VERSION}" '
                      "/moatery.rpm", containerfile)
        self.assertEqual(containerfile.count(
            "COPY --from=moatery /moatery.rpm /tmp/moatery.rpm"), 2)
        self.assertIn("/usr/share/workloadctl/moatery.rpm", containerfile)

    def test_the_fetch_refuses_what_the_project_key_did_not_sign(self):
        """dnf download checks no signature, so the fetch's rpmkeys is the
        only check between Copr and the image. It reads the key committed
        beside it, and _pkgverify_level makes it refuse an unsigned package,
        which `rpmkeys -K` alone passes on its digests (both seen
        2026-10-06: a package signed by another key and an unsigned one,
        each served from a local repository, were refused)."""
        copr = REPO_ROOT / "moatery-copr"
        fetch = (copr / "fetch").read_text()
        self.assertTrue((copr / "pubkey.gpg").read_text().startswith(
            "-----BEGIN PGP PUBLIC KEY BLOCK-----"))
        self.assertIn('/pubkey.gpg', fetch)
        self.assertIn("--define '_pkgverify_level signature' -K", fetch)
        self.assertIn('install -m 0644 "$1" "$dest"', fetch)

    def test_a_local_moatery_stands_in_for_the_copr_stage(self):
        """build-base-local's MOATERY_LOCAL hands podman a build context
        named as the Containerfile's moatery stage, holding moatery.rpm
        where the stage puts /moatery.rpm. podman then takes the context
        for every --from=moatery and does not build the stage (seen with
        podman 5.8.7, 2026-10-06); a context of any other name is ignored
        and the image quietly gets the Copr release."""
        containerfile = CONTAINERFILE.read_text()
        justfile = (REPO_ROOT / "justfile").read_text()
        stage = re.search(
            r"(?m)^FROM \S+ AS (moatery)$", containerfile).group(1)
        self.assertIn(f'--build-context "{stage}=$context"', justfile)
        self.assertIn('"$context/moatery.rpm"', justfile)
        self.assertIn(f"COPY --from={stage} /moatery.rpm", containerfile)


if __name__ == "__main__":
    unittest.main()
