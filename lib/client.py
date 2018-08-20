# -*- coding: utf-8 -*-
import sys
import json
import requests
from bs4 import BeautifulSoup
from urllib import urlencode
from base64 import b64decode
from string import ascii_uppercase
from itertools import chain, islice, takewhile
try:
    # Python 2.7
    from urlparse import parse_qs
    from HTMLParser import HTMLParser
except ImportError:
    # Python 3
    from urllib.parse import parse_qs
    from html.parser import HTMLParser

import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin

import re

from lib.common import (
    getWindowProperty,
    setWindowProperty,
    clearWindowProperty
)
#from lib.simpletvdb import tvdb # Unused.
from lib.simplecache import cache


BASEURL = 'https://www.watchcartoononline.io'
BASEURL_MOBILE = 'https://m.watchcartoononline.io'
BASEURL_IMAGES = BASEURL + '/wp-content/catimg/'

PROPERTY_CATALOG_PATH = 'watchnixtoons2.catalogPath'
PROPERTY_CATALOG = 'watchnixtoons2.catalog'

HTML_PARSER = HTMLParser()
IGNORED_WORDS_LOWCASE = set(('english','subbed','dubbed'))

addon = xbmcaddon.Addon()
ADDON_ICON_PATH = addon.getAddonInfo('icon')
ADDON_USE_METADATA = addon.getSetting('use_metadata')

# Page size = number of items per catalog section page. CAREFUL not to be greedy.
# Used when metadata is ON, to make it quicker to load pages but not overburden the website being requested.
CATALOG_PAGE_SIZE = 15 # Default: 15 scraped items per page, with 2 requests per item (1 for add-on, 1 for Kodi thumbnail).
API_REQUEST_DELAY = 200 # In milliseconds.

# Url paths: paths to parts of the website, to be added to the BASEURL_MOBILE url.
# Also used to tell what kind of catalog is loaded in memory, if it needs to be changed.
URL_PATHS = {
    'latest': '/last-50-recent-release',
    'popular': '/ongoing-series',
    'dubbed': '/dubbed-anime-list',
    'cartoons': '/cartoon-list',
    'subbed': '/subbed-anime-list',
    'movies': '/movie-list',
    'ova': '/ova-list',
    'search': '/search',
    'search-series': 'series_search',
    'search-episodes': 'episodes_search',
    'genre': '/search-by-genre'
}


def viewMenu(params):
    cache.saveCache() # Save cache, if dirty.

    def _makeItem(view, title, path):
        item = xbmcgui.ListItem('[B][COLOR orange]' + title + '[/COLOR][/B]', label2 = title)
        item.setArt({'icon': ADDON_ICON_PATH, 'fanart': ADDON_ICON_PATH.replace('icon.png','fanart.jpg')})
        item.setInfo( 'video', {'title': title, 'plot': title})
        return (buildUrl({'view': view, 'path': path}), item, True)

    listItems = (
        _makeItem('CATALOG_MENU', 'Latest Releases', URL_PATHS['latest']),
        _makeItem('CATALOG_MENU', 'Popular & Ongoing Series', URL_PATHS['popular']),
        _makeItem('CATALOG_MENU', 'Dubbed Anime', URL_PATHS['dubbed']),
        _makeItem('CATALOG_MENU', 'Cartoons', URL_PATHS['cartoons']),
        _makeItem('CATALOG_MENU', 'Subbed Anime', URL_PATHS['subbed']),
        _makeItem('CATALOG_MENU', 'Movies', URL_PATHS['movies']),
        _makeItem('CATALOG_MENU', 'OVA Series', URL_PATHS['ova']),
        _makeItem('SEARCH_MENU', 'Search', '')
    )
    xbmcplugin.addDirectoryItems(int(sys.argv[1]), listItems)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))


def getShowMeta(fullTitle, showPath):
    xbmc.sleep(API_REQUEST_DELAY)

    showMeta = cache.getCacheItem(fullTitle)
    if not showMeta and showPath != '':
        r = requestHelper(BASEURL_MOBILE + showPath)
        soup = BeautifulSoup(r.text, 'html.parser')
        div = soup.find('div', {'id':'category_description'})
        thumb = None; plot = None
        if div:
            thumb = div.img['src'].replace(BASEURL_IMAGES, '') if div.img else ''
            plot = div.p.string if div.p else ''
        showMeta = [thumb, plot]
        cache.addCacheItem(fullTitle, showMeta)

    # showMeta = [thumb, plot], but thumb url is shortened and needs to be appended to BASEURL_IMAGES url (to save memory).
    return showMeta


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



# Entry = (partial_url, full_item_title) -> partial_url needs to be appended to BASEURL_MOBILE.
def makeListItem(entry, scrapeMetadata):
    fullTitle = entry[1].strip()
    unescapedTitle = HTML_PARSER.unescape(fullTitle)
    item = xbmcgui.ListItem(unescapedTitle)
    title, season, episode  = getTitleInfo(unescapedTitle)

    if episode:
        # For episodes.
        item.setProperty('IsPlayable', 'true') # Allows the checkmark to be placed on watched episodes.
        thumb = xbmc.getInfoLabel('ListItem.Art(poster)')
        if thumb:
            item.setArt({'icon': thumb, 'thumb': thumb, 'poster': thumb})
        item.setInfo('video',
            {
                'mediatype': 'episode',
                'tvshowtitle': title,
                'season': season,
                'episode': episode,
                'plot': xbmc.getInfoLabel('ListItem.Plot')
            }
        )
    else:
        # For movies, specials\OVAs or separate seasons (like one listing for a large season, as if it were a show).
        plot = ''
        if scrapeMetadata:
            showMeta = getShowMeta(fullTitle, entry[0])
            if showMeta:
                if showMeta[0]:
                    thumb = BASEURL_IMAGES + showMeta[0]
                    item.setArt(
                        {
                            'icon': thumb,
                            'thumb': thumb,
                            'poster': thumb,
                            'fanart': thumb
                        }
                    )
                plot = showMeta[1] if showMeta[1] else ''
        item.setInfo('video',
            {
                'mediatype': 'episode', # It's not episode, but looks better on the layout.
                'tvshowtitle': title,
                'title': title,
                'plot': plot
            }
        )
    return item


'''
The catalog is a dictionary of lists of lists, used to store data between add-on states to make xbmcgui.ListItems:
{
    (1. Sections, as in alphabet sections of list items, A, B, C, D, E, F etc., each section holds a tuple of pages.)
    A: (
        page1, (2. Each page is a tuple holding items, or empty.)
        page2, (item, item, item, ...)     (3. Items, each item is a pair of <a> properties: (a['href'], a.string).)
        page3
    )
    B: (...)
    C: (...)
}
'''

# Manually splits items from an iterable returned by 'iterableFunc' into an alphabetised catalog.
# Iterable contains (a['href'], a.string) pairs which refer to a series, episode, ova or movie.
def catalogFromIterable(iterable):
    catalog = {key: [ [ ] ] for key in ascii_uppercase + '#'}
    for item in iterable:
        itemKey = item[1][0].upper()
        section = catalog[itemKey] if itemKey in catalog else catalog['#']
        currentPage = section[-1]
        currentPage.append(item) if len(currentPage) <= CATALOG_PAGE_SIZE else section.append( [item] )
    return catalog


def latestCatalog(params):
    # Returns a list of links from the "Latest 50 Releases" area but for mobile.
    r = requestHelper(BASEURL_MOBILE) # Path unused, data is already on the homepage.
    soup = BeautifulSoup(r.text, 'html.parser')
    mainOL = soup.find('ol', {'class': 'vList'})
    return catalogFromIterable( ((li.a['href'], li.a.text) for li in mainOL.find_all('li')))


def popularCatalog(params):
    # This scrapes the '/contact' page as it's smaller, as we're looking
    # for a sidebar that's on all pages and don't care about page body content.
    r = requestHelper(BASEURL_MOBILE + params['path'])
    soup = BeautifulSoup(r.text, 'html.parser')
    div = soup.find('div', {'data-role': 'content'})
    mainUL = div.ul
    return catalogFromIterable( ((a['href'], a.string) for a in mainUL.find_all('a')) )


def seriesSearchCatalog(params):
    r = requestHelper(BASEURL + '/search', {'catara': params['text'], 'konuara': 'series'})
    soup = BeautifulSoup(r.text, 'html.parser')
    results = soup.find_all('div', {'class': 'cerceve'})
    if results:
        return catalogFromIterable( ((div.a['href'].replace(BASEURL, ''), div.a.string) for div in results) )
    else:
        return [ ]


def episodesSearchCatalog(params):
    r = requestHelper(BASEURL + '/search', {'catara': params['text'], 'konuara': 'episodes'})
    soup = BeautifulSoup(r.text, 'html.parser')
    mainUL = soup.find('div', {'id': 'catlist-listview2'}).find_next('ul')
    return catalogFromIterable( ((a['href'].replace(BASEURL, ''), a.string) for a in mainUL.find_all('a')) )


def genericCatalog(params):
    return popularCatalog(params) # Same HTML layout, can use the same scraping.


# Retrieves the catalog from a persistent window property between different add-on
# directories, or recreates the catalog based on one of the catalog functions.
def getCatalogProperty(params):
    path = params['path']

    def _buildCatalog():
        func = CATALOG_FUNCS.get(path, genericCatalog)
        catalog = func(params)
        setWindowProperty(PROPERTY_CATALOG, catalog)
        return catalog

    # If these properties are empty (like when coming in from a favourites menu), or if
    # a different catalog (a different url path) is stored in this property, then reload it.
    currentPath = getWindowProperty(PROPERTY_CATALOG_PATH)
    if currentPath != path:
        setWindowProperty(PROPERTY_CATALOG_PATH, path)
        catalog = _buildCatalog()
    else:
        catalog = getWindowProperty(PROPERTY_CATALOG)
        if not catalog:
            catalog = _buildCatalog()
    return catalog


def viewCatalogMenu(params):
    xbmcplugin.setContent(int(sys.argv[1]), 'tvshows')
    catalog = getCatalogProperty(params)

    sectionAll = (
        buildUrl( {'view': 'CATALOG_SECTION', 'path': params['path'], 'section': 'ALL', 'page': 0} ),
        xbmcgui.ListItem('All'),
        True
    )
    listItems = (
        (
            buildUrl( {'view': 'CATALOG_SECTION', 'path': params['path'], 'section': sectionName, 'page': 0} ),
            xbmcgui.ListItem(sectionName),
            True
        )
        for sectionName in sorted(catalog.iterkeys()) if len(catalog[sectionName][0]) > 0
    )
    xbmcplugin.addDirectoryItems(int(sys.argv[1]), (sectionAll,) + tuple(listItems))
    xbmcplugin.endOfDirectory(int(sys.argv[1]))
    xbmc.executebuiltin('Container.SetViewMode(54)') # InfoWall mode, Estuary skin (the default skin).


def viewCatalogSection(params):
    xbmcplugin.setContent(int(sys.argv[1]), 'episodes')
    catalog = getCatalogProperty(params)

    path = params['path']
    if path not in (URL_PATHS['ova'], URL_PATHS['movies'], URL_PATHS['search-episodes'], URL_PATHS['latest']):
        view = 'LIST_EPISODES'
        isFolder = True
    else:
        # Special case for the OVA, movie and episode-search catalogs, they link to the video player pages already.
        view = 'RESOLVE'
        isFolder = False

    def _makeItem(entry, scrapeMetadata = False):
        return (
            buildUrl({'view': view, 'url': entry[0]}),
            makeListItem(entry, scrapeMetadata),
            isFolder
        )

    sectionName = params['section']
    if ADDON_USE_METADATA:
        cache.ensureCacheLoaded() # Make sure cache is loaded, to avoid web requests.

        # Display items in pages so it's faster to scrape and not too abusive on the website.
        page = int(params['page']) # Zero-based index.
        if sectionName == 'ALL':
            # Create pages with a generator for "ALL".
            # Flatten all sections into a list, then flatten all pages into
            # another list, which is then isliced to get the current directory page.
            start = page * CATALOG_PAGE_SIZE
            stop = start + CATALOG_PAGE_SIZE
            flatSections = chain.from_iterable(catalog[key] for key in sorted(catalog.iterkeys()))
            listItems = (
                _makeItem(entry, True)
                for entry in (pageEntry for pageEntry in islice(chain.from_iterable(flatSections), start, stop))
            )
            totalSectionPages = sum(len(page) for page in chain.from_iterable(catalog.itervalues())) // CATALOG_PAGE_SIZE
        else:
            # Use one of the premade pages.
            listItems = (_makeItem(entry, True) for entry in catalog[sectionName][page])
            totalSectionPages = len(catalog[sectionName])

        page += 1
        if totalSectionPages > 1 and page < totalSectionPages:
            params.update({'page':page})
            nextPage = (buildUrl(params), xbmcgui.ListItem('Next Page ('+str(page+1)+'/'+str(totalSectionPages)+')'), True)
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), tuple(listItems) + (nextPage,))
        else:
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), tuple(listItems))

        # After the list items have been tuple'd into existence, flush the cache object to memory.
        cache.flushCacheToMemory()
    else:
        if sectionName == 'ALL':
            allSections = chain.from_iterable(catalog[sectionName] for sectionName in sorted(catalog.iterkeys()))
            listItems = (_makeItem(entry) for page in allSections for entry in page)
        else:
            allPages = chain.from_iterable(page for page in catalog[sectionName])
            listItems = (_makeItem(entry) for entry in allPages)
            totalSectionPages = len(catalog[sectionName])
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), tuple(listItems))

    xbmcplugin.endOfDirectory(int(sys.argv[1]))
    #xbmc.executebuiltin('Container.SetViewMode(54)') # Commented it out, the default WideList looks better imo.


# A sub menu, lists search options.
def viewSearchMenu(params):
    def _modalKeyboard(heading):
        kb = xbmc.Keyboard('', heading)
        kb.doModal()
        return kb.getText() if kb.isConfirmed() else ''

    if 'search' in params:
        text = _modalKeyboard('Series Name' if params['search'] == 'series' else 'Episode Title')
        if text:
            params.update({'view': 'CATALOG_MENU', 'text': text}) # Send the search query for the catalog functions to use.
            xbmc.executebuiltin('Container.Update(%s,replace)' % buildUrl(params) )
            return
        else:
            return # User typed nothing or cancelled the keyboard.

    listItems = (
        (
            buildUrl({'view': 'SEARCH_MENU', 'path': URL_PATHS['search-series'], 'search': 'series'}),
            xbmcgui.ListItem('Search Series Name'),
            True
        ),
        (
            buildUrl({'view': 'SEARCH_MENU', 'path': URL_PATHS['search-episodes'], 'search': 'episodes'}),
            xbmcgui.ListItem('Search Episode Title'),
            True
        ),
        (
            buildUrl({'view': 'SEARCH_GENRE', 'path': URL_PATHS['genre']}),
            xbmcgui.ListItem('Search Genre'),
            True
        )
    )
    xbmcplugin.addDirectoryItems(int(sys.argv[1]), listItems)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))


# A sub menu, lists the genre categories in the genre search.
def viewSearchGenre(params):
    r = requestHelper(BASEURL + URL_PATHS['genre'])
    soup = BeautifulSoup(r.text, 'html.parser')
    mainDIV = soup.find('div', {'class': 'ddmcc'})
    listItems = (
        (
            buildUrl( {'view': 'CATALOG_MENU', 'path': URL_PATHS['genre'] + a['href'][ a['href'].rfind('/') : ]} ),
            xbmcgui.ListItem(a.string),
            True
        )
        for a in mainDIV.find_all('a')
    )
    xbmcplugin.addDirectoryItems(int(sys.argv[1]), tuple(listItems))
    xbmcplugin.endOfDirectory(int(sys.argv[1]))


def viewListEpisodes(params):
    xbmcplugin.setContent(int(sys.argv[1]), 'episodes')

    r = requestHelper(BASEURL_MOBILE + params['url']) # Full show url of the mobile version of the website.
    soup = BeautifulSoup(r.text, 'html.parser')
    div = soup.find('div', {'data-role': 'content'})
    mainUL = div.ul
    listItems = (
        (
            buildUrl( {'view': 'RESOLVE', 'url': a['href']} ),
            makeListItem((a['href'], a.string), False), # False to NOT scrape any metadata.
            False
        )
        for a in mainUL.find_all('a')
    )
    xbmcplugin.addDirectoryItems(int(sys.argv[1]), tuple(listItems))
    xbmcplugin.endOfDirectory(int(sys.argv[1]))


def resolve(params):
    cache.saveCache() # Save cache before watching an pisode, if dirty.

    r = requestHelper(BASEURL + params['url']) # Needs to be BASEURL to get multiple video qualities.
    html = r.text

    chars = re.findall(r' = \[(".*?")\];', html)[0]
    spread = int(re.findall(r' - (\d+)\)\; }', html)[0])
    chars = chars.replace('"','').split(',')
    iframe = ''
    for char in chars:
        char = b64decode(char)
        char = ''.join([d for d in char if d.isdigit()])
        char = chr(int(char) - spread)
        iframe += char

    sourceUrl = re.findall(r'src="(.*?)"', iframe)[0]
    if '&#038;' in sourceUrl:
        sourceUrl = sourceUrl.replace('&#038;', '&')
    else:
        sourceUrl = sourceUrl.replace('embed', 'embed-adh')

    r = requestHelper(BASEURL + sourceUrl)
    temp = re.findall(r'sources:\s*(\[\s*?{.*?}\s*?\])(?:\s*}])?', r.text, re.DOTALL)[0] # Capture the sources block in the page.
    temp = re.sub(r'(\s)(\w.*?)(:\s)', r'\1"\2"\3', temp) # Add double quotes around every property name (file: -> "file":).
    sources = json.loads(temp.replace("'",'"')) # Replace single quotes if applicable, so it can be loaded as JSON data.

    # The property names in the sources block vary between 'file' and 'src' and between
    # 'label' and 'format' depending on if the show is new or not. The JSON data is a
    # list of dictionaries, one dict for each source.
    for s in sources:
        s['_url'] = s['file'] if 'file' in s else s.get('src','')
        s['_height'] = ''.join( char for char in (s['label'] if 'label' in s else s.get('format','')) if char.isdigit() )
        s['_label'] = s['label'] if 'label' in s else s.get('format', 'video')
    sources = sorted(sources, key = lambda s: s['_height'], reverse = True)

    mediaUrl = ''
    if len(sources) == 1:
        mediaUrl = sources[0]['_url']
    elif len(sources) > 0:
        playbackMethod = xbmcaddon.Addon().getSetting('playback_method')
        if playbackMethod == '0': # Select quality.
                selectedIndex = xbmcgui.Dialog().select(
                    'Select Quality',
                    tuple((source['_label'] for source in sources))
                )
                if selectedIndex != -1:
                    mediaUrl = sources[selectedIndex].get('_url', '')
        elif playbackMethod == '1': # Play highest quality.
            mediaUrl = sources[0]['_url']
        else:
            mediaUrl = sources[-1]['_url'] # Play lowest quality.

    if mediaUrl:
        # Need to use the same name\infolabel or else it gets replaced in the Kodi interface.
        item = xbmcgui.ListItem(xbmc.getInfoLabel('ListItem.Label'))
        item.setPath(mediaUrl)
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
        #xbmc.Player().play(listitem=item) # Alternative play method.
        xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, item)


def buildUrl(query):
    return sys.argv[0] + '?' + urlencode( {k: unicode(v).encode('utf-8') for k, v in query.iteritems()})


def requestHelper(url, data = None):
    if not hasattr(requestHelper, 'session'):
        requestHelper.session = requests.Session() # Seesion is stored as a function attribute.

        """# Random user-agent logic. Thanks to http://edmundmartin.com/random-user-agent-requests-python/
        from random import choice
        desktop_agents = [
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
        ]
        randomHeader = {'User-Agent': choice(desktop_agents), 'Accept': 'text/html,application/xhtml+xml,application/xml,application/json;q=0.9,image/webp,*/*;q=0.8'}"""
        myUA = 'WatchNixtoons2 (https://github.com/doko-desuka/plugin.video.watchnixtoons2)'
        randomHeader = {'User-Agent': myUA, 'Accept': 'text/html,application/xhtml+xml,application/xml,application/json;q=0.9,image/webp,*/*;q=0.8'}

        requestHelper.session.headers.update(randomHeader)
    if data:
        return requestHelper.session.post(url, data = data, timeout = 8)
    else:
        return requestHelper.session.get(url, timeout = 8)


CATALOG_FUNCS = {
    URL_PATHS['latest']: latestCatalog,
    URL_PATHS['popular']: popularCatalog,
    URL_PATHS['search-series']: seriesSearchCatalog,
    URL_PATHS['search-episodes']: episodesSearchCatalog
}


# Main dictionary of add-on directories (aka views or screens).
VIEW_FUNCS = {
    'MENU': viewMenu,

    'CATALOG_MENU': viewCatalogMenu,
    'CATALOG_SECTION': viewCatalogSection,
    'SEARCH_MENU': viewSearchMenu,
    'SEARCH_GENRE': viewSearchGenre,

    'LIST_EPISODES': viewListEpisodes,
    'RESOLVE': resolve
}


def main():
    params = {key: value[0] for key, value in parse_qs(sys.argv[2][1:]).iteritems()}
    VIEW_FUNCS[params.get('view', 'MENU')](params)