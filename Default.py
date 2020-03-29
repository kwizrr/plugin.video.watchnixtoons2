# -*- coding: utf-8 -*-
#from Lib.Plugin import main

import xbmcaddon, xbmcgui

ADDON_ICON = xbmcaddon.Addon().getAddonInfo('icon')
xbmcgui.Dialog().ok(
    "WatchNixtoons2",
    "The source website has (temporarily?) blocked all watching for free, now only paid accounts work. " \
    "If this block is ever lifted we'll update the add-on.\nFor now it's not working, sorry."
)

# Commented for now. No point in hammering the source website with fruitless requests.
#main() # See bottom of Plugin.py.