#!/usr/bin/env python3
"""`ci-scan.py`: what fails an image build's scan.

    python3 .forgejo/scripts/test_ci_scan.py
"""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("ci_scan",
                                                  HERE / "ci-scan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = _load()


def match(vid, severity="Critical", state="fixed", versions=("1.2",)):
    return {"vulnerability": {"id": vid, "severity": severity,
                              "fix": {"state": state,
                                      "versions": list(versions)}},
            "artifact": {"name": "openssl", "version": "1.0"}}


class Judging(unittest.TestCase):

    def test_a_fixable_critical_fails(self):
        got = scan.failures({"matches": [match("CVE-1")]}, "img", [])
        self.assertEqual(got, [("CVE-1", "openssl", "1.0", "1.2")])

    def test_unfixed_or_lesser_ones_do_not(self):
        doc = {"matches": [match("CVE-1", state="not-fixed"),
                           match("CVE-2", severity="High"),
                           match("CVE-3", state="wont-fix")]}
        self.assertEqual(scan.failures(doc, "img", []), [])

    def test_the_allowlist_accepts_by_id_and_image(self):
        allow = scan.read_allowlist(
            "CVE-1 registry.local/workloads/jelly* upstream ships it\n"
            "# a comment\n\nCVE-2 * accepted everywhere\n")
        doc = {"matches": [match("CVE-1"), match("CVE-2"), match("CVE-3")]}
        got = scan.failures(doc, "registry.local/workloads/jellyfin:latest",
                            allow)
        self.assertEqual([g[0] for g in got], ["CVE-3"])
        got = scan.failures(doc, "registry.local/workloads/caddy:latest",
                            allow)
        self.assertEqual([g[0] for g in got], ["CVE-1", "CVE-3"])

    def test_an_allowlist_line_needs_a_reason(self):
        with self.assertRaises(ValueError):
            scan.read_allowlist("CVE-1 *\n")

    def test_a_scan_that_did_not_run_fails_not_passes(self):
        for doc in ({}, {"matches": None}, [], None, {"descriptor": {}}):
            with self.assertRaises(ValueError):
                scan.failures(doc, "img", [])


class Main(unittest.TestCase):

    def _run(self, doc, allow="", mode="judge"):
        with tempfile.TemporaryDirectory() as tmp:
            s, a = Path(tmp) / "s.json", Path(tmp) / "a.txt"
            if doc is not None:
                s.write_text(json.dumps(doc) if not isinstance(doc, str)
                             else doc)
            a.write_text(allow)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = scan.main(["ci-scan.py", mode, "img", str(s), str(a)])
            self.out = out.getvalue()
            return rc

    def test_clean_passes(self):
        self.assertEqual(self._run({"matches": [match("C", "High")]}), 0)

    def test_a_finding_fails(self):
        self.assertEqual(self._run({"matches": [match("C")]}), 1)

    def test_no_scan_file_or_garbage_fails(self):
        self.assertEqual(self._run(None), 1)
        self.assertEqual(self._run("not json"), 1)

    def test_report_warns_of_a_finding_and_passes(self):
        self.assertEqual(self._run({"matches": [match("C")]},
                                   mode="report"), 0)
        self.assertIn("::warning::img: C (critical)", self.out)
        self.assertNotIn("::error::", self.out)

    def test_report_warns_of_a_scan_that_did_not_run(self):
        self.assertEqual(self._run("not json", mode="report"), 0)
        self.assertIn("::warning::scan of img failed", self.out)

    def test_the_shipped_allowlist_parses(self):
        scan.read_allowlist((HERE.parent / "cve-allowlist.txt").read_text())



class Workflow(unittest.TestCase):
    """build-workload-images.yml runs the scan, before the push, weekly."""

    def setUp(self):
        self.text = (HERE.parent / "workflows" /
                     "build-workload-images.yml").read_text()

    def test_every_bundle_is_rebuilt_weekly(self):
        self.assertRegex(self.text, r"\n  schedule:\n    - cron: '[^']+'\n")

    def test_the_scan_judges_each_image_before_it_is_pushed(self):
        scan_at = self.text.index("ci-scan.py judge")
        self.assertLess(self.text.index("Build image"), scan_at)
        self.assertLess(scan_at, self.text.index("podman push"))
        self.assertIn(".forgejo/cve-allowlist.txt", self.text[scan_at:])

    def test_a_missing_scanner_or_a_failed_scan_stops_the_job(self):
        self.assertIn("command -v grype", self.text)
        self.assertRegex(self.text, r"if ! sudo (?:env [^\n]*?)?grype "
                                    r"(?:[^\n]*\\\n)*[^\n]*; then\n"
                                    r"[^\n]*\n\s*exit 1")

    def test_ci_runs_these_tests(self):
        self.assertIn("python3 .forgejo/scripts/test_ci_scan.py", self.text)

class OsImages(unittest.TestCase):
    """Each OS image is checked for security updates it lacks, report only,
    after its rechunk and before its push, so a fresh advisory cannot hold
    the hosts' updates."""

    JOBS = {"build-hypervisor.yml": 2, "build-hypervisor-f44-quick.yml": 2,
            "build-minimal-bootc.yml": 1}

    def test_every_rechunked_image_is_scanned_before_its_push(self):
        for name, jobs in self.JOBS.items():
            text = (HERE.parent / "workflows" / name).read_text()
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
        text = (HERE / "ci-os-scan.sh").read_text()
        self.assertNotIn("exit 1", text)
        self.assertRegex(text, r"(?m)^exit 0$")

    def test_the_os_scan_asks_fedora_not_a_scanner(self):
        # Everything in an OS image is a Fedora package: grype's matches in
        # podman's vendored Go modules and the kernel's NVD entries were
        # 113 findings on 2026-10-17, none of which a rebuild could change.
        text = (HERE / "ci-os-scan.sh").read_text()
        self.assertIn("dnf -q check-upgrade --security", text)
        self.assertNotIn("grype", text)

    def test_a_check_that_did_not_run_is_not_read_as_clean(self):
        # dnf exits 1 when it cannot reach the repos: only 0 is clean.
        text = (HERE / "ci-os-scan.sh").read_text()
        self.assertRegex(text, r"\n  0\)\n\s*echo \"\$\{ref\}: no missing")
        self.assertRegex(text, r"\n  \*\)\n(?:[^\n]*\n)*?\s*echo \"::warning::could not check")


class Runners(unittest.TestCase):
    """Each runner bundle installs the scanner the workflows call. The
    forge's runner had none on 2026-10-14, and the workload image build
    refuses to push an image it has not scanned."""

    BUNDLES = ("forgejo-runner",)
    # workloadctl ships the runner bundles; its RPM root, as
    # ci-workload-images.py reads it.
    SHIPPED = (Path(os.environ.get("WORKLOADCTL_ROOT", "/"))
               / "usr" / "share" / "workloadctl" / "workloads")

    def setUp(self):
        if not self.SHIPPED.is_dir():
            self.skipTest(f"no workloadctl bundles at {self.SHIPPED}: set "
                          f"WORKLOADCTL_ROOT")

    def _packages(self, bundle):
        text = (self.SHIPPED / bundle / "cloud-init" / "user-data").read_text()
        command = text.split("dnf install -y --skip-broken", 1)[1]
        command = command.split("\n\n", 1)[0].replace("\\\n", " ")
        return command.split()

    def test_every_runner_installs_grype(self):
        for bundle in self.BUNDLES:
            with self.subTest(bundle=bundle):
                self.assertIn("grype", self._packages(bundle))


if __name__ == "__main__":
    os.chdir(HERE)
    unittest.main()
