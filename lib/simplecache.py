# -*- coding: utf-8 -*-
import json

import xbmc
import xbmcvfs
import xbmcaddon

from time import time

from lib.common import (
    getWindowProperty,
    setWindowProperty,
    setRawWindowProperty,
    testWindowProperty,
    clearWindowProperty
)


CACHE_PATH = xbmc.translatePath(xbmcaddon.Addon().getAddonInfo('profile')).decode('utf-8') + 'cache.json'


# Simple JSON and window property dictionary cache.

class SimpleCache():

    PROPERTY_CACHE = 'simplecache.cache'
    PROPERTY_CACHE_FILE_DIRTY = 'simplecache.dirty'
    PROPERTY_CACHE_LOADED = 'simplecache.loaded'
    PROPERTY_CACHE_MEMORY_DIRTY = 'simplecache.memoryDirty'

    def __init__(self):
        self.cache = None


    def ensureCacheLoaded(self):
        if not self.isCacheLoaded():
            self.reloadCache()
        else:
            clearWindowProperty(self.PROPERTY_CACHE_MEMORY_DIRTY)


    def isCacheLoaded(self):
        # Test cache existence with a small flag just so we don't have to keep loading
        # the (large) JSON cache from memory to test if it exists.
        return testWindowProperty(self.PROPERTY_CACHE_LOADED) and self.cache
        

    def reloadCache(self):
        # Try to load the cache from memory first.
        self.cache = getWindowProperty(self.PROPERTY_CACHE)
        if not self.cache:
            # Try to load or create the cache file.
            if xbmcvfs.exists(CACHE_PATH):
                file = xbmcvfs.File(CACHE_PATH)
                try:
                    self.cache = json.loads(file.read())
                except:
                    # Error. Notification with no sound.
                    from xbmcgui import Dialog, NOTIFICATION_INFO
                    dialog = Dialog()
                    dialog.notification('Cache', 'Could not read cache file', NOTIFICATION_INFO, 2500, False)
                    self.cache = self.blankCache()
                finally:
                    file.close()
            else:
                # Create new cache file.
                file=xbmcvfs.File(CACHE_PATH, 'w')
                self.cache = self.blankCache()
                file.write(json.dumps(self.cache))
                file.close()
            setWindowProperty(self.PROPERTY_CACHE, self.cache)
            setRawWindowProperty(self.PROPERTY_CACHE_MEMORY_DIRTY, '1')
        clearWindowProperty(self.PROPERTY_CACHE_FILE_DIRTY)
        clearWindowProperty(self.PROPERTY_CACHE_LOADED)        


    def getCacheItem(self, key):
        return self.cache.get(key, None)


    def addCacheItem(self, key, data):
        self.cache[key] = data
        setRawWindowProperty(self.PROPERTY_CACHE_FILE_DIRTY, '1')
        setRawWindowProperty(self.PROPERTY_CACHE_MEMORY_DIRTY, '1')


    def flushCacheToMemory(self):
        if testWindowProperty(self.PROPERTY_CACHE_MEMORY_DIRTY):
            setWindowProperty(self.PROPERTY_CACHE, self.cache)
            setRawWindowProperty(self.PROPERTY_CACHE_LOADED, '1')
            clearWindowProperty(self.PROPERTY_CACHE_MEMORY_DIRTY)


    def saveCache(self):
        if testWindowProperty(self.PROPERTY_CACHE_FILE_DIRTY):
            self.ensureCacheLoaded()
            if len(self.cache):
                file=xbmcvfs.File(CACHE_PATH, 'w')
                file.write(json.dumps(self.cache))
                file.close()
            clearWindowProperty(self.PROPERTY_CACHE_FILE_DIRTY)


    def blankCache():
        return {'_': None} # Dummy value to initialise the JSON object and still be valid.


cache = SimpleCache()
