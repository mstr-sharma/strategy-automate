"""Every operation a SKILL.md tells an agent to run (`strategy_api.py call|describe <op>`) must
exist in the spec index — so skills can't drift onto endpoints the platform doesn't have."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "tests" / "fixtures" / "strategy_rest_operations.tsv"
REF = re.compile(r'(?:strategy_api\.py|\$API)\s+(?:call|describe)\s+'
                 r'("(?:GET|POST|PUT|PATCH|DELETE|HEAD) /api/[^"]+"|[A-Za-z][A-Za-z0-9_\-]*[A-Za-z0-9_])')


def _template(path):
    return re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path)) + "$")


class SkillOperationTests(unittest.TestCase):
    def test_skill_references_resolve(self):
        ids, routes = set(), []
        for line in INDEX.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 5:
                routes.append((parts[0], parts[1], _template(parts[1])))
                ids.add(parts[4])
        problems, seen = [], 0
        for skill in sorted((ROOT / "skills").glob("*/SKILL.md")):
            text = skill.read_text(encoding="utf-8")
            for m in REF.finditer(text):
                ref = m.group(1).strip('"')
                seen += 1
                if " " in ref:
                    verb, path = ref.split(" ", 1)
                    ok = any(v == verb and (p == path or t.match(path)) for v, p, t in routes)
                else:
                    ok = ref in ids
                if not ok:
                    problems.append(f"{skill.relative_to(ROOT)}:{text[:m.start()].count(chr(10)) + 1} {ref}")
        self.assertGreater(seen, 0)
        self.assertEqual(problems, [], "skills reference operations that are not in the spec index")


if __name__ == "__main__":
    unittest.main()
