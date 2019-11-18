# -*- coding: utf-8 -*-
import re
import sys
import requests

from itertools import chain
from base64 import b64decode
from time import time, sleep
from urlparse import parse_qsl
from string import ascii_uppercase
from urllib import quote_plus, urlencode

import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin

from Lib.Common import *
from Lib.SimpleTrakt import SimpleTrakt

# Disable urllib3's "InsecureRequestWarning: Unverified HTTPS request is being made" warnings
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


PLUGIN_ID = int(sys.argv[1])
PLUGIN_URL = sys.argv[0]

BASEURL = 'https://www.wcostream.com'
BASEURL_MOBILE = 'https://m.wcostream.com'

PROPERTY_CATALOG_PATH = 'wnt2.catalogPath'
PROPERTY_CATALOG = 'wnt2.catalog'
PROPERTY_EPISODE_LIST_URL = 'wnt2.listURL'
PROPERTY_EPISODE_LIST_DATA = 'wnt2.listData'
PROPERTY_LATEST_MOVIES = 'wnt2.latestMovies'
PROPERTY_INFO_ITEMS = 'wnt2.infoItems'
PROPERTY_SESSION_COOKIE = 'wnt2.cookie'

ADDON = xbmcaddon.Addon()
# Show catalog: whether to show the catalog categories or to go straight to the "ALL" section with all items visible.
ADDON_SHOW_CATALOG = ADDON.getSetting('showCatalog') == 'true'
# Use Latest Releases date: whether to sort the Latest Releases items by their date, or with a catalog.
ADDON_LATEST_DATE = ADDON.getSetting('useLatestDate') == 'true'
# Use Latest Releases thumbs: whether to show a little thumbnail available for the Latest Releases items only.
ADDON_LATEST_THUMBS = ADDON.getSetting('showLatestThumbs') == 'true'
ADDON_ICON = ADDON.getAddonInfo('icon')
ADDON_ICON_DICT = {'icon': ADDON_ICON, 'thumb': ADDON_ICON, 'poster': ADDON_ICON}
ADDON_TRAKT_ICON = 'special://home/addons/plugin.video.watchnixtoons2/resources/traktIcon.png'

# To let the source website know it's this plugin. Also used inside "makeLatestCatalog()" and "actionResolve()".
WNT2_USER_AGENT = 'Mozilla/5.0 (compatible; WatchNixtoons2/0.3.7; ' \
'+https://github.com/doko-desuka/plugin.video.watchnixtoons2)'

MEDIA_HEADERS = None # Initialized in 'actionResolve()'.

# Url paths: paths to parts of the website, to be added to the BASEURL / BASEURL_MOBILE urls.
# Also used to tell what kind of catalog is loaded in memory.
# In case they change in the future it'll be easier to modify in here.
URL_PATHS = {
    'latest': 'latest', # No path used, 'makeLatestCatalog()' is hardcoded to use the homepage of the mobile website.
    'popular': '/ongoing-series',
    'dubbed': '/dubbed-anime-list',
    'cartoons': '/cartoon-list',
    'subbed': '/subbed-anime-list',
    'movies': '/movie-list',
    'latestmovies': '/anime/movies',
    'ova': '/ova-list',
    'search': '/search',
    'genre': '/search-by-genre'
}


def actionMenu(params):
    def _menuItem(title, data, color):
        item = xbmcgui.ListItem('[B][COLOR ' + color + ']' + title + '[/COLOR][/B]', label2 = title)
        item.setArt(ADDON_ICON_DICT)
        item.setInfo('video', {'title': title, 'plot': title})
        return (buildURL(data), item, True)

    xbmcplugin.addDirectoryItems(
        PLUGIN_ID,
        (
            _menuItem('Latest Releases', {'action': 'actionCatalogMenu', 'path': URL_PATHS['latest']}, 'mediumaquamarine'),
            _menuItem( # Make the Latest Movies menu go straight to the item list, no catalog.
                'Latest Movies', {'action': 'actionLatestMoviesMenu', 'path': URL_PATHS['latestmovies']}, 'mediumaquamarine'
            ),
            _menuItem('Popular & Ongoing Series', {'action': 'actionCatalogMenu', 'path': URL_PATHS['popular']}, 'mediumaquamarine'),
            _menuItem('Dubbed Anime', {'action': 'actionCatalogMenu', 'path': URL_PATHS['dubbed']}, 'lightgreen'),
            _menuItem('Cartoons', {'action': 'actionCatalogMenu', 'path': URL_PATHS['cartoons']}, 'lightgreen'),
            _menuItem('Subbed Anime', {'action': 'actionCatalogMenu', 'path': URL_PATHS['subbed']}, 'lightgreen'),
            _menuItem('Movies', {'action': 'actionCatalogMenu', 'path': URL_PATHS['movies']}, 'lightgreen'),
            _menuItem('OVA Series', {'action': 'actionCatalogMenu', 'path': URL_PATHS['ova']}, 'lightgreen'),
            _menuItem('Search', {'action': 'actionSearchMenu',  'path': 'search'}, 'lavender'), # Non-web path.
            _menuItem('Settings', {'action': 'actionShowSettings','path': 'settings'}, 'lavender') # Non-web path.
        )
    )
    xbmcplugin.endOfDirectory(PLUGIN_ID)


def actionCatalogMenu(params):
    xbmcplugin.setContent(PLUGIN_ID, 'tvshows')
    catalog = getCatalogProperty(params)

    if ADDON_SHOW_CATALOG:
        listItems = tuple(
            (
                buildURL({'action': 'actionCatalogSection', 'path': params['path'], 'section': sectionName}),
                xbmcgui.ListItem(sectionName),
                True
            )
            for sectionName in sorted(catalog.iterkeys()) if len(catalog[sectionName])
        )
        if len(listItems):
            if len(listItems) > 1:
                sectionAll = (
                    buildURL({'action': 'actionCatalogSection', 'path': params['path'], 'section': 'ALL'}),
                    xbmcgui.ListItem('All'),
                    True
                )
                xbmcplugin.addDirectoryItems(PLUGIN_ID, (sectionAll,) + listItems)
            else:
                # Conveniency when a search leads to only 1 result, show it already without the catalog screen.
                params['section'] = 'ALL'
                actionCatalogSection(params)
                return
        else:
            xbmcplugin.addDirectoryItem(PLUGIN_ID, '', xbmcgui.ListItem('(No Results)'), isFolder=False)
        xbmcplugin.endOfDirectory(PLUGIN_ID)
        setViewMode()
    else:
        params['section'] = 'ALL'
        actionCatalogSection(params)


def actionCatalogSection(params):
    catalog = getCatalogProperty(params)
    path = params['path']
    
    # Set up a boolean indicating if the catalog items are already playable, instead of being folders
    # with more items inside.
    # This is true for the OVA, movies, latest-episodes, movie-search and episode-search catalogs.
    # Items in these catalogs link to the video player pages already.
    isSpecial = (
        path in {URL_PATHS['ova'], URL_PATHS['movies'], URL_PATHS['latest']}
        or params.get('searchType', 'series') != 'series' # not series = movies or episodes search
    )

    if isSpecial:
        action = 'actionResolve'
        isFolder = False
    else:
        action = 'actionEpisodesMenu'
        isFolder = True

    thumb = params.get('thumb', ADDON_ICON)
    if path != URL_PATHS['latest'] or not ADDON_LATEST_THUMBS:
        artDict = {'icon': thumb, 'thumb': thumb, 'poster': thumb} if thumb else None
    else:
        artDict = {'icon': thumb, 'thumb': 'DefaultVideo.png', 'poster': 'DefaultVideo.png'} if thumb else None

    # Persistent property with item metadata, used with the "Show Information" context menu.
    infoItems = getWindowProperty(PROPERTY_INFO_ITEMS) or { }

    if 'query' not in params and ADDON.getSetting('cleanupEpisodes') == 'true':
        listItemFunc = makeListItemClean
    else:
        listItemFunc = makeListItem

    if params['section'] == 'ALL':
        sectionItems = chain.from_iterable(catalog[sectionName] for sectionName in sorted(catalog))
    else:
        sectionItems = catalog[params['section']]

    def _sectionItemsGen():
        if ADDON_LATEST_THUMBS and path == URL_PATHS['latest']:
            # Special-case for the 'Latest Releases' catalog, which has some thumbnails available.
            # Each 'entry' is (URL, htmlTitle, thumb).
            NO_THUMB = '-120-72.jpg' # As seen on 2019-04-15.
            for entry in sectionItems:
                entryURL = entry[0]
                entryArt = (
                    artDict if entry[2].startswith(NO_THUMB) else {'icon':ADDON_ICON,'thumb':entry[2],'poster':entry[2]}
                )
                # If there's metadata for this entry (requested by the user with "Show Information"), use it.
                if entryURL in infoItems:
                    itemPlot, itemThumb = infoItems[entryURL]
                    yield (
                        buildURL({'action': action, 'url': entryURL}),
                        listItemFunc(entry[1], entryURL, entryArt, itemPlot, isFolder, isSpecial, None),
                        isFolder
                    )
                else:
                    yield (
                        buildURL({'action': action, 'url': entryURL}),
                        listItemFunc(entry[1], entryURL, entryArt, '', isFolder, isSpecial, params),
                        isFolder
                    )
        else:
            # Normal item listing, each 'entry' is (URL, htmlTitle).
            for entry in sectionItems:
                entryURL = entry[0]
                if entryURL in infoItems:
                    itemPlot, itemThumb = infoItems[entryURL]
                    entryArt = {'icon': ADDON_ICON, 'thumb': itemThumb, 'poster': itemThumb}
                    yield (
                        buildURL({'action': action, 'url': entryURL}),
                        listItemFunc(entry[1], entryURL, entryArt, itemPlot, isFolder, isSpecial, None),
                        isFolder
                    )
                else:
                    yield (
                        buildURL({'action': action, 'url': entryURL}),
                        listItemFunc(entry[1], entryURL, artDict, '', isFolder, isSpecial, params),
                        isFolder
                    )

    xbmcplugin.addDirectoryItems(PLUGIN_ID, tuple(_sectionItemsGen()))
    xbmcplugin.endOfDirectory(PLUGIN_ID)
    setViewMode() # Set the skin layout mode, if the option is enabled.


def actionEpisodesMenu(params):
    xbmcplugin.setContent(PLUGIN_ID, 'episodes')

    # Memory-cache the last episode list, to help when the user goes back and forth while watching
    # multiple episodes of the same show. This way only one web request is needed for the same show.
    lastListURL = getRawWindowProperty(PROPERTY_EPISODE_LIST_URL)
    if lastListURL and lastListURL == params['url']:
        listData = getWindowProperty(PROPERTY_EPISODE_LIST_DATA)
    else:
        url = params['url'].replace('watchcartoononline.io', 'wcostream.com', 1) # New domain safety replace.
        # Always get episodes from the mobile version of the show page.
        r = requestHelper(
            url.replace('/www.', '/m.', 1) if url.startswith('http') else BASEURL_MOBILE + url
        )
        html = r.text

        # Try to scrape thumb and plot metadata from the show page.
        dataStartIndex = html.find('category_description')
        if dataStartIndex == -1:
            raise Exception('Episode description scrape fail: ' + url)
        else:
            htmlSlice = html[dataStartIndex : html.find('/p>', dataStartIndex)]
            thumb = re.search('''<img.*?src.*?"(.*?)"''', htmlSlice)
            thumb = thumb.group(1) if thumb else ''
            plot = re.search('''<p>(.*?)<''', htmlSlice, re.DOTALL)
            plot = plot.group(1) if plot else ''

        dataStartIndex = html.find('ui-listview-z', dataStartIndex)
        if dataStartIndex == -1:
            raise Exception('Episode list scrape fail: ' + url)

        # Episode list data: a tuple with the thumb, plot and an inner tuple of per-episode data.
        listData = (
            thumb,
            plot,
            tuple(
                match.groups()
                for match in re.finditer('''<a.*?"(.*?)".*?>(.*?)</''', html[dataStartIndex : html.rfind('button')])
            )
        )
        setRawWindowProperty(PROPERTY_EPISODE_LIST_URL, params['url'])
        setWindowProperty(PROPERTY_EPISODE_LIST_DATA, listData)

    def _episodeItemsGen():
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        playlist.clear()

        showURL = params['url']
        thumb = listData[0]
        artDict = {'icon': thumb, 'thumb': thumb, 'poster': thumb} if thumb else None
        plot = listData[1]

        listItemFunc = makeListItemClean if ADDON.getSetting('cleanupEpisodes') == 'true' else makeListItem

        itemParams = {'action': 'actionResolve', 'url': None}
        listIter = iter(listData[2]) if ADDON.getSetting('reverseEpisodes') == 'true' else reversed(listData[2])
        for URL, title in listIter:
            item = listItemFunc(title, URL, artDict, plot, isFolder=False, isSpecial=False, oldParams=None)
            itemParams['url'] = URL
            itemURL = buildURL(itemParams)
            playlist.add(itemURL, item)
            yield (itemURL, item, False)

    xbmcplugin.addDirectoryItems(PLUGIN_ID, tuple(_episodeItemsGen()))
    xbmcplugin.endOfDirectory(PLUGIN_ID)


def actionLatestMoviesMenu(params):
    # Returns a list of links from a hidden "/anime/movies" area.
    # Since this page is very large (130 KB), we memory cache it after it's been requested.
    html = getRawWindowProperty(PROPERTY_LATEST_MOVIES)
    if not html:
        r = requestHelper(BASEURL + params['path']) # Path unused, data is already on the homepage.
        html = r.text
        setRawWindowProperty(PROPERTY_LATEST_MOVIES, html)

    dataStartIndex = html.find('catlist-listview')
    if dataStartIndex == -1:
        raise Exception('Latest movies scrape fail')

    # Persistent property with item metadata.
    infoItems = getWindowProperty(PROPERTY_INFO_ITEMS) or { }

    def _movieItemsGen():
        artDict = {'icon': ADDON_ICON, 'thumb': ADDON_ICON, 'poster': ADDON_ICON}
        reIter = re.finditer(
            '''<a.*?href="(.*?)".*?>(.*?)</''', html[dataStartIndex : html.find('CAT List FINISH')], re.DOTALL
        )
        # The page has like 6000 items going back to 2010, so we limit to only the latest 200.
        for x in range(200):
            entryURL, entryTitle = next(reIter).groups()
            if entryURL in infoItems:
                entryPlot, entryThumb = infoItems[entryURL]
                yield (
                    buildURL({'action': 'actionResolve', 'url': entryURL}),
                    makeListItem(
                        entryTitle,
                        entryURL,
                        {'icon': ADDON_ICON, 'thumb': entryThumb, 'poster': entryThumb},
                        entryPlot,
                        isFolder=False,
                        isSpecial=True,
                        oldParams=None
                    ),
                    False
                )
            else:
                yield (
                    buildURL({'action': 'actionResolve', 'url': entryURL}),
                    makeListItem(entryTitle, entryURL, artDict, '', isFolder=False, isSpecial=True, oldParams=params),
                    False
                )
    xbmcplugin.addDirectoryItems(PLUGIN_ID, tuple(_movieItemsGen()))
    xbmcplugin.endOfDirectory(PLUGIN_ID)
    setViewMode()


# A sub menu, lists search options.
def actionSearchMenu(params):
    def _modalKeyboard(heading):
        kb = xbmc.Keyboard('', heading)
        kb.doModal()
        return kb.getText() if kb.isConfirmed() else ''

    if 'searchType' in params:
        # Support for the 'actionShowInfo()' function reloading this route, sending it an already searched query.
        # This also supports external query calls, like from OpenMeta.
        if 'query' in params:
            query = params['query']
        else:
            query = _modalKeyboard(params.get('searchTitle', 'Search'))

        if query:
            historyTypeIDs = {'series':'0', 'movies':'1', 'episodes':'2'}
            previousHistory = ADDON.getSetting('searchHistory')
            if previousHistory:
                # Limit search history to 40 items.
                if previousHistory.count('\n') == 40:
                    previousHistory = previousHistory[:previousHistory.rfind('\n')] # Forget the oldest search result.
                ADDON.setSetting('searchHistory', historyTypeIDs[params['searchType']] + query + '\n' + previousHistory)
            else:
                ADDON.setSetting('searchHistory', historyTypeIDs[params['searchType']] + query)
            
            params['query'] = query
            params['section'] = 'ALL' # Force an uncategorized display (results are usually few).
            actionCatalogSection(params) # Send the search type and query for the catalog functions to use.
        return

    xbmcplugin.addDirectoryItems(
        PLUGIN_ID,
        (
            (
                buildURL({
                    'action': 'actionSearchMenu',
                    'path': URL_PATHS['search'], # A special, non-web path used by 'getCatalogProperty()'.
                    'searchType': 'series',
                    'searchTitle': 'Search Cartoon/Anime Name'
                }),
                xbmcgui.ListItem('[COLOR lavender][B]Search Cartoon/Anime Name[/B][/COLOR]'),
                True
            ),
            (
                buildURL({
                    'action': 'actionSearchMenu',
                    'path': URL_PATHS['search'],
                    'searchType': 'movies',
                    'searchTitle': 'Search Movie Name'
                }),
                xbmcgui.ListItem('[COLOR lavender][B]Search Movie Name[/B][/COLOR]'),
                True
            ),
            (
                buildURL({
                    'action': 'actionSearchMenu',
                    'path': URL_PATHS['search'],
                    'searchType': 'episodes',
                    'searchTitle': 'Search Episode Name'
                }),
                xbmcgui.ListItem('[COLOR lavender][B]Search Episode Name[/B][/COLOR]'),
                True
            ),
            (
                buildURL({'action': 'actionGenresMenu', 'path': URL_PATHS['genre']}),
                xbmcgui.ListItem('[COLOR lavender][B]Search by Genre[/B][/COLOR]'),
                True
            ),
            (
                buildURL({'action': 'actionTraktMenu', 'path': 'trakt'}),
                xbmcgui.ListItem('[COLOR lavender][B]Search by Trakt List[/B][/COLOR]'),
                True
            ),
            (
                buildURL({'action': 'actionSearchHistory', 'path': 'searchHistory'}),
                xbmcgui.ListItem('[COLOR lavender][B]Search History...[/B][/COLOR]'),
                True
            )
        )
    )
    xbmcplugin.endOfDirectory(PLUGIN_ID)
    
    
# A sub menu, lists all previous searches along with their categories.
def actionSearchHistory(params):
    history = ADDON.getSetting('searchHistory').split('\n') # Non-UI setting, it's just a big string.
    
    # A blank string split creates a list with a blank string inside, so test if the first item is valid.
    if history[0]:
        # Use list indexes to map to 'searchType' and a label prefix.
        historyTypeNames = ['series', 'movies', 'episodes']
        historyPrefixes = ['(Cartoon/Anime)', '(Movie)', '(Episode)']
        
        searchPath = URL_PATHS['search']
        
        historyItems = tuple(
            (
                buildURL({
                    'query': itemQuery,
                    'searchType': historyTypeNames[itemType],
                    'path': searchPath,                    
                    'section': 'ALL',
                    'action': 'actionCatalogSection'                    
                }),
                xbmcgui.ListItem('[B]%s[/B] "%s"' % (historyPrefixes[itemType], itemQuery)),
                True
            )
            for itemType, itemQuery in (
                (int(itemString[0]), itemString[1:]) for itemString in history
            )
        )
        clearHistoryItem = (
            buildURL({'action': 'actionSearchHistoryClear'}), xbmcgui.ListItem('[B]Clear History...[/B]'), False
        )           
        xbmcplugin.addDirectoryItems(PLUGIN_ID, (clearHistoryItem,) + historyItems)
    else:
        xbmcplugin.addDirectoryItem(PLUGIN_ID, '', xbmcgui.ListItem('(No History)'), isFolder=False)
    xbmcplugin.endOfDirectory(PLUGIN_ID)
    
    
def actionSearchHistoryClear(params):
    dialog = xbmcgui.Dialog()
    if dialog.yesno('Clear Search History', 'Are you sure?'):
        ADDON.setSetting('searchHistory', '')
        dialog.notification('Watchnixtoons2', 'Search history cleared', xbmcgui.NOTIFICATION_INFO, 3000, False)
        # Show the search menu afterwards.
        xbmc.executebuiltin('Container.Update(' + PLUGIN_URL + '?action=actionSearchMenu,replace)')


# A sub menu, lists the genre categories in the genre search.
def actionGenresMenu(params):
    r = requestHelper(BASEURL_MOBILE + URL_PATHS['genre'])
    html = r.text

    dataStartIndex = html.find('ui-listview-z')
    if dataStartIndex == -1:
        raise Exception('Genres list scrape fail')

    xbmcplugin.addDirectoryItems(
        PLUGIN_ID,
        tuple(
            (
                buildURL({'action': 'actionCatalogMenu', 'path': match.group(1), 'searchType': 'genres'}),
                xbmcgui.ListItem(match.group(2)),
                True
            )
            for match in re.finditer('''<a.*?"(.*?)".*?>(.*?)</''', html[dataStartIndex : html.rfind('button')])
        )
    )
    xbmcplugin.endOfDirectory(PLUGIN_ID)


def actionTraktMenu(params):
    instance = SimpleTrakt.getInstance()
    if instance.ensureAuthorized(ADDON):

        def _traktMenuItemsGen():
            traktIconDict = {'icon': ADDON_TRAKT_ICON, 'thumb': ADDON_TRAKT_ICON, 'poster': ADDON_TRAKT_ICON}
            for listName, listURL, listDescription in instance.getUserLists(ADDON):
                item = xbmcgui.ListItem(listName)
                item.setArt(traktIconDict)
                item.setInfo('video', {'title': listName, 'plot': listDescription})
                yield (
                    buildURL({'action': 'actionTraktList', 'listURL': listURL}),
                    item,
                    True
                )

        xbmcplugin.addDirectoryItems(PLUGIN_ID, tuple(_traktMenuItemsGen()))
        xbmcplugin.endOfDirectory(PLUGIN_ID) # Only finish the directory if the user is authorized it.


def actionTraktList(params):
    instance = SimpleTrakt.getInstance()
    if instance.ensureAuthorized(ADDON):

        def _traktListItemsGen():
            traktIconDict = {'icon': ADDON_TRAKT_ICON, 'thumb': ADDON_TRAKT_ICON, 'poster': ADDON_TRAKT_ICON}
            for itemName, overview, searchType, query in sorted(instance.getListItems(params['listURL'], ADDON)):
                item = xbmcgui.ListItem(itemName)
                item.setInfo('video', {'title': itemName, 'plot': overview})
                item.setArt(traktIconDict)
                yield (
                    # Trakt items will lead straight to a show name search.
                    buildURL(
                        {
                            'action': 'actionCatalogMenu',
                            'path': URL_PATHS['search'],
                            'query': query,
                            'searchType': searchType,
                        }
                    ),
                    item,
                    True
                )

        xbmcplugin.addDirectoryItems(PLUGIN_ID, tuple(_traktListItemsGen()))
    xbmcplugin.endOfDirectory(PLUGIN_ID)


def actionClearTrakt(params):
    if 'watchnixtoons2' in xbmc.getInfoLabel('Container.PluginName'):
        xbmc.executebuiltin('Dialog.Close(all)')

    # Kinda buggy behavior.
    # Need to wait a bit and recreate the xbmcaddon.Addon() reference, otherwise the settings
    # don't seem to be changed.
    # See https://forum.kodi.tv/showthread.php?tid=290353&pid=2425543#pid2425543
    global ADDON
    xbmc.sleep(500)
    if SimpleTrakt.clearTokens(ADDON):
        xbmcgui.Dialog().notification('Watchnixtoons2', 'Trakt tokens cleared', xbmcgui.NOTIFICATION_INFO, 3500, False)
    else:
        xbmcgui.Dialog().notification(
            'Watchnixtoons2', 'Trakt tokens already cleared', xbmcgui.NOTIFICATION_INFO, 3500, False
        )
    ADDON = xbmcaddon.Addon()


def actionShowSettings(params):
    # Modal dialog, so the program won't continue from this point until user closes\confirms it.
    ADDON.openSettings()

    # So right after it is a good time to update any settings globals.

    global ADDON_SHOW_CATALOG
    ADDON_SHOW_CATALOG = ADDON.getSetting('showCatalog') == 'true'

    global ADDON_LATEST_DATE
    # Set the catalog to be reloaded in case the user changed the "Order 'Latest Releases' By Date" setting.
    newLatestDate = ADDON.getSetting('useLatestDate') == 'true'
    if ADDON_LATEST_DATE != newLatestDate and URL_PATHS['latest'] in getRawWindowProperty(PROPERTY_CATALOG_PATH):
        setRawWindowProperty(PROPERTY_CATALOG_PATH, '')
    ADDON_LATEST_DATE = newLatestDate

    global ADDON_LATEST_THUMBS
    ADDON_LATEST_THUMBS = ADDON.getSetting('showLatestThumbs') == 'true'


def actionShowInfo(params):
    xbmcgui.Dialog().notification('Watchnixtoons2', 'Requesting info...', ADDON_ICON, 2000, False)

    # Get the desktop page for the item, whatever it is.
    url = params['url']
    r = requestHelper(url.replace('https://m.', 'https://www.', 1) if url.startswith('http') else BASEURL + url)
    html = r.text

    stringStartIndex = html.find('og:image" content="')
    if stringStartIndex != -1:
        thumb = BASEURL + html[stringStartIndex+19 : html.find('"', stringStartIndex+19)] # 19 = len('og:image" content="')
    else:
        thumb = ''
        xbmc.log('WatchNixtoons2 > Could not find thumbnail metadata (' + url + ')', xbmc.LOGWARNING)

    # We don't know if it's a show page (which has a list of episodes) or movie/OVA/episode page (which
    # has the video player element). Find out what it is.
    plot = ''
    if 'cat-img-desc' in html:
        # It's a show page.
        stringStartIndex = html.find('iltext">') + 8
        if stringStartIndex != 7:
            if html.find('</div', stringStartIndex) > 0: # Sometimes the description is empty.
                match = re.search('p>(.*?)</p', html[stringStartIndex:], re.DOTALL)
                if match:
                    plot = unescapeHTMLText(
                        match.group(1).replace('<p>', '').replace('</p>', '\n').replace('<br />', '\n').strip()
                    )
    else:
        # Assume it's a video player page.
        stringStartIndex = html.find('iltext"')
        if stringStartIndex != 7:
            match = re.search('/b>(.*?)<span', html[stringStartIndex:], re.DOTALL)
            if match:
                plot = unescapeHTMLText(
                    match.group(1).replace('<p>', '').replace('</p>', '\n').replace('<br />', '\n').strip()
                )

    # Old way, using Kodi's info screen on a new ListItem:
    #tempItem.setInfo(
    #    'video', {'mediatype': 'video', 'tvshowtitle': title, 'title': title, 'plot': plot, 'description': plot}
    #)
    #xbmcgui.Dialog().info(tempItem)
    #xbmcplugin.endOfDirectory(int(sys.argv[1]))

    # New way, using a persistent property holding a dictionary, and refreshing the directory listing.
    oldParams = dict(parse_qsl(params['oldParams']))
    if plot or thumb:
        infoItems = getWindowProperty(PROPERTY_INFO_ITEMS) or { }
        if thumb:
            thumb += getThumbnailHeaders()
        infoItems[url] = (plot, (thumb or 'DefaultVideo.png'))
        setWindowProperty(PROPERTY_INFO_ITEMS, infoItems)
    xbmc.executebuiltin('Container.Update(' + PLUGIN_URL + '?' + params['oldParams'] + ',replace)')


def unescapeHTMLText(text):
    text = text.encode('utf-8') if isinstance(text, unicode) else unicode(text, errors='ignore').encode('utf-8')
    # Unescape HTML entities.
    if r'&#' in text:
        # Strings found by regex-searching on all lists in the source website. It's very likely to only be these.
        return text.replace(r'&#8216;', '‘').replace(r'&#8221;', '”').replace(r'&#8211;', '–').replace(r'&#038;', '&')\
        .replace(r'&#8217;', '’').replace(r'&#8220;', '“').replace(r'&#8230;', '…').replace(r'&#160;', ' ')\
        .replace(r'&amp;', '&')
    else:
        return text.replace(r'&amp;', '&')


def getTitleInfo(unescapedTitle):
    # We need to interpret the full title of each episode's link's string
    # for information like episode number, season and show title.
    season = None
    episode = None
    multiPart = None
    showTitle = unescapedTitle
    episodeTitle = ''

    seasonIndex = unescapedTitle.find('Season ') # 7 characters long.
    if seasonIndex != -1:
        season = unescapedTitle[seasonIndex+7 : unescapedTitle.find(' ', seasonIndex+7)]
        showTitle = unescapedTitle[:seasonIndex].strip()

    episodeIndex = unescapedTitle.find(' Episode ') # 9 characters long.
    if episodeIndex != -1:
        spaceIndex = unescapedTitle.find(' ', episodeIndex+9)
        if spaceIndex > episodeIndex:
            episodeSplit = unescapedTitle[episodeIndex+9 : spaceIndex].split('-') # For multipart episodes, like "42-43".
            episode = episodeSplit[0]
            multiPart = episodeSplit[1] if len(episodeSplit) > 1 else None

            englishIndex = unescapedTitle.rfind(' English', spaceIndex)
            if englishIndex != -1:
                episodeTitle = unescapedTitle[spaceIndex+1 : englishIndex]
            else:
                episodeTitle = unescapedTitle[spaceIndex+1:]
            # Safeguard for when season 1 is ocasionally omitted in the title.
            if not season:
                season = '1'

    if episode:
        return (showTitle[:episodeIndex], season, episode, multiPart, episodeTitle.strip(' /'))
    else:
        englishIndex = unescapedTitle.rfind(' English')
        if englishIndex != -1:
            return (unescapedTitle[:englishIndex], None, None, None, '')
        else:
            return (unescapedTitle, None, None, None, '')


def makeListItem(title, url, artDict, plot, isFolder, isSpecial, oldParams):
    unescapedTitle = unescapeHTMLText(title)
    item = xbmcgui.ListItem(unescapedTitle)
    isPlayable = False

    if not (isFolder or isSpecial):
        title, season, episode, multiPart, episodeTitle = getTitleInfo(unescapedTitle)
        # Playable content.
        isPlayable = True
        itemInfo = {
            'mediatype': 'episode' if episode else 'tvshow', 'tvshowtitle': title, 'title': episodeTitle, 'plot': plot
        }
        if episode and episode.isdigit():
            itemInfo['season'] = int(season) if season.isdigit() else -1
            itemInfo['episode'] = int(episode)
        item.setInfo('video', itemInfo)
    elif isSpecial:
        isPlayable = True
        item.setInfo('video', {'mediatype': 'movie', 'title': unescapedTitle, 'plot': plot})
    else:
        item.setInfo('video', {'mediatype': 'tvshow', 'title': unescapedTitle, 'plot': plot})

    if artDict:
        item.setArt(artDict)

    # Add the context menu items, if necessary.
    contextMenuList = None
    if oldParams:
        contextMenuList = [
            (
                'Show Information',
                'RunPlugin('+PLUGIN_URL+'?action=actionShowInfo&url='+quote_plus(url)+'&oldParams='+quote_plus(urlencode(oldParams))+')'
            )
        ]
    if isPlayable:
        item.setProperty('IsPlayable', 'true') # Allows the checkmark to be placed on watched episodes.
        playChaptersItem = (
            'Play Chapters',
            'PlayMedia('+PLUGIN_URL+'?action=actionResolve&url='+quote_plus(url)+'&playChapters=1)'
        )
        if contextMenuList:
            contextMenuList.append(playChaptersItem)
        else:
            contextMenuList = [playChaptersItem]
    if contextMenuList:
        item.addContextMenuItems(contextMenuList)

    return item


# Variant of the 'makeListItem()' function that tries to format the item label using the season and episode.
def makeListItemClean(title, url, artDict, plot, isFolder, isSpecial, oldParams):
    unescapedTitle = unescapeHTMLText(title)
    isPlayable = False

    if isFolder or isSpecial:
        item = xbmcgui.ListItem(unescapedTitle)
        if isSpecial:
            isPlayable = True
            item.setInfo('video', {'mediatype': 'video', 'title': unescapedTitle})
    else:
        title, season, episode, multiPart, episodeTitle = getTitleInfo(unescapedTitle)
        if episode and episode.isdigit():
            # The clean episode label will have this format: "SxEE Episode Name", with S and EE standing for digits.
            item = xbmcgui.ListItem(
                '[B]' + season + 'x' + episode.zfill(2) + ('-' + multiPart if multiPart else '') + '[/B] '
                + (episodeTitle or title)
            )
            itemInfo = {
                'mediatype': 'episode',
                'tvshowtitle': title,
                'title': title,
                'plot': plot,
                'season': int(season) if season.isdigit() else -1,
                'episode': int(episode)
            }
        else:
            item = xbmcgui.ListItem(title)
            itemInfo = {'mediatype': 'tvshow', 'tvshowtitle': title, 'title': title, 'plot': plot}
        item.setInfo('video', itemInfo)
        isPlayable = True

    if artDict:
        item.setArt(artDict)

    # Add the context menu items, if necessary.
    contextMenuList = None
    if oldParams:
        contextMenuList = [
            (
                'Show Information',
                'RunPlugin('+PLUGIN_URL+'?action=actionShowInfo&url='+quote_plus(url)+'&oldParams='+quote_plus(urlencode(oldParams))+')'
            )
        ]
    if isPlayable:
        item.setProperty('IsPlayable', 'true') # Allows the checkmark to be placed on watched episodes.
        playChaptersItem = (
            'Play Chapters',
            'PlayMedia('+PLUGIN_URL+'?action=actionResolve&url='+quote_plus(url)+'&playChapters=1)'
        )
        if contextMenuList:
            contextMenuList.append(playChaptersItem)
        else:
            contextMenuList = [playChaptersItem]
    if contextMenuList:
        item.addContextMenuItems(contextMenuList)

    return item


'''
(1. The catalog is a dictionary of lists, used to store data between add-on states to make xbmcgui.ListItems:
{
    (2. Sections, as in alphabet sections of items, A, B, C, D, E, F etc., each section holds a list of items.)
    A: (
        (item, item, item, ...) (3. Items, each item is a pair of <a> properties: (a.string, a['href']).)
    )
    B: (...)
    C: (...)
}
'''

# Manually sorts items from an iterable into an alphabetised catalog.
# Iterable contains (URL, name) pairs that might refer to a series, episode, ova or movie.
def catalogFromIterable(iterable):
    catalog = {key: [ ] for key in ascii_uppercase}
    miscSection = catalog['#'] = [ ]
    for item in iterable:
        key = item[1][0].upper()
        if key in catalog:
            catalog[key].append(item)
        else:
            miscSection.append(item)
    return catalog


def makeLatestCatalog(params):
    # Returns a list of links from the "Latest 50 Releases" area but for mobile.
    r = requestHelper(BASEURL_MOBILE) # Path unused, data is already on the homepage.
    html = r.text

    dataStartIndex = html.find('vList')
    if dataStartIndex == -1:
        raise Exception('Latest catalog scrape fail')

    thumbHeaders = getThumbnailHeaders()
        
    if ADDON_LATEST_DATE:
        # Make the catalog dict only have a single section, "LATEST", with items listed as they are.
        # This will cause "actionCatalogMenu" to show this single section directly, with no alphabet categories.
        return {
            'LATEST': tuple(
                (match.group(1), match.group(3), match.group(2)+thumbHeaders)
                for match in re.finditer(
                    '''<a.*?"(.*?)".*?img src="(.*?)".*?div.*?div>(.*?)</div''', html[dataStartIndex : html.find('/ol')]
                )
            )
        }
    else:
        return catalogFromIterable(
            (match.group(1), match.group(3), match.group(2)+thumbHeaders)
            for match in re.finditer(
                '''<a.*?"(.*?)".*?img src="(.*?)".*?div.*?div>(.*?)</div''', html[dataStartIndex : html.find('/ol')]
            )
        )


def makePopularCatalog(params):
    # The "Popular & Ongoing" page of the mobile version is more complete.
    r = requestHelper(BASEURL_MOBILE + params['path'])
    html = r.text

    dataStartIndex = html.find('ui-listview-z')
    if dataStartIndex == -1:
        raise Exception('Popular catalog scrape fail: ' + params['path'])

    return catalogFromIterable(
        match.groups()
        for match in re.finditer(
            '''<a.*?href="(.*?)".*?>(.*?)</''', html[dataStartIndex : html.rfind('button')]
        )
    )


def makeSeriesSearchCatalog(params):
    r = requestHelper(
        BASEURL+'/search', data={'catara': params['query'], 'konuara': 'series'}, extraHeaders={'Referer': BASEURL+'/'})
    html = r.text

    dataStartIndex = html.find('submit')
    if dataStartIndex == -1:
        raise Exception('Series search scrape fail: ' + params['query'])

    return catalogFromIterable(
        match.groups()
        for match in re.finditer(
            '''aramadabaslik.*?<a.*?"(.*?)".*?>(.*?)</''',
            html[dataStartIndex : html.find('cizgiyazisi')],
            re.DOTALL
        )
    )


def makeMoviesSearchCatalog(params):
    # Try a movie category search (same code as in 'makeGenericCatalog()').
    r = requestHelper(BASEURL + URL_PATHS['movies'])
    html = r.text

    dataStartIndex = html.find(r'ddmcc">')
    if dataStartIndex == -1:
        raise Exception('Movies search scrape fail: ' + params['query'])

    lowerQuery = params['query'].lower()

    return catalogFromIterable(
        match.groups()
        for match in re.finditer(
            '''<a.*?"(.*?)".*?>(.*?)</''', html[dataStartIndex : html.find(r'/ul></ul')]
        )
        if lowerQuery in match.group(2).lower()
    )


def makeEpisodesSearchCatalog(params):
    r = requestHelper(
        BASEURL+'/search', data={'catara': params['query'], 'konuara': 'episodes'}, extraHeaders={'Referer': BASEURL+'/'}
    )
    html = r.text

    dataStartIndex = html.find('submit')
    if dataStartIndex == -1:
        raise Exception('Episode search scrape fail: ' + params['query'])

    
    return catalogFromIterable(
        match.groups()
        for match in re.finditer(
            '''<a.*?href="(.*?)".*?>(.*?)</''',
            html[dataStartIndex : html.find('cizgiyazisi')],
            re.DOTALL
        )
    )


def makeSearchCatalog(params):
    searchType = params.get('searchType', 'series')
    if searchType == 'series':
        return makeSeriesSearchCatalog(params)
    elif searchType == 'movies':
        return makeMoviesSearchCatalog(params)
    else:
        return makeEpisodesSearchCatalog(params)


def makeGenericCatalog(params):
    # The movies path is missing some items when scraped from BASEURL_MOBILE, so we use the BASEURL
    # (full website) in here.
    r = requestHelper(BASEURL + params['path'])
    html = r.text

    dataStartIndex = html.find(r'ddmcc">')
    if dataStartIndex == -1:
        raise Exception('Generic catalog scrape fail: ' + params['path'])

    # Account for genre searches having a slightly different end pattern.
    dataEndPattern = r'/ul></div></div' if 'search-by-genre' in params['path'] else r'/ul></ul'
    return catalogFromIterable(
        match.groups()
        for match in re.finditer(
            '''<li><a.*?"(.*?)".*?>(.*?)</''', html[dataStartIndex : html.find(dataEndPattern)]
        )
    )


# Retrieves the catalog from a persistent XBMC window property between different add-on
# directories, or recreates the catalog based on one of the catalog functions.
def getCatalogProperty(params):
    path = params['path']

    def _rebuildCatalog():
        func = CATALOG_FUNCS.get(path, makeGenericCatalog)
        catalog = func(params)
        setWindowProperty(PROPERTY_CATALOG, catalog)
        if 'query' in params:
            # For searches, store the query and search type in the catalog path so we can identify
            # this particular search attempt.
            setRawWindowProperty(PROPERTY_CATALOG_PATH, path + params['query'] + params['searchType'])
        else:
            setRawWindowProperty(PROPERTY_CATALOG_PATH, path)
        setRawWindowProperty(PROPERTY_INFO_ITEMS, '') # Clear any previous info.
        return catalog

    # If these properties are empty (like when coming in from a favourites menu), or if
    # a different catalog (a different URL path) is stored in this property, then reload it.
    currentPath = getRawWindowProperty(PROPERTY_CATALOG_PATH)
    if (
        # "If we're coming in from a search and the search query and type are different, or if we're not
        # coming in from a search and the paths are simply different, rebuild the catalog."
        ('query' in params and (params['query'] not in currentPath or params['searchType'] not in currentPath))
        or ('query' not in params and currentPath != path)
    ):
        catalog = _rebuildCatalog()
    else:
        catalog = getWindowProperty(PROPERTY_CATALOG)
        if not catalog:
            catalog = _rebuildCatalog()
    return catalog


def actionResolve(params):
    # Needs to be the BASEURL domain to get multiple video qualities.
    url = params['url']
    # Sanitize the URL since on some occasions it's a path instead of full address.
    url = url if url.startswith('http') else (BASEURL + (url if url.startswith('/') else '/' + url))
    r = requestHelper(url.replace('watchcartoononline.io', 'wcostream.com', 1)) # New domain safety replace.
    content = r.content

    def _decodeSource(content, startIndex):
        subContent = content[startIndex:]
        chars = re.search(b' = \[(".*?")\];', subContent).group(1)
        spread = int(re.search(r' - (\d+)\)\; }', subContent).group(1))
        iframe = ''
        for char in chars.replace('"', '').split(','):
            char = ''.join(d for d in b64decode(char) if d.isdigit())
            char = chr(int(char) - spread)
            iframe += char
        return BASEURL + re.search(r'src="(.*?)"', iframe).group(1)

    # On rare cases an episode might have several "chapters", which are video players on the page.
    embedURLPattern = b'<meta itemprop="embedURL'
    embedURLIndex = content.find(embedURLPattern)
    if 'playChapters' in params or ADDON.getSetting('chapterEpisodes') == 'true':
        # Multi-chapter episode found (or, multiple "embedURL" statements found).
        # Extract all chapters from the page.
        currentPlayerIndex = embedURLIndex
        dataIndices = [ ]
        while currentPlayerIndex != -1:
            dataIndices.append(currentPlayerIndex)
            currentPlayerIndex = content.find(embedURLPattern, currentPlayerIndex + 24)

        # If more than one "embedURL" statement found, make a selection dialog and call them "chapters".
        if len(dataIndices) > 1:
            selectedIndex = xbmcgui.Dialog().select(
                'Select Chapter', ['Chapter '+str(n) for n in xrange(1, len(dataIndices)+1)]
            )
        else:
            selectedIndex = 0
        
        if selectedIndex != -1:
            embedURL = _decodeSource(content, dataIndices[selectedIndex])
        else:
            return # User cancelled the chapter selection.
    else:
        # Normal / single-chapter episode.
        embedURL = _decodeSource(content, content.find(b' = ["', embedURLIndex))
        if 'playChapters' in params: # User asked to play multiple chapters, but only one chapter/video player found.
            xbmcgui.Dialog().notification('Watchnixtoons2', 'Only 1 chapter found...', ADDON_ICON, 2000, False)

    # Request the embedded player page.
    r2 = requestHelper(unescapeHTMLText(embedURL)) # Sometimes a '&#038;' symbol is present in this URL.
    html = r2.text

    # Find the stream URLs.
    if 'getvid?evid' in html:
        # Query-style stream getting.
        sourceURL = re.search(b'get\("(.*?)"', html, re.DOTALL).group(1)

        # Inline code similar to 'requestHelper()'.
        # The User-Agent for this next request is somehow encoded into the media tokens, so we make sure to use
        # the EXACT SAME value later, when playing the media, or else we get a HTTP 404 / 500 error.
        r3 = requestHelper(
            BASEURL + sourceURL,
            data = None,
            extraHeaders = {
                'User-Agent': WNT2_USER_AGENT, 'Accept': '*/*', 'Referer': embedURL, 'X-Requested-With': 'XMLHttpRequest'
            }
        )
        if not r3.ok:
            raise Exception('Sources XMLHttpRequest request failed')
        jsonData = r3.json()

        # Only two qualities are ever available: 480p ("SD") and 720p ("HD").
        sourceURLs = [ ]
        sdToken = jsonData.get('enc', '')
        hdToken = jsonData.get('hd', '')
        sourceBaseURL = jsonData.get('server', '') + '/getvid?evid='
        if sdToken:
            sourceURLs.append(('480 (SD)', sourceBaseURL + sdToken)) # Order the items as (LABEL, URL).
        if hdToken:
            sourceURLs.append(('720 (HD)', sourceBaseURL + hdToken))
        # Use the same backup stream method as the source: cdn domain + SD stream.
        backupURL = jsonData.get('cdn', '') + '/getvid?evid=' + (sdToken or hdToken)
    else:
        # Alternative video player page, with plain stream links in the JWPlayer javascript.
        sourcesBlock = re.search('sources:\s*?\[(.*?)\]', html, re.DOTALL).group(1)
        streamPattern = re.compile('\{\s*?file:\s*?"(.*?)"(?:,\s*?label:\s*?"(.*?)")?')
        sourceURLs = [
            # Order the items as (LABEL (or empty string), URL).
            (sourceMatch.group(2), sourceMatch.group(1))
            for sourceMatch in streamPattern.finditer(sourcesBlock)
        ]
        # Use the backup link in the 'onError' handler of the 'jw' player.
        backupMatch = streamPattern.search(html[html.find(b'jw.onError'):])
        backupURL = backupMatch.group(1) if backupMatch else ''

    mediaURL = None
    if len(sourceURLs) == 1: # Only one quality available.
        mediaURL = sourceURLs[0][1]
    elif len(sourceURLs) > 0:
        playbackMethod = ADDON.getSetting('playbackMethod')
        if playbackMethod == '0': # Select quality.
                selectedIndex = xbmcgui.Dialog().select(
                    'Select Quality', [(sourceItem[0] or '?') for sourceItem in sourceURLs]
                )
                if selectedIndex != -1:
                    mediaURL = sourceURLs[selectedIndex][1]
        else: # Auto-play user choice.
            sortedSources = sorted(sourceURLs)
            mediaURL = sortedSources[-1][1] if playbackMethod == '1' else sortedSources[0][1]

    if mediaURL:
        # Kodi headers for playing web streamed media.
        global MEDIA_HEADERS
        if not MEDIA_HEADERS:
            MEDIA_HEADERS = {
                'User-Agent': WNT2_USER_AGENT,
                'Accept': 'video/webm,video/ogg,video/*;q=0.9,application/ogg;q=0.7,audio/*;q=0.6,*/*;q=0.5',
                'Connection': 'keep-alive',
                'Referer': BASEURL + '/'
            }

        # Try to un-redirect the chosen media URL.
        # If it fails, try to un-resolve the backup URL. If not even the backup URL is working, abort playing.
        mediaHead = solveMediaRedirect(mediaURL, MEDIA_HEADERS)
        if not mediaHead:
            mediaHead = solveMediaRedirect(backupURL, MEDIA_HEADERS)
        if not mediaHead:
            return xbmcplugin.setResolvedUrl(PLUGIN_ID, False, xbmcgui.ListItem())

        # Need to use the exact same ListItem name & infolabels when playing or else Kodi replaces that item
        # in the UI listing.
        item = xbmcgui.ListItem(xbmc.getInfoLabel('ListItem.Label'))
        item.setPath(mediaHead.url + '|' + '&'.join(key+'='+quote_plus(val) for key, val in MEDIA_HEADERS.iteritems()))
        item.setMimeType(mediaHead.headers.get('Content-Type', 'video/mp4')) # Avoids Kodi's MIME request.
        episodeString = xbmc.getInfoLabel('ListItem.Episode')
        if episodeString != '' and episodeString != '-1':
            item.setInfo('video',
                {
                    'tvshowtitle': xbmc.getInfoLabel('ListItem.TVShowTitle'),
                    'title': xbmc.getInfoLabel('ListItem.Title'),
                    'season': int(xbmc.getInfoLabel('ListItem.Season')),
                    'episode': int(episodeString),
                    'plot': xbmc.getInfoLabel('ListItem.Plot'),
                    'mediatype': 'episode'
                }
            )
        else:
            item.setInfo('video',
                {
                    'title': xbmc.getInfoLabel('ListItem.Title'),
                    'plot': xbmc.getInfoLabel('ListItem.Plot'),
                    'mediatype': 'movie'
                }
            )
        #xbmc.Player().play(listitem=item) # Alternative play method, lets you extend the Player class with your own.
        xbmcplugin.setResolvedUrl(PLUGIN_ID, True, item)
    else:
        # Failed. No source found, or the user didn't select one from the dialog.
        xbmcplugin.setResolvedUrl(PLUGIN_ID, False, xbmcgui.ListItem())


def buildURL(query):
    '''
    Helper function to build a Kodi xbmcgui.ListItem URL.
    :param query: Dictionary of url parameters to put in the URL.
    :returns: A formatted and urlencoded URL string.
    '''
    return (PLUGIN_URL + '?' + urlencode({k: v.encode('utf-8') if isinstance(v, unicode)
                                         else unicode(v, errors='ignore').encode('utf-8')
                                         for k, v in query.iteritems()}))


def setViewMode():
    if ADDON.getSetting('useViewMode') == 'true':
        viewModeID = ADDON.getSetting('viewModeID')
        if viewModeID.isdigit():
            xbmc.executebuiltin('Container.SetViewMode(' + viewModeID + ')')


def xbmcDebug(*args):
    xbmc.log('WATCHNIXTOONS2 > '+' '.join((val if isinstance(val, str) else repr(val)) for val in args), xbmc.LOGWARNING)


def simpleRequest(url, requestFunc, headers):
    return requestFunc(url, headers=headers, verify=False, timeout=10)


# Thumbnail HTTP headers for Kodi to use when grabbing thumbnail images.    
def getThumbnailHeaders():    
    # Original code:
    #return (
    #    '|User-Agent='+quote_plus(WNT2_USER_AGENT)
    #    + '&Accept='+quote_plus('image/webp,*/*')
    #    + '&Referer='+quote_plus(BASEURL_MOBILE+'/')
    #)    
    cookieProperty = getRawWindowProperty(PROPERTY_SESSION_COOKIE)
    cookies = ('&Cookie=' + quote_plus(cookieProperty)) if cookieProperty else ''
    
    # Since it's a constant value, it can be precomputed.        
    return '|User-Agent=Mozilla%2F5.0+%28compatible%3B+WatchNixtoons2%2F0.3.7%3B' \
    '+%2Bhttps%3A%2F%2Fgithub.com%2Fdoko-desuka%2Fplugin.video.watchnixtoons2%29' \
    '&Accept=image%2Fwebp%2C%2A%2F%2A&Referer=https%3A%2F%2Fm.wcostream.com%2F' + cookies

    

def solveMediaRedirect(url, headers):
    # Use HEAD requests to fulfill possible 302 redirections.
    # Return the final stream HEAD response.
    done = False
    while not done:
        try:
            mediaHead = simpleRequest(url, requests.head, headers)
            if 'Location' in mediaHead.headers:
                url = mediaHead.headers['Location'] # Change the URL to the redirected location and repeat the HEAD.
            else:
                mediaHead.raise_for_status()
                return mediaHead # Return the response.
        except:
            return None # Return nothing on failure.


def requestHelper(url, data=None, extraHeaders=None):
    myHeaders = {
        'User-Agent': WNT2_USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml,application/json;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'DNT': '1'
    }
    if extraHeaders:
        myHeaders.update(extraHeaders)

    # At the moment it's a single response cookie, "__cfduid". Other cookies are set w/ Javascript by ads.
    cookieProperty = getRawWindowProperty(PROPERTY_SESSION_COOKIE)
    if cookieProperty:
        cookieDict = dict(pair.split('=') for pair in cookieProperty.split('; '))
    else:
        cookieDict = None

    startTime = time()

    if data:
        response = requests.post(url, data=data, headers=myHeaders, verify=False, cookies=cookieDict, timeout=10)
    else:
        response = requests.get(url, headers=myHeaders, verify=False, cookies=cookieDict, timeout=10)

    # Store the session cookie(s), if any.
    if not cookieProperty and response.cookies:
        setRawWindowProperty(
            PROPERTY_SESSION_COOKIE, '; '.join(pair[0]+'='+pair[1] for pair in response.cookies.get_dict().iteritems())
        )

    elapsed = time() - startTime
    if elapsed < 1.5:
        sleep(1.5 - elapsed)

    return response


#def getRandomUserAgent():
#    # Random user-agent logic. Thanks to http://edmundmartin.com/random-user-agent-requests-python/
#    from random import choice
#    desktop_agents = (
#        'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.99 Safari/537.36',
#        'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.99 Safari/537.36',
#        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.99 Safari/537.36',
#        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_1) AppleWebKit/602.2.14 (KHTML, like Gecko) Version/10.0.1 Safari/602.2.14',
#        'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.71 Safari/537.36',
#        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.98 Safari/537.36',
#        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.98 Safari/537.36',
#        'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.71 Safari/537.36',
#        'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.99 Safari/537.36',
#        'Mozilla/5.0 (Windows NT 10.0; WOW64; rv:50.0) Gecko/20100101 Firefox/50.0'
#    )
#    return choice(desktop_agents)


# Defined after all the functions exist.
CATALOG_FUNCS = {
    URL_PATHS['latest']: makeLatestCatalog,
    URL_PATHS['popular']: makePopularCatalog,
    URL_PATHS['search']: makeSearchCatalog
}


def main():
    '''
    Main add-on routing function, calls a certain action (function).
    The 'action' parameter is the direct name of the function.
    '''
    params = dict(parse_qsl(sys.argv[2][1:], keep_blank_values=True))
    globals()[params.get('action', 'actionMenu')](params) # Defaults to 'actionMenu()'.
