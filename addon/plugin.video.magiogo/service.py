"""Service entry point. Puts resources/lib on the path and runs the service loop."""

import os
import sys

import xbmcaddon

sys.path.insert(
    0, os.path.join(xbmcaddon.Addon().getAddonInfo("path"), "resources", "lib")
)

from magiogo.service import main  # noqa: E402

main()
