# Miro - an RSS based video player application
# Copyright (C) 2005-2010 Participatory Culture Foundation
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

import errno
import signal
import os
import statvfs
import threading
from miro import config
from miro import prefs
import logging
import logging.handlers
import locale
import urllib
import sys
import time
from miro.util import (returns_unicode, returns_binary, check_u, check_b,
                       call_command)
import miro
from miro.plat import options

FilenameType = str

# We need to define samefile for the portable code.  Lucky for us, this is
# very easy.
from os.path import samefile

# this is used in portable/gtcache.py
_locale_initialized = False

def get_available_bytes_for_movies():
    """Helper method used to get the free space on the disk where downloaded
    movies are stored
    """
    d = config.get(prefs.MOVIES_DIRECTORY)

    if not os.path.exists(d):
        # FIXME - this is a bogus value.  need to "do the right thing"
        # here.
        return 0

    statinfo = os.statvfs(d)
    return statinfo.f_frsize * statinfo.f_bavail

backend_thread = None

def set_backend_thread():
    global backend_thread
    backend_thread = threading.currentThread()

def confirm_backend_thread():
    if backend_thread is not None and backend_thread != threading.currentThread():
        import traceback
        print "backend function called from thread %s" % threading.currentThread()
        traceback.print_stack()

ui_thread = None

def set_ui_thread():
    global ui_thread
    ui_thread = threading.currentThread()

def confirm_ui_thread():
    if ui_thread is not None and ui_thread != threading.currentThread():
        import traceback
        print "ui function called from thread %s" % threading.currentThread()
        traceback.print_stack()

def locale_initialized():
    return _locale_initialized

def initialize_locale():
    # gettext understands *NIX locales, so we don't have to do anything
    global _locale_initialized
    _locale_initialized = True

def setup_logging(inDownloader=False):
    if inDownloader:
        if os.environ.get('MIRO_FRONTEND') == 'cli':
            level = logging.WARN
        else:
            level = logging.INFO
        logging.basicConfig(level=level,
                            format='%(asctime)s %(levelname)-8s %(message)s',
                            stream=sys.stdout)
    else:
        if config.get(prefs.APP_VERSION).endswith("git"):
            level = logging.DEBUG
        elif options.frontend != 'cli':
            level = logging.INFO
        else:
            level = logging.WARN
        logging.basicConfig(level=level,
                            format='%(asctime)s %(levelname)-8s %(message)s')
        rotater = logging.handlers.RotatingFileHandler(config.get(prefs.LOG_PATHNAME), mode="w", maxBytes=100000, backupCount=5)
        formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
        rotater.setFormatter(formatter)
        logging.getLogger('').addHandler(rotater)
        rotater.doRollover()

@returns_binary
def utf8_to_filename(filename):
    if not isinstance(filename, str):
        raise ValueError("filename is not a str")
    return filename

@returns_binary
def unicodeToFilename(filename, path=None):
    """Takes in a unicode string representation of a filename (NOT a file
    path) and creates a valid byte representation of it attempting to preserve
    extensions.

    Note: This is not guaranteed to give the same results every time it is run,
    nor is it guaranteed to reverse the results of filenameToUnicode.
    """
    @returns_unicode
    def shortenFilename(filename):
        check_u(filename)
        first, last = os.path.splitext(filename)

        if first:
            return u"".join([first[:-1], last])

        return unicode(last[:-1])

    check_u(filename)
    if path:
        check_b(path)
    else:
        path = os.getcwd()

    # Keep this a little shorter than the max length, so we can run
    # nextFilename
    max_len = os.statvfs(path)[statvfs.F_NAMEMAX]-5

    for mem in ("/", "\000", "\\", ":", "*", "?", "\"", "<", ">", "|", "&"):
        filename = filename.replace(mem, "_")

    def encodef(filename):
        try:
            return filename.encode(locale.getpreferredencoding())
        except (SystemExit, KeyboardInterrupt):
            raise
        except:
            return filename.encode('ascii', 'replace')

    new_filename = encodef(filename)

    while len(new_filename) > max_len:
        filename = shortenFilename(filename)
        new_filename = encodef(filename)

    return new_filename

@returns_unicode
def filenameToUnicode(filename, path=None):
    """Given a filename in raw bytes, return the unicode representation

    Note: This is not guaranteed to give the same results every time it is run,
    not is it guaranteed to reverse the results of unicodeToFilename.
    """
    if path:
        check_b(path)
    check_b(filename)
    try:
        return filename.decode(locale.getpreferredencoding())
    except (SystemExit, KeyboardInterrupt):
        raise
    except:
        return filename.decode('ascii', 'replace')

@returns_unicode
def make_url_safe(s, safe='/'):
    """Takes in a byte string or a unicode string and does the right thing
    to make a URL
    """
    if isinstance(s, str):
        # quote the byte string
        return urllib.quote(s, safe=safe).decode('ascii')

    try:
        return urllib.quote(s.encode(locale.getpreferredencoding()), safe=safe).decode('ascii')
    except (SystemExit, KeyboardInterrupt):
        raise
    except:
        return s.decode('ascii', 'replace')

@returns_binary
def unmake_url_safe(s):
    """Undoes make_url_safe (assuming it was passed a filenameType)
    """
    # unquote the byte string
    check_u(s)
    return urllib.unquote(s.encode('ascii'))

def pid_is_running(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError, err:
        return err.errno == errno.EPERM

def kill_process(pid):
    if pid is None:
        return
    if pid_is_running(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            for i in xrange(100):
                time.sleep(.01)
                if not pid_is_running(pid):
                    return
            os.kill(pid, signal.SIGKILL)
        except (SystemExit, KeyboardInterrupt):
            raise
        except:
            logging.exception("error killing download daemon")

def launch_download_daemon(oldpid, env):
    # Use UNIX style kill
    if oldpid is not None and pid_is_running(oldpid):
        kill_process(oldpid)

    environ = os.environ.copy()
    environ['MIRO_FRONTEND'] = options.frontend
    environ['DEMOCRACY_DOWNLOADER_LOG'] = config.get(prefs.DOWNLOADER_LOG_PATHNAME)
    environ.update(env)
    miro_path = os.path.dirname(miro.__file__)
    dl_daemon_path = os.path.join(miro_path, 'dl_daemon')

    # run the Miro_Downloader script
    script = os.path.join(dl_daemon_path, 'Democracy_Downloader.py')
    os.spawnle(os.P_NOWAIT, sys.executable, sys.executable, script, environ)

def exit(return_code):
    sys.exit(return_code)

def set_properties(props):
    for p, val in props:
        logging.info("Setting preference: %s -> %s", p.alias, val)
        config.set(p, val)

def movie_data_program_info(movie_path, thumbnail_path):
    from miro import app
    return app.movie_data_program_info(movie_path, thumbnail_path)