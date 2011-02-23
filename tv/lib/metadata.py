# Miro - an RSS based video player application
# Copyright (C) 2005, 2006, 2007, 2008, 2009, 2010, 2011
# Participatory Culture Foundation
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
#
# In addition, as a special exception, the copyright holders give
# permission to link the code of portions of this program with the OpenSSL
# library.
#
# You must obey the GNU General Public License in all respects for all of
# the code used other than OpenSSL. If you modify file(s) with this
# exception, you may extend this exception to your version of the file(s),
# but you are not obligated to do so. If you do not wish to do so, delete
# this exception statement from your version. If you delete this exception
# statement from all source files in the program, then also delete it here.

"""``miro.metadata`` -- Handle metadata properties for *Items. Generally the
frontend cares about these and the backend doesn't.
"""

import logging
import fileutil

from miro.gtcache import gettext as _
from miro.util import returns_unicode
from miro import coverart

class Source(object):
    """Object with readable metadata properties."""

    def get_iteminfo_metadata(self):
        return dict(
            name = self.get_title(),
            title_tag = self.title_tag,
            description = self.description,
            album = self.album,
            album_artist = self.album_artist,
            artist = self.artist,
            track = self.track,
            album_tracks = self.album_tracks,
            year = self.year,
            genre = self.genre,
            rating = self.rating,
            cover_art = self.cover_art,
            has_drm = self.has_drm,
        )

    def setup_new(self):
        self.title = u""
        self.title_tag = None
        self.description = u""
        self.album = None
        self.album_artist = None
        self.artist = None
        self.track = None
        self.album_tracks = None
        self.year = None
        self.genre = None
        self.rating = None
        self.cover_art = None
        self.has_drm = None
        self.file_type = None
        self.metadata_version = 0

    @returns_unicode
    def get_title(self):
        if self.title:
            return self.title
        else:
            return self.title_tag

def metadata_setter(attribute, type_=None):
    def set_metadata(self, value, _bulk=False):
        if value is not None and type_ is not None:
            # None is always an acceptable value for metadata properties
            value = type_(value)
        if not _bulk:
            self.confirm_db_thread()
        self.__dict__[attribute] = value
        if not _bulk:
            self.signal_change()
            self.write_back((attribute,))
    return set_metadata

class Store(Source):
    """Object with read/write metadata properties."""

    set_title = metadata_setter('title', unicode)
    set_title_tag = metadata_setter('title_tag', unicode)
    set_description = metadata_setter('description', unicode)
    set_album = metadata_setter('album', unicode)
    set_album_artist = metadata_setter('album_artist', unicode)
    set_artist = metadata_setter('artist', unicode)
    set_track = metadata_setter('track', int)
    set_album_tracks = metadata_setter('album_tracks')
    set_year = metadata_setter('year', int)
    set_genre = metadata_setter('genre', unicode)
    set_rating = metadata_setter('rating', int)
    set_file_type = metadata_setter('file_type', unicode)
    set_has_drm = metadata_setter('has_drm', bool)

    def set_cover_art(self, new_file, _bulk=False):
        """Set new cover art. Deletes any old cover art.

        Creates a copy of the image in our cover art directory.
        """
        if not _bulk:
            self.confirm_db_thread()
        if new_file:
            new_cover = coverart.Image.from_file(new_file, self.get_filename())
        self.delete_cover_art()
        if new_file:
            self.cover_art = new_cover
        if not _bulk:
            self.signal_change()
            self.write_back(('cover_art',))

    def delete_cover_art(self):
        """Delete the cover art file and unset cover_art."""
        try:
            fileutil.remove(self.cover_art)
        except (OSError, TypeError):
            pass
        self.cover_art = None

    def setup_new(self):
        Source.setup_new(self)
        self._deferred_update = {}

    def set_metadata_from_iteminfo(self, changes, _deferrable=True):
        self.confirm_db_thread()
        for field, value in changes.iteritems():
            Store.ITEM_INFO_TO_ITEM[field](self, value, _bulk=True)
        self.signal_change()
        self.write_back(changes.keys())

    def write_back(self, _changed):
        """Write back metadata changes to the original source, if supported. If
        this method fails because the item is playing, it should add the changed
        fields to _deferred_update.
        """
        logging.debug("%s can't write back changes", self.__class__.__name__)

    def set_is_playing(self, playing):
        """Hook so that we can defer updating an item's data if we can't change
        it while it's playing.
        """
        if not playing and self._deferred_update:
            self.set_metadata_from_iteminfo(self._deferred_update, _deferrable=False)
            self._deferred_update = {}
        super(Store, self).set_is_playing(playing)

    ITEM_INFO_TO_ITEM = dict(
        name = set_title,
        title_tag = set_title_tag,
        description = set_description,
        album = set_album,
        album_artist = set_album_artist,
        artist = set_artist,
        track = set_track,
        album_tracks = set_album_tracks,
        year = set_year,
        genre = set_genre,
        rating = set_rating,
        file_type = set_file_type,
        cover_art = set_cover_art,
        has_drm = set_has_drm,
    )
