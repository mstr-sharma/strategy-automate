"""Imported first by every test module: the suite must not depend on, or touch, the operator's setup.

- MSTR_* variables (a real MSTR_BASE, MSTR_API_TOKEN, MSTR_AUTH_METHOD, ...) are removed, so
  tests behave the same on every machine and can never reach a real tenant by accident.
- Proxy variables are removed and NO_PROXY covers everything: the loopback servers the tests
  start must not be routed through a corporate proxy.
- Secrets go to a throw-away file store, never the macOS Keychain, libsecret or
  ~/.config/strategy-automate. Tests that need other values set them with mock.patch.dict.
"""
import atexit
import os
import shutil
import tempfile

for _key in [k for k in os.environ if k.startswith("MSTR_")
             or k.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")]:
    del os.environ[_key]

_HOME = tempfile.mkdtemp(prefix="strategy-tests-")
atexit.register(shutil.rmtree, _HOME, True)
os.environ.update({
    "NO_PROXY": "*",
    "MSTR_SECRET_STORE": "file",
    "XDG_CONFIG_HOME": os.path.join(_HOME, "config"),
    "XDG_CACHE_HOME": os.path.join(_HOME, "cache"),
})
