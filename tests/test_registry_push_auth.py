#!/usr/bin/env python3
"""Every registry write in CI passes the sealed login.

The homelab registry takes pushes only from `ci` (F25 in the 2026-10 audit:
zot answered anonymous pushes from anywhere on the LAN, and hosts accept the
mirrored public names unsigned). zot's side is the registry bundle's config,
which workloadctl's suite holds. This side: every Forgejo step that writes to
the registry (`podman push`, a `skopeo copy` to a floating or dated tag)
passes the sealed login, in a step that refuses to run without it. A push step
added without it would fail at push time with a 401; this fails here first.
"""
import re
import unittest

from tests import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".forgejo" / "workflows"


class WorkflowLoginTests(unittest.TestCase):
    WRITE = re.compile(r"^\s*(sudo\s+)?(podman push|skopeo copy)\b")

    def steps(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            step, start = [], 0
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if re.match(r"\s*- name:", line):
                    if step:
                        yield path.name, start, step
                    step, start = [], n
                step.append(line)
            if step:
                yield path.name, start, step

    def test_every_registry_write_passes_the_sealed_login(self):
        writes = 0
        for name, start, step in self.steps():
            code = [ln for ln in step if not ln.strip().startswith("#")]
            uses = [ln for ln in code if self.WRITE.search(ln)]
            if not uses:
                continue
            with self.subTest(workflow=name, step_line=start):
                text = "\n".join(code)
                self.assertIn('test -s "${CREDS}/registry-auth"', text)
                self.assertIn(
                    'AUTH_ARGS=(--authfile "${CREDS}/registry-auth")', text)
                for ln in uses:
                    writes += 1
                    self.assertIn('"${AUTH_ARGS[@]}"', ln)
        self.assertGreater(writes, 0)


if __name__ == "__main__":
    unittest.main()
