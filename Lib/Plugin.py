# -*- coding: utf-8 -*-
import re
import sys
import json
import requests

from itertools import chain
from base64 import b64decode
from urlparse import parse_qsl
from HTMLParser import HTMLParser
from string import ascii_uppercase
from urllib import quote_plus, urlencode
from bs4 import BeautifulSoup, SoupStrainer

import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin

from Lib.Common import (
    getWindowProperty,
    setWindowProperty,
    getRawWindowProperty,
    setRawWindowProperty
)
from Lib.SimpleTrakt import SimpleTrakt

# Disable urllib3's "InsecureRequestWarning: Unverified HTTPS request is being made" warnings
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


PLUGIN_ID = int(sys.argv[1])
PLUGIN_URL = sys.argv[0]

BASEURL = 'https://www.watchcartoononline.io'
BASEURL_MOBILE = 'https://m.watchcartoononline.io'
BASEURL_IMAGES = BASEURL + '/wp-content/catimg/'

PROPERTY_CATALOG_PATH = 'wnt2.catalogPath'
PROPERTY_CATALOG = 'wnt2.catalog'
PROPERTY_EPISODE_LIST_URL = 'wnt2.listURL'
PROPERTY_EPISODE_LIST_DATA = 'wnt2.listData'

HTML_PARSER = HTMLParser()
IGNORED_WORDS_LOWCASE = set(('english','subbed','dubbed'))

ADDON = xbmcaddon.Addon()
ADDON_SHOW_CATALOG = ADDON.getSetting('showCatalog') == 'true'
ADDON_ICON = ADDON.getAddonInfo('icon')
ADDON_ICON_DICT = {'icon': ADDON_ICON, 'thumb': ADDON_ICON, 'poster': ADDON_ICON}
ADDON_TRAKT_ICON = 'special://home/addons/plugin.video.watchnixtoons2/resources/traktIcon.png'

MEDIA_HEADERS = None # Initialized in 'actionResolve()'.

# Url paths: paths to parts of the website, to be added to the BASEURL / BASEURL_MOBILE urls.
# Also used to tell what kind of catalog is loaded in memory.
# In case they change in the future it'll be easier to modify in here.
URL_PATHS = {
    'latest': '/last-50-recent-release',
    'popular': '/ongoing-series',
    'dubbed': '/dubbed-anime-list',
    'cartoons': '/cartoon-list',
    'subbed': '/subbed-anime-list',
    'movies': '/movie-list',
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
            _menuItem('Popular & Ongoing Series', {'action': 'actionCatalogMenu', 'path': URL_PATHS['popular']}, 'mediumaquamarine'),
            _menuItem('Dubbed Anime', {'action': 'actionCatalogMenu', 'path': URL_PATHS['dubbed']}, 'lightgreen'),
            _menuItem('Cartoons', {'action': 'actionCatalogMenu', 'path': URL_PATHS['cartoons']}, 'lightgreen'),
            _menuItem('Subbed Anime', {'action': 'actionCatalogMenu', 'path': URL_PATHS['subbed']}, 'lightgreen'),
            _menuItem('Movies', {'action': 'actionCatalogMenu', 'path': URL_PATHS['movies']}, 'lightgreen'),
            _menuItem('OVA Series', {'action': 'actionCatalogMenu', 'path': URL_PATHS['ova']}, 'lightgreen'),
            _menuItem('Search', {'action': 'actionSearchMenu',  'path': ''}, 'lavender'),
            _menuItem('Settings', {'action': 'actionShowSettings','path': ''}, 'lavender')
        )
    )
    xbmcplugin.endOfDirectory(PLUGIN_ID)


def actionShowSettings(params):
    # Modal dialog, so the program won't continue from this point until user closes\confirms it.
    ADDON.openSettings()
    # So right after it is a good time to update any settings globals.
    global ADDON_SHOW_CATALOG
    ADDON_SHOW_CATALOG = ADDON.getSetting('showCatalog') == 'true'
    
    
def actionCatalogMenu(params):
    xbmcplugin.setContent(PLUGIN_ID, 'tvshows')
    catalog = getCatalogProperty(params)

    if ADDON_SHOW_CATALOG:
        sectionAll = (
            buildURL({'action': 'actionCatalogSection', 'path': params['path'], 'section': 'ALL'}),
            xbmcgui.ListItem('All'),
            True
        )
        listItems = tuple(
            (
                buildURL({'action': 'actionCatalogSection', 'path': params['path'], 'section': sectionName}),
                xbmcgui.ListItem(sectionName),
                True
            )
            for sectionName in sorted(catalog.iterkeys()) if len(catalog[sectionName])
        )
        if len(listItems):
            xbmcplugin.addDirectoryItems(PLUGIN_ID, (sectionAll,) + listItems)
        xbmcplugin.endOfDirectory(PLUGIN_ID)
        xbmc.executebuiltin('Container.SetViewMode(54)') # InfoWall mode, Estuary skin (the default skin).
    else:
        params['section'] = 'ALL'
        actionCatalogSection(params)
    


def actionCatalogSection(params):
    catalog = getCatalogProperty(params)

    path = params['path']
    if (
        path not in (URL_PATHS['ova'], URL_PATHS['movies'], URL_PATHS['latest'])
        or ('searchType' in params and params['searchType'] == 'series')
    ):
        xbmcplugin.setContent(PLUGIN_ID, 'tvshows')
        action = 'actionEpisodesMenu'
        isFolder = True
    else:
        xbmcplugin.setContent(PLUGIN_ID, 'episodes')
        # Special case for the OVA, movie and episode-search catalogs, they link to the video player pages already.
        action = 'actionResolve'
        isFolder = False

    thumb = params.get('thumb', ADDON_ICON)
    artDict = {'icon': thumb, 'thumb': thumb, 'poster': thumb} if thumb else None
    plot = params.get('plot', '')
        
    def _sectionItem(entry):
        return (
            buildURL({'action': action, 'url': entry[1]}),
            makeListItem(entry[0], artDict, plot, isFolder),
            isFolder
        )

    sectionName = params['section']
        
    if sectionName == 'ALL':
        listItems = (
            _sectionItem(item)
            for item in chain.from_iterable(catalog[sectionName] for sectionName in sorted(catalog.iterkeys()))
        )
    else:
        listItems = (_sectionItem(item) for item in catalog[sectionName])
        
    xbmcplugin.addSortMethod(PLUGIN_ID, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.addDirectoryItems(PLUGIN_ID, tuple(listItems))
    xbmcplugin.endOfDirectory(PLUGIN_ID)
    #xbmc.executebuiltin('Container.SetViewMode(54)') # Optionall use a grid layout (Estuary skin).

    
def actionEpisodesMenu(params):
    xbmcplugin.setContent(PLUGIN_ID, 'episodes')

    # Memory-cache the last episode list, to help when the user goes back and forth while watching
    # multiple episodes of the same show. This way only one web request is needed.
    lastListURL = getRawWindowProperty(PROPERTY_EPISODE_LIST_URL)
    if lastListURL and lastListURL == params['url']:
        listData = getWindowProperty(PROPERTY_EPISODE_LIST_DATA)
    else:
        r = requestHelper(params['url'].replace('www.', 'm.', 1)) # Show page for the mobile version of the website.
        soup = BeautifulSoup(r.content, 'html.parser', parse_only=SoupStrainer('div', {'class': 'main'}))
        # Try to scrape thumb and plot metadata from the show page.
        thumb = plot = ''
        div = soup.find('div', {'id': 'category_description'})
        if div:
            thumb = div.img['src'] if div.img else ''
            plot = div.p.string if div.p else ''
        # Episode list data: a list of two lists, one has the show thumb & plot data, the other has
        # the per-episode data.
        mainUL = soup.find('ul', {'class': 'ui-listview-z'})
        listData = (thumb, plot, tuple((a.string, a['href']) for a in mainUL.find_all('a')))
        setRawWindowProperty(PROPERTY_EPISODE_LIST_URL, params['url'])
        setWindowProperty(PROPERTY_EPISODE_LIST_DATA, listData)

    def _episodeItemsGen():
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        playlist.clear()

        thumb = listData[0]
        artDict = {'icon': thumb, 'thumb': thumb, 'poster': thumb} if thumb else None
        plot = listData[1]

        itemParams = {'action': 'actionResolve', 'url': None}
        listIter = iter(listData[2]) if ADDON.getSetting('reverseEpisodes')=='true' else reversed(listData[2])
        for title, URL in listIter:
            item = makeListItem(title, artDict, plot, isFolder=False)
            itemParams['url'] = URL
            itemURL = buildURL(itemParams)
            playlist.add(itemURL, item)
            yield (itemURL, item, False)

    xbmcplugin.addDirectoryItems(PLUGIN_ID, tuple(_episodeItemsGen()))
    xbmcplugin.endOfDirectory(PLUGIN_ID)    
    

# A sub menu, lists search options.
def actionSearchMenu(params):
    def _modalKeyboard(heading):
        kb = xbmc.Keyboard('', heading)
        kb.doModal()
        return kb.getText() if kb.isConfirmed() else ''

    if 'searchType' in params:
        query = _modalKeyboard(params['searchTitle'])
        if query:
            params['query'] = query
            params['section'] = 'ALL'
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
                buildURL({'action': 'actionTraktMenu', 'path': URL_PATHS['genre']}),
                xbmcgui.ListItem('[COLOR lavender][B]Search by Trakt List[/B][/COLOR]'),
                True
            )
        )
    )
    xbmcplugin.endOfDirectory(PLUGIN_ID)


# A sub menu, lists the genre categories in the genre search.
def actionGenresMenu(params):
    r = requestHelper(BASEURL_MOBILE + URL_PATHS['genre'])
    soup = BeautifulSoup(r.text, 'html.parser')
    mainDIV = soup.find('div', {'class': 'main'})

    xbmcplugin.addDirectoryItems(
        PLUGIN_ID,
        tuple(
            (
                buildURL({'action': 'actionCatalogMenu', 'path': URL_PATHS['genre'] + a['href'][a['href'].rfind('/'):]}),
                xbmcgui.ListItem(a.string),
                True
            )
            for a in mainDIV.ul.find_all('a')
        )
    )
    xbmcplugin.endOfDirectory(PLUGIN_ID)

    
def actionTraktMenu(params):
    instance = SimpleTrakt.getInstance()
    if instance.ensureAuthorized(ADDON):

        def _traktMenuItemsGen():
            traktIconDict = {'icon': ADDON_TRAKT_ICON, 'thumb': ADDON_TRAKT_ICON, 'poster': ADDON_TRAKT_ICON}
            for list in instance.getUserLists(ADDON):
                item = xbmcgui.ListItem(list['name'])
                item.setArt(traktIconDict)
                item.setInfo('video', {'title': list['name'], 'plot': list['description']})
                yield (
                    buildURL({'action': 'actionTraktList', 'traktList': str(list['ids']['trakt'])}),
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
            for itemName in sorted(instance.getListItems(params['traktList'], ADDON)):
                item = xbmcgui.ListItem(itemName)
                item.setArt(traktIconDict)
                yield (
                    # Trakt items will lead straight to a show name search.
                    buildURL(
                        {
                            'action': 'actionCatalogMenu',
                            'path': URL_PATHS['search'],
                            'query': itemName,
                            'searchType': 'series',
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


def getTitleInfo(unescapedTitle):
    # We need to interpret the full title of each episode's link's string
    # for information like episode number, season and show title.
    season = 0
    episode = 0
    showTitle = ''

    titleWords = unescapedTitle.split()
    for index, word in enumerate(titleWords):
        if word == 'Season':
            try:
                season = int(titleWords[index+1])
            except ValueError:
                pass
        elif word == 'Episode':
            try:
                episode = int(titleWords[index+1].split('-')[0]) # Sometimes it's more than one, like "42-43".
                if not season:
                    season = 1 # Season 1 is ocasionally omitted in the title.
            except:
                episode = 0
            break # The word 'Episode' is always put after the season and show title in the link strings.
        else:
            if not season and not episode and word.lower() not in IGNORED_WORDS_LOWCASE:
                showTitle += word + ' '
    return (showTitle.strip(), season, episode)


def makeListItem(title, artDict, plot, isFolder):
    unescapedTitle = HTML_PARSER.unescape(title.strip())
    title, season, episode  = getTitleInfo(unescapedTitle)

    item = xbmcgui.ListItem(unescapedTitle)
    if artDict:
        item.setArt(artDict)
    
    if not isFolder:
        item.setProperty('IsPlayable', 'true') # Allows the checkmark to be placed on watched episodes.
        itemInfo = {'mediatype': 'episode' if episode else 'tvshow', 'title': title, 'plot': plot}
        if episode:
            itemInfo.update({'season': season, 'episode': episode})
        item.setInfo('video', itemInfo)
        
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

# Manually splits items from an iterable returned by 'iterableFunc' into an alphabetised catalog.
# Iterable contains (a.string, a['href']) pairs which refer to a series, episode, ova or movie.
def catalogFromIterable(iterable):
    catalog = {key: [ ] for key in ascii_uppercase}
    miscSection = catalog['#'] = [ ]
    for item in iterable:
        catalog.get(item[0][0].upper(), miscSection).append(item)
    return catalog


def makeLatestCatalog(params):
    # Returns a list of links from the "Latest 50 Releases" area but for mobile.
    r = requestHelper(BASEURL_MOBILE) # Path unused, data is already on the homepage.
    mainOL = BeautifulSoup(r.content, 'html.parser', parse_only=SoupStrainer('ol', {'class': 'vList'}))
    return catalogFromIterable((li.a.text, li.a['href']) for li in mainOL.find_all('li'))


def makePopularCatalog(params):
    # The movies path is missing some items in BASEURL_MOBILE, so we use the BASEURL (full website) in here.
    r = requestHelper(BASEURL + params['path'])
    soup = BeautifulSoup(r.content, 'html.parser', parse_only=SoupStrainer('div', {'class': 'ddmcc'}))
    mainUL = soup.ul
    return catalogFromIterable((a.text, a['href']) for subUL in mainUL.find_all('ul') for a in subUL.find_all('a'))


def makeSearchCatalog(params):
    searchType = params.get('searchType', 'series')
    if searchType == 'series':
        return makeSeriesSearchCatalog(params)
    elif searchType == 'movies':
        return makeMoviesSearchCatalog(params)
    else:
        return makeEpisodesSearchCatalog(params)


def makeSeriesSearchCatalog(params):
    r = requestHelper(BASEURL + '/search', {'catara': params['query'], 'konuara': 'series'})
    # Shorthand '_class' parameter doesn't work on SoupStrainer...
    results = BeautifulSoup(r.content, 'html.parser', parse_only=SoupStrainer('div', {'class': 'cerceve'}))
    return catalogFromIterable((div.a.string, div.a['href'].replace(BASEURL, '')) for div in results)

        
def makeMoviesSearchCatalog(params):
    # Try a movie category search (same code as in 'makePopularCatalog()').
    r = requestHelper(BASEURL + URL_PATHS['movies'])
    soup = BeautifulSoup(r.content, 'html.parser', parse_only=SoupStrainer('div', {'class': 'ddmcc'}))
    lowerQuery = params['query'].lower()
    return catalogFromIterable((a.text, a['href']) for a in soup.ul.find_all('a') if lowerQuery in a.text.lower())


def makeEpisodesSearchCatalog(params):
    r = requestHelper(BASEURL + '/search', {'catara': params['query'], 'konuara': 'episodes'})
    soup = BeautifulSoup(r.content, 'html.parser', parse_only=SoupStrainer('div', {'id': 'catlist-listview2'}))
    mainUL = soup.ul
    return catalogFromIterable(((a.string, a['href'].replace(BASEURL, '')) for a in mainUL.find_all('a')))


def makeGenericCatalog(params):
    return makePopularCatalog(params) # Same HTML layout, can use the same scraping.


# Retrieves the catalog from a persistent XBMC window property between different add-on
# directories, or recreates the catalog based on one of the catalog functions.
def getCatalogProperty(params):
    path = params['path']

    def _rebuildCatalog():
        func = CATALOG_FUNCS.get(path, makeGenericCatalog)
        catalog = func(params)
        setWindowProperty(PROPERTY_CATALOG, catalog)
        return catalog

    # If these properties are empty (like when coming in from a favourites menu), or if
    # a different catalog (a different URL path) is stored in this property, then reload it.
    currentPath = getRawWindowProperty(PROPERTY_CATALOG_PATH)
    if currentPath != path or 'searchType' in params:
        catalog = _rebuildCatalog()
        setRawWindowProperty(PROPERTY_CATALOG_PATH, path)
    else:
        catalog = getWindowProperty(PROPERTY_CATALOG)
        if not catalog:
            catalog = _rebuildCatalog()
    return catalog


def actionResolve(params):
    # Needs to be the BASEURL to get multiple video qualities.
    url = params['url']
    r = requestHelper(url if url.startswith('http') else BASEURL + url)
    
    html = r.text
    chars = re.search(r' = \[(".*?")\];', html).group(1)
    spread = int(re.search(r' - (\d+)\)\; }', html).group(1))
    iframe = ''
    for char in chars.replace('"', '').split(','):
        char = b64decode(char)
        char = ''.join([d for d in char if d.isdigit()])
        char = chr(int(char) - spread)
        iframe += char

    sourceUrl = re.search(r'src="(.*?)"', iframe).group(1)
    if '&#038;' in sourceUrl:
        sourceUrl = sourceUrl.replace('&#038;', '&')
    else:
        sourceUrl = sourceUrl.replace('embed', 'embed-adh')
        
    r = requestHelper(BASEURL + sourceUrl)
    # Capture the sources block in the page.
    temp = re.search(r'sources:\s*(\[\s*?{.*?}\s*?\])(?:\s*}])?', r.text, re.DOTALL).group(1)
    # Add double quotes around every property name (file: -> "file":).
    temp = re.sub(r'(\s)(\w.*?)(:\s)', r'\1"\2"\3', temp)
    # Replace single quotes if applicable, so it can be loaded as JSON data.
    sources = json.loads(temp.replace("'",'"')) 
    
    # The property names in the sources block vary between 'file' and 'src' and between
    # 'label' and 'format' depending on if the show is new or not. The JSON data is a
    # list of dictionaries, one dict for each source.
    for s in sources:
        s['_url'] = s['file'] if 'file' in s else s.get('src','')
        s['_height'] = ''.join(char for char in (s['label'] if 'label' in s else s.get('format','')) if char.isdigit())
        s['_label'] = s['label'] if 'label' in s else s.get('format', 'video')
    sources = sorted(sources, key = lambda s: s['_height'])
    
    mediaURL = ''
    if len(sources) == 1:
        mediaURL = sources[0]['_url']
    elif len(sources) > 0:
        playbackMethod = ADDON.getSetting('playbackMethod')
        if playbackMethod == '0': # Select quality.
                selectedIndex = xbmcgui.Dialog().select(
                    'Select Quality',
                    tuple(source['_label'] for source in sources)
                )
                if selectedIndex != -1:
                    mediaURL = sources[selectedIndex].get('_url', '')
        elif playbackMethod == '1': # Play highest quality.
            mediaURL = sources[-1]['_url']
        else:
            mediaURL = sources[0]['_url'] # Play lowest quality.

    if mediaURL:
        # Need to use the exact same ListItem name/infolabels or else it gets replaced in the Kodi list.
        item = xbmcgui.ListItem(xbmc.getInfoLabel('ListItem.Label'))
       
        # Set some desktop browser headers for Kodi to use.
        global MEDIA_HEADERS
        if not MEDIA_HEADERS:
            MEDIA_HEADERS = '|' + '&'.join(key + '=' + quote_plus(value) for key, value in (
                    #('User-Agent', getRandomUserAgent()), # No need to spoof a desktop user agent.
                    ('Accept', 'video/webm,video/ogg,video/*;q=0.9,application/ogg;q=0.7,audio/*;q=0.6,*/*;q=0.5'),
                    ('Accept-Language', 'en-US,en;q=0.5'),
                    ('Connection', 'keep-alive'),
                    ('Referer', BASEURL + '/'),
                    ('DNT', '1')            
                )
            )
        
        item.setPath(mediaURL + MEDIA_HEADERS)
        item.setProperty('IsPlayable', 'true')
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
                                         
                                         
def xbmcDebug(name, val):
    xbmc.log('WATCHNIXTOONS2 > ' + name + ' ' + (repr(val) if not isinstance(val, str) else val), xbmc.LOGWARNING)


def requestHelper(url, data = None):
    # If the Session instance doesn't exist yet, create it and store it as a function attribute.
    if not hasattr(requestHelper, 'session'):
        session = requests.Session()
        myUA = 'Mozilla/5.0 (compatible; WatchNixtoons2/0.1.0; +https://github.com/doko-desuka/plugin.video.watchnixtoons2)'
        myHeaders = {
            'User-Agent': myUA,
            'Accept': 'text/html,application/xhtml+xml,application/xml,application/json;q=0.9,image/webp,*/*;q=0.8'
        }
        session.headers.update(myHeaders)
        requestHelper.session = session
    else:
        session = requestHelper.session    
        
    if data:
        return requestHelper.session.post(url, data=data, headers={'Referer':BASEURL+'/'}, verify=False, timeout = 8)
    else:
        return requestHelper.session.get(url, verify=False, timeout=8)


def getRandomUserAgent():
    # Random user-agent logic. Thanks to http://edmundmartin.com/random-user-agent-requests-python/
    from random import choice
    desktop_agents = (
        'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.99 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.99 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.99 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_1) AppleWebKit/602.2.14 (KHTML, like Gecko) Version/10.0.1 Safari/602.2.14',
        'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.71 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.98 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.98 Safari/537.36',
        'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.71 Safari/537.36',
        'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.99 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; WOW64; rv:50.0) Gecko/20100101 Firefox/50.0'
    )
    return choice(desktop_agents)
    

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
