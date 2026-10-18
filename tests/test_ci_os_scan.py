"""Each OS image is checked for security updates it lacks, report only,
after its rechunk and before its push, so a fresh advisory cannot hold
the hosts' updates."""
import unittest

from tests import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".forgejo" / "workflows"
OS_SCAN = REPO_ROOT / ".forgejo" / "scripts" / "ci-os-scan.sh"


class OsImages(unittest.TestCase):

    JOBS = {"build-hypervisor.yml": 2, "build-hypervisor-f44-quick.yml": 2,
            "build-minimal-bootc.yml": 1}

    def test_every_rechunked_image_is_scanned_before_its_push(self):
        for name, jobs in self.JOBS.items():
            text = (WORKFLOWS / name).read_text()
            steps = text.split("\n      - name: ")
            names = [st.split("\n", 1)[0] for st in steps]
            scans = [i for i, n in enumerate(names)
                     if n.startswith("Check for missing security")]
            self.assertEqual(len(scans), jobs, name)
            for i in scans:
                self.assertTrue(names[i - 1].startswith("Rechunk"), name)
                self.assertTrue(names[i + 1].startswith("Tag and push"), name)
                ref = steps[i - 1].rsplit(":rechunked-", 1)[1].split('"')[0]
                self.assertIn(f"ci-os-scan.sh ", steps[i])
                self.assertIn(f":rechunked-{ref}", steps[i])
                gate = [ln for ln in steps[i - 1].splitlines()
                        if ln.strip().startswith("if:")]
                for ln in gate:
                    self.assertIn(ln, steps[i], name)

    def test_the_os_scan_never_fails_the_job(self):
        text = OS_SCAN.read_text()
        self.assertNotIn("exit 1", text)
        self.assertRegex(text, r"(?m)^exit 0$")

    def test_the_os_scan_asks_fedora_not_a_scanner(self):
        # Everything in an OS image is a Fedora package: grype's matches in
        # podman's vendored Go modules and the kernel's NVD entries were
        # 113 findings on 2026-10-17, none of which a rebuild could change.
        text = OS_SCAN.read_text()
        self.assertIn("dnf -q check-upgrade --security", text)
        self.assertNotIn("grype", text)

    def test_a_check_that_did_not_run_is_not_read_as_clean(self):
        # dnf exits 1 when it cannot reach the repos: only 0 is clean.
        text = OS_SCAN.read_text()
        self.assertRegex(text, r"\n  0\)\n\s*echo \"\$\{ref\}: no missing")
        self.assertRegex(text, r"\n  \*\)\n(?:[^\n]*\n)*?\s*echo \"::warning::could not check")


if __name__ == "__main__":
    unittest.main()
