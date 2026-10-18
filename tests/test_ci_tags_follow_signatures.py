"""A floating tag moves only onto a digest whose signature has verified.

Hosts follow :latest, :44, :negativo17 and the like under a sigstoreSigned
policy. A job that copies a floating tag before verifying the signature over
the digest it pushed, and then fails to sign, leaves that tag on an image
every host refuses: they stop taking updates until a good build. Verifying
first leaves the tag on the last signed image instead.
"""
import re
import unittest

from tests import REPO_ROOT
from tests.test_ci_shared_runner import jobs

WORKFLOWS = sorted([
    *(REPO_ROOT / ".github" / "workflows").glob("*.yml"),
    *(REPO_ROOT / ".forgejo" / "workflows").glob("*.yml"),
])

# The pushed digest checked against cosign.pub: by cosign on GitHub, by a
# sigstoreSigned policy pull on Forgejo.
VERIFIES_DIGEST = re.compile(
    r'(?:cosign verify --key cosign\.pub|--signature-policy=\S+) '
    r'"\$\{IMAGE_BASE\}@\$\{DIGEST\}"')


class TagsFollowSignatures(unittest.TestCase):

    def test_every_tag_copy_comes_after_the_digest_verifies(self):
        publishing = 0
        for path in WORKFLOWS:
            for name, job in jobs(path.read_text()).items():
                first_copy = job.find("skopeo copy")
                if first_copy < 0:
                    continue
                publishing += 1
                with self.subTest(workflow=f"{path.parent.parent.name}/{path.name}",
                                  job=name):
                    verified = VERIFIES_DIGEST.search(job)
                    self.assertIsNotNone(verified, "never verifies the digest")
                    self.assertLess(verified.start(), first_copy)
        # GitHub: minimal, base, variant. Forgejo: minimal, base and variant
        # in both hypervisor workflows, negativo-rpms.
        self.assertEqual(publishing, 9)


if __name__ == "__main__":
    unittest.main()
