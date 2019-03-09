# -*- coding: utf-8 -*-
import requests

import xbmcgui
from xbmc import sleep


class SimpleTrakt():
    TRAKT_API_URL = 'https://api.trakt.tv'

    CLIENT_ID = 'fd584905ac39b30b8458d583b75ea1b39743e036b293da91c838fdc3cc59dbcc'
    CLIENT_SECRET = 'd9fa7c625add7a6df29be40b9364482a8c61f520df9961a6708742b79c3b3afe'

    _INSTANCE = None

    @classmethod
    def getInstance(cls):
        if not cls._INSTANCE:
            cls._INSTANCE = SimpleTrakt()
        return cls._INSTANCE


    @classmethod
    def clearTokens(cls, addon):
        hadToClear = False
        accessToken = addon.getSetting('trakt_access')
        if accessToken:
            requests.post(
                cls.TRAKT_API_URL + '/oauth/revoke',
                json = {
                    'access_token': accessToken,
                    'client_id': cls.CLIENT_ID,
                    'client_secret': cls.CLIENT_SECRET
                },
                timeout = 10
            )
            hadToClear = True
        addon.setSetting('trakt_access', '')
        addon.setSetting('trakt_refresh', '')
        return hadToClear


    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                'Content-Type': 'application/json',
                'trakt-api-key': self.CLIENT_ID,
                'trakt-api-version': '2',
            }
        )


    def ensureAuthorized(self, addon):
        accessToken = addon.getSetting('trakt_access')
        if not accessToken:
            tokens = self._tryPairDialog()
            if tokens:
                accessToken, refreshToken = tokens
                addon.setSetting('trakt_access', accessToken)
                addon.setSetting('trakt_refresh', refreshToken)

        if accessToken:
            self.session.headers.update({'Authorization': 'Bearer ' + accessToken})
            return True
        else:
            return False


    def getUserLists(self, addon):
        r = self._traktRequest('/users/me/lists', data=None, addon=addon)
        return r.json() if r.ok else ()


    def getListItems(self, listID, addon):
        r = self._traktRequest('/users/me/lists/' + listID + '/items/movie,show', data=None, addon=addon)
        if r.ok:
            return set(item[item['type']]['title'] for item in r.json())
        else:
            return ()


    def _tryPairDialog(self):
        r = self._traktRequest('/oauth/device/code', {'client_id': self.CLIENT_ID})
        if r.ok:
            jsonData = r.json()
            deviceCode = jsonData['device_code']
            totalTime = jsonData['expires_in']
            interval = jsonData['interval']

            progressDialog = xbmcgui.DialogProgress()
            progressDialog.create(
                'Trakt Activation',
                'Go to [B]' + jsonData['verification_url'] + '[/B] and enter this code:',
                '[COLOR aquamarine][B]' + jsonData['user_code'] + '[/B][/COLOR]',
                'Time left:'
            )

            pollData = {
                'code': deviceCode,
                'client_id': self.CLIENT_ID,
                'client_secret': self.CLIENT_SECRET
            }

            for s in xrange(totalTime):
                if progressDialog.iscanceled():
                    break
                percentage = int(s / float(totalTime) * 100.0)
                progressDialog.update(percentage, line3='Time left: [B]' + str(totalTime - s) + '[/B] seconds')

                if not (s % interval):
                    r2 = self._traktRequest('/oauth/device/token', pollData)
                    if r2.status_code == 200: # Process complete.
                        progressDialog.close()
                        jsonData = r2.json()
                        return jsonData['access_token'], jsonData['refresh_token']
                    elif r2.status_code == 409 or r2.status_code == 418:
                        progressDialog.close()
                        break
                sleep(1000)
            else:
                progressDialog.close()
            return None
            
        else:
            self._notification('Watchnixtoons2', 'Trakt request failed', useSound=True, isError=True)
            return None


    def _tryRefreshToken(self, addon):
        refreshToken = addon.getSetting('trakt_refresh')
        if refreshToken:
            r = self.session.post(
                '/oauth/token',
                json = {
                    'client_id': self.CLIENT_ID,
                    'client_secret': self.CLIENT_SECRET,
                    'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
                    'grant_type': 'refresh_token',
                    'refresh_token': refreshToken
                },
                timeout = 10
            )
            if r.ok:
                jsonData = r.json()
                addon.setSetting('trakt_access', accessToken)
                addon.setSetting('trakt_refresh', refreshToken) # The refresh token also updates.
                self.session.headers.update({'Authorization': 'Bearer ' + accessToken})
                return True
        return False


    def _traktRequest(self, path, data, addon=None):
        try:
            if data:
                r = self.session.post(self.TRAKT_API_URL + path, json=data, timeout=10)
            else:
                r = self.session.get(self.TRAKT_API_URL + path, timeout=10)

            # See if the token has expired (happens every 3 months).
            if addon and r.status_code in (401, 400, 403) and self._tryRefreshToken(addon):
                r = self._traktRequest(path, data) # Try once more after refreshing the token.
            return r
        except:
            return type('FailedResponse', (object,), {'ok': False, 'status_code': 400})


    def _notification(self, heading, caption, useSound=False, isError=False):
        icon = xbmcgui.NOTIFICATION_ERROR if isError else xbmcgui.NOTIFICATION_INFO
        xbmcgui.Dialog().notification(heading, caption, icon, 3000, useSound)
