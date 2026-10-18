#!/usr/bin/env python3
"""Policy: tracked files may not cite untracked docs.

A citation is a promise that a reader can follow it from a clean checkout:
rationale that lives only in an unreachable file reads as authoritative and
cannot be checked. This walks every tracked file and asserts that two kinds of
citation resolve to something tracked:

  1. a bare `*.md` reference, anywhere — prose, a comment, a workflow;
  2. a **markdown link target**, `[text](path)`, at any extension.

The axis is link *syntax*, not file extension: a path in prose or in a code
line is often illustrative (a unit-name fragment, an in-container path, a
path on a running host), while `[text](target)` is syntactically a promise
the reader can follow it. workloadctl's docs are its repository's, cited by
URL.

Skipped cleanly when git isn't available or the tree isn't a checkout.
"""
import re
import subprocess
import unittest
from pathlib import Path

from tests import REPO_ROOT

GIT_ROOT = REPO_ROOT

# A leading dot is part of the path, not a boundary: `.github/workflows/x.md`
# must be matched whole, or it degrades to `github/workflows/x.md` and resolves
# to nothing.
CITATION = re.compile(
    r"(?<![A-Za-z0-9])(/?\.?[A-Za-z0-9_][A-Za-z0-9_./-]*\.md)(?![A-Za-z0-9])")

# `[text](target)`, with an optional "title" after the target. Reference-style
# links and bare autolinks are deliberately not matched — neither appears in
# this tree, and both would need their own resolution rules.
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# Anything with a scheme is somebody else's namespace. Stripped from the line
# before scanning rather than guarded against afterwards: a citation regex can
# match starting *inside* a URL (`https://just.systems/install.sh` matches from
# the `/`), and a guard that inspects the text before the match then sees only
# `https:` and lets it through.
URL = re.compile(r"[a-z][a-z0-9+.-]*://\S+")
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:")

# Absolute paths naming a location on a *running host*, not a file in the repo.
RUNTIME_PREFIXES = ("/usr/", "/etc/", "/var/", "/run/", "/tmp/", "/home/", "/opt/")

# `~/...` is the same idea as RUNTIME_PREFIXES one syntax over: it names a
# location in whoever-is-reading's home directory, which is by construction not
# a file in this repo. Stripped from the line rather than guarded against after
# the match, for the reason URLs are: CITATION starts matching *inside* it
# (`~/.claude/CLAUDE.md` matches from the slash, yielding `/.claude/CLAUDE.md`),
# so a check on the text before the match sees only `~/` on a path the regex
# has already reduced to a repo-shaped one.
HOME_RELATIVE = re.compile(r"~/\S*")


def _scannable(line: str) -> str:
    """The part of a line that can hold a citation to a file in this repo."""
    return HOME_RELATIVE.sub(" ", URL.sub(" ", line))

# Citations into someone else's source tree. The policy is about docs *we* own;
# an upstream filename is a useful pointer even though it is not in this repo.
# Keep this list short — every entry is a citation a reader cannot follow from a
# clean checkout, so it needs to be worth that.
EXTERNAL: set[str] = set()


def _resolves_against(tracked, citing: Path, cite: str) -> bool:
    """Does `cite`, as written in `citing`, name a tracked file?"""
    bare = cite.lstrip("/")
    if "/" in bare:
        # A path is resolved against each ancestor directory of the citing
        # file, innermost first: `scripts/x.md` inside .forgejo/ means
        # .forgejo/scripts/x.md, and `docs/x.md` anywhere means the root
        # docs/. Both are legitimate.
        for base in citing.parents:
            candidate = (base / bare).resolve()
            try:
                rel = candidate.relative_to(GIT_ROOT).as_posix()
            except ValueError:
                continue
            if rel in tracked:
                return True
            if base == GIT_ROOT:
                break
        return False
    # A bare filename is a relative link whose base depends on where the
    # reader is (a docs/ index row, a "see cli.md" in a sibling doc), so it
    # is enough that some tracked file has that name. Case-sensitive on
    # purpose: `readme.md` does not resolve to `README.md` on the
    # case-sensitive filesystems this ships to.
    return any(t.rsplit("/", 1)[-1] == bare for t in tracked)


def _git(*args):
    return subprocess.run(
        ["git", *args], cwd=GIT_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout


class TestDocCitations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.tracked = set(_git("ls-files").split())
        except (OSError, subprocess.CalledProcessError) as e:
            raise unittest.SkipTest(f"git unavailable: {e}")
        if not cls.tracked:
            raise unittest.SkipTest("no tracked files")

    def _resolves(self, citing: Path, cite: str) -> bool:
        return _resolves_against(self.tracked, citing, cite)

    def _link_resolves(self, citing: Path, target: str) -> bool:
        """Does a markdown link target name something a reader can open?

        Same resolution as a citation, with two additions a link needs and a
        prose mention doesn't: a trailing `#anchor` is part of the link, not
        the path; and a link may legitimately point at a directory.
        """
        target = target.split("#", 1)[0]
        if not target:
            return True  # pure in-page anchor
        if self._resolves(citing, target):
            return True
        bare = target.lstrip("/")
        if "/" not in bare:
            return False
        for base in citing.parents:
            candidate = (base / bare).resolve()
            try:
                rel = candidate.relative_to(GIT_ROOT).as_posix()
            except ValueError:
                continue
            # A directory counts only if the repo actually tracks something
            # under it — an empty or gitignored directory is as unfollowable
            # from a clean checkout as a missing file.
            if any(t == rel or t.startswith(rel.rstrip("/") + "/")
                   for t in self.tracked):
                return True
            if base == GIT_ROOT:
                break
        return False

    def _violations(self):
        found = []
        own = Path(__file__).resolve().relative_to(GIT_ROOT).as_posix()
        for rel in sorted(self.tracked):
            path = GIT_ROOT / rel
            if not path.is_file():
                continue
            # This module's own `*.md` strings are the fixtures the regression
            # test feeds the checker: names chosen precisely because they do not
            # resolve. Scanning them would make the file fail itself.
            if rel == own:
                continue
            try:
                text = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue  # binary or unreadable: nothing to cite from
            for lineno, line in enumerate(text.splitlines(), 1):
                # An RPM macro path is a build destination, not a citation.
                if "%{" in line:
                    continue
                for m in LINK.finditer(line):
                    target = m.group(1)
                    if SCHEME.match(target) or target.startswith("#"):
                        continue  # URL, mailto:, in-page anchor
                    if target in EXTERNAL or target.startswith(RUNTIME_PREFIXES):
                        continue
                    if target.startswith("~/"):
                        continue  # the reader's home, not this repo
                    if not self._link_resolves(path, target):
                        found.append(f"{rel}:{lineno} links to {target!r}")
                for m in CITATION.finditer(_scannable(line)):
                    cite = m.group(1)
                    if cite in EXTERNAL or cite.startswith(RUNTIME_PREFIXES):
                        continue
                    if not self._resolves(path, cite):
                        found.append(f"{rel}:{lineno} cites {cite!r}")
        return found

    def test_every_cited_doc_is_tracked(self):
        violations = self._violations()
        self.assertEqual(
            violations, [],
            "tracked files cite or link to paths that are not tracked — write "
            "the file, retarget at something tracked, or drop it:\n  "
            + "\n  ".join(violations))

    def test_the_checker_would_notice_a_regression(self):
        """A green result is only meaningful if the check can fail. Guards
        against a future refactor that quietly stops matching anything."""
        probe = GIT_ROOT / "hypervisor.Containerfile"
        self.assertIn(probe.as_posix().replace(GIT_ROOT.as_posix() + "/", ""),
                      self.tracked, "probe file is not tracked")
        self.assertFalse(self._resolves(probe, "docs/wip/does-not-exist.md"))
        self.assertFalse(self._resolves(probe, "totally-made-up-name.md"))
        self.assertFalse(self._resolves(probe, "workloadctl/docs/cli.md"))
        # And a real one still resolves, so it is not just rejecting everything.
        self.assertTrue(self._resolves(probe, "docs/ci-image-signing.md"))

    def test_link_targets_are_checked_at_any_extension(self):
        """The Q3-9 class: a `.md` → non-`.md` link. The extension filter on
        CITATION means only the link rule can see these."""
        probe = GIT_ROOT / "README.md"
        self.assertFalse(self._link_resolves(probe, "workloadctl/justfile"))
        self.assertFalse(
            self._link_resolves(probe, ".forgejo/workflows/nonesuch.yml"))
        self.assertTrue(self._link_resolves(probe, "fedora-versions.yml"))
        self.assertTrue(
            self._link_resolves(probe, ".forgejo/workflows/image-test.yml"))

    def test_link_anchor_is_not_part_of_the_path(self):
        probe = GIT_ROOT / "README.md"
        self.assertTrue(self._link_resolves(probe, "docs/ci-image-signing.md#x"))
        self.assertFalse(self._link_resolves(probe, "no-such-doc.md#x"))

    def test_link_may_point_at_a_directory_that_has_tracked_content(self):
        probe = GIT_ROOT / "README.md"
        self.assertTrue(self._link_resolves(probe, "security/"))
        self.assertFalse(self._link_resolves(probe, "no-such-dir/"))
        # A directory with nothing tracked under it is as unfollowable from a
        # clean checkout as a missing file.
        self.assertFalse(self._link_resolves(probe, ".reference/"))

    def test_dotted_directories_are_matched_whole(self):
        """`.forgejo/...` must not degrade to `forgejo/...`, which resolves to
        nothing and would make every CI citation a false positive."""
        m = CITATION.search("see .forgejo/workflows/nope.md for details")
        self.assertEqual(m.group(1), ".forgejo/workflows/nope.md")

    def test_a_home_relative_path_is_not_a_citation(self):
        """`~/.claude/CLAUDE.md` names a file in the reader's home. Left
        unstripped, CITATION matches from the dot and reports it as the repo
        path `/.claude/CLAUDE.md`, so the tilde has to come off the line
        before the scan rather than be inspected after it."""
        line = "rtk init --global   # Add RTK to ~/.claude/CLAUDE.md"
        self.assertEqual(CITATION.search(line).group(1), "/.claude/CLAUDE.md")
        self.assertIsNone(CITATION.search(_scannable(line)))
        # Only the tilde path is removed: a real citation on the same line
        # still has to resolve.
        both = "see docs/ci-image-signing.md and ~/.config/notes.md"
        self.assertEqual(
            [m.group(1) for m in CITATION.finditer(_scannable(both))],
            ["docs/ci-image-signing.md"])
        # And a link target is skipped by its own guard, not by _scannable.
        probe = GIT_ROOT / "README.md"
        self.assertFalse(self._link_resolves(probe, "~/.claude/CLAUDE.md"))

    def test_a_path_inside_a_url_is_not_a_citation(self):
        """A citation regex can match starting mid-URL, so URLs are stripped
        from the line before scanning rather than guarded against after."""
        line = "curl -sSf https://example.com/docs/nonexistent.md -o x"
        self.assertIsNone(CITATION.search(URL.sub(" ", line)))
        # The link rule has its own scheme guard.
        self.assertTrue(SCHEME.match("https://example.com/a.yml"))


if __name__ == "__main__":
    unittest.main()
