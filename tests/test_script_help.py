"""Every script runs `--help` cleanly on this interpreter: catches syntax and import errors, and
features newer than the oldest supported Python (3.9), in files no other test imports."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = sorted(p for p in (ROOT / "skills").glob("*/scripts/*.py") if "__main__" in p.read_text(encoding="utf-8"))


class ScriptHelpTests(unittest.TestCase):
    def test_every_script_prints_help(self):
        self.assertGreater(len(SCRIPTS), 10)
        failures = []
        for script in SCRIPTS:
            r = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True,
                               timeout=60, cwd=ROOT, env=dict(os.environ), stdin=subprocess.DEVNULL)
            if r.returncode != 0 or "usage" not in r.stdout.lower():
                failures.append(f"{script.relative_to(ROOT)}: exit {r.returncode}: {(r.stderr or r.stdout)[-300:]}")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
