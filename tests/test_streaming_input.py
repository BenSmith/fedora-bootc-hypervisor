#!/usr/bin/env python3
"""The image gives the input devices uinput makes to their own group.

/dev/uinput and the nodes under /devices/virtual/input go to a `uinput`
group; the physical keyboards and mice stay `input`'s. A streaming workload
that grants /dev/uinput joins `uinput`, and so cannot read every key typed at
the host (audit F16). A rule that handed a node to `input` would build green.
"""
import re
import unittest

from tests import REPO_ROOT

CONTAINERFILE = REPO_ROOT / "hypervisor.Containerfile"


class Image(unittest.TestCase):

    def setUp(self):
        self.text = CONTAINERFILE.read_text()

    def _rules(self):
        return re.findall(
            r"printf '([^']*)\\n' \\\s*>>? /usr/lib/udev/rules\.d/"
            r"72-uinput-input\.rules", self.text)

    def test_uinput_and_its_nodes_go_to_the_uinput_group(self):
        rules = self._rules()
        self.assertIn('KERNEL=="uinput", GROUP="uinput", MODE="0660"', rules)
        virtual = [r for r in rules if "/devices/virtual/input/" in r]
        self.assertEqual(len(virtual), 1, rules)
        self.assertIn('SUBSYSTEM=="input"', virtual[0])
        self.assertIn('GROUP="uinput"', virtual[0])

    def test_no_rule_hands_a_node_to_input(self):
        rules = self._rules()
        self.assertTrue(rules)
        self.assertFalse([r for r in rules if 'GROUP="input"' in r])

    def test_the_group_exists(self):
        self.assertRegex(self.text,
                         r"printf 'g uinput - -\\n' > /usr/lib/sysusers\.d/")


if __name__ == "__main__":
    unittest.main()
