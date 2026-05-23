"""Entry point. Kodi calls this with sys.argv = [base_url, handle, query].

It only puts ``resources/lib`` on the path (so the ``core`` package and the
vendored single-file deps are importable) and hands off to the real router.
"""

import os
import sys

import xbmcaddon

sys.path.insert(
    0, os.path.join(xbmcaddon.Addon().getAddonInfo("path"), "resources", "lib")
)

from magiogo.plugin import run  # noqa: E402

run()
