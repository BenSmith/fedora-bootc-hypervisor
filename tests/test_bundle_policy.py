#!/usr/bin/env python3
"""workloadctl's bundle trust policy ships only where the homelab CA ships.

`workloadctl bundle add <ref>` checks a pulled bundle against
/etc/workloadctl/bundle-policy.json, and a bundle carries files host root
runs. The policy trusts registry.local, an mDNS name that only the homelab
CA makes meaningful, so it is installed inside the ca-trust-inject
conditional, beside the registry mirror. Without it, workloadctl refuses
every OCI bundle, which is the public image's intended state.
"""
import json
import unittest

from tests import REPO_ROOT
from tests.test_registry_mirror import _run_blocks

CONTAINERFILE = REPO_ROOT / "hypervisor.Containerfile"
POLICY = REPO_ROOT / "workloadctl" / "bundle-policy.json"
TARGET = "/etc/workloadctl/bundle-policy.json"


class TestBundlePolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.containerfile = CONTAINERFILE.read_text()
        cls.policy = json.loads(POLICY.read_text())

    def test_never_copied_straight_into_etc(self):
        for line in self.containerfile.splitlines():
            if line.startswith("COPY ") and "bundle-policy.json" in line:
                self.assertNotIn("/etc/", line, line)

    def test_the_only_install_is_ca_gated(self):
        installing = [b for b in _run_blocks(self.containerfile) if TARGET in b]
        self.assertEqual(len(installing), 1, self.containerfile)
        self.assertIn("ca-trust-inject", installing[0])
        self.assertIn(".crt", installing[0])

    def test_rejects_by_default(self):
        self.assertEqual(self.policy["default"], [{"type": "reject"}])
        self.assertEqual(list(self.policy["transports"]), ["docker"])

    def test_trusts_only_signed_registry_local(self):
        self.assertEqual(self.policy["transports"]["docker"], {"registry.local": [{
            "type": "sigstoreSigned",
            "keyPath": "/etc/pki/containers/cosign.pub",
            "signedIdentity": {"type": "matchRepository"},
        }]})


if __name__ == "__main__":
    unittest.main()
