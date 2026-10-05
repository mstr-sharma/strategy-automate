"""Repo hygiene: nothing operator-specific or secret gets committed.

Scans every tracked file (git ls-files) for things that must never land in this public repo:
secrets and credential files, private keys and tokens, personal home-directory paths, e-mail
addresses, and Strategy tenant host names other than documentation hosts and placeholders.
The checks are generic on purpose — the repo cannot list the names it must not contain.
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FORBIDDEN_FILES = re.compile(
    r"(^|/)(\.env|\.coverage|id_rsa[^/]*|id_ed25519[^/]*|[^/]*\.(pem|key|p12|pfx|bundle|jks|keystore))$")
SECRETS = {
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "JSON web token": re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "Strategy token value": re.compile(r"X-MSTR-AuthToken['\"]?\s*[:=]\s*['\"]?[a-z0-9]{20,}", re.I),
    # test fixtures may carry passwords, but they must look fake (fake-, dummy, example, ...)
    "password value": re.compile(r"""(?i)\bpassword["']?\s*[:=]\s*["'](?![^"']*(?:fake|dummy|example|placeholder|changeme|redacted))[^"'<>{}$\s]{8,}["']"""),
}
HOME_PATH = re.compile(r"(/Users|/home|C:\\Users)[/\\](?!<)[A-Za-z][A-Za-z0-9._-]*[/\\]")
HOME_PATH_OK = {"/home/runner/"}    # GitHub Actions runner paths in docs
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b")
# example.com/.org/.net and the reserved TLDs of RFC 2606 (.example, .invalid, .test, .localhost)
EMAIL_OK = re.compile(r"@((\w[\w-]*\.)*(example\.(com|org|net)|[\w-]+\.(example|invalid|test|localhost))|anthropic\.com)$",
                      re.I)
TENANT_HOST = re.compile(r"(?<![A-Za-z0-9<>_.-])[A-Za-z0-9<>_.-]+\.(?:micro)?strategy\.com\b", re.I)
TENANT_HOST_OK = {
    # documentation and community hosts
    "community.strategy.com", "www.strategy.com", "www2.strategy.com",
    "www.microstrategy.com", "www2.microstrategy.com", "demo.microstrategy.com",
    # placeholders
    "<tenant>.strategy.com", "<tenant>.customer.cloud.microstrategy.com",
    "yourtenant.customer.cloud.microstrategy.com", "foo.strategy.com",
}
SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".zip", ".pptx", ".docx", ".xlsx")
SELF = "tests/test_repo_hygiene.py"


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


class RepoHygieneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = tracked_files()
        if cls.files is None:
            raise unittest.SkipTest("not a git checkout")
        cls.texts = {}
        for path in cls.files:
            if path == SELF or path.lower().endswith(SKIP_SUFFIXES):
                continue
            full = os.path.join(ROOT, path)
            if not os.path.isfile(full):
                continue   # deleted in the working tree
            with open(full, "rb") as f:
                raw = f.read()
            if b"\0" in raw[:8192]:
                continue   # binary
            cls.texts[path] = raw.decode("utf-8", "replace")

    def _hits(self, pattern, allowed=lambda m: False):
        hits = []
        for path, text in self.texts.items():
            for lineno, line in enumerate(text.splitlines(), 1):
                for m in pattern.finditer(line):
                    if not allowed(m):
                        hits.append(f"{path}:{lineno}: {m.group(0)[:80]}")
        return hits

    def test_no_secret_or_credential_files_are_tracked(self):
        bad = [p for p in self.files if FORBIDDEN_FILES.search(p) and not p.endswith(".env.example")]
        self.assertEqual(bad, [], "credential or local-state files are tracked")

    def test_no_secrets_in_tracked_text(self):
        found = {name: self._hits(rx) for name, rx in SECRETS.items()}
        self.assertEqual({k: v for k, v in found.items() if v}, {})

    def test_no_personal_home_paths(self):
        self.assertEqual(self._hits(HOME_PATH, lambda m: m.group(0) in HOME_PATH_OK), [],
                         "use ~/ or <you> instead of a real home directory")

    def test_only_placeholder_email_addresses(self):
        self.assertEqual(self._hits(EMAIL, lambda m: bool(EMAIL_OK.search(m.group(0)))), [],
                         "use an example.com address")

    def test_no_real_tenant_host_names(self):
        self.assertEqual(self._hits(TENANT_HOST, lambda m: m.group(0).lower() in TENANT_HOST_OK), [],
                         "use <tenant>.strategy.com for tenant hosts")

    def test_patterns_catch_what_they_should(self):
        # Guard against a pattern silently matching nothing.
        self.assertTrue(HOME_PATH.search("/Users/someone/Desktop/x"))
        self.assertFalse(HOME_PATH.search("/Users/<you>/Desktop/x"))
        self.assertTrue(EMAIL.search("name@company.io"))
        self.assertTrue(EMAIL_OK.search("ops@tenant.example.com"))
        self.assertTrue(TENANT_HOST.search("https://acme-prod.strategy.com/MicroStrategyLibrary"))
        self.assertTrue(FORBIDDEN_FILES.search("config/.env"))
        self.assertFalse(FORBIDDEN_FILES.search(".env.example"))
        self.assertTrue(SECRETS["password value"].search('password = "hunter22hunter"'))
        self.assertFalse(SECRETS["password value"].search('password = "<password>"'))
        self.assertFalse(SECRETS["password value"].search('"password": "fake-S3cret!"'))
        self.assertTrue(EMAIL_OK.search("p@tenant.invalid"))
        self.assertFalse(EMAIL_OK.search("p@tenant.io"))


if __name__ == "__main__":
    unittest.main()
