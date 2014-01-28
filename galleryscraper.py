# Standard library modules
import os
import os.path
import sys
import json
import zlib
import logging
import urlparse
from multiprocessing.dummy import Pool as ThreadPool
from collections import namedtuple, defaultdict
from datetime import datetime
from functools import wraps
from time import sleep

# 3rd party modules
import requests
from docopt import docopt
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup


__author__ = 'Aaron Jacobs <atheriel@gmail.com>'
__version__ = '0.2.0'
__license__ = 'ISCL'
__doc__ = """
Usage:
  galleryscraper.py URL DIR [--threads N --log-level N --quiet --skip-duplicates]
  galleryscraper.py -h | --help | --version

Options:
      --threads N        the number of threads to use [default: 4]
  -V, --log-level N      the level of info logged to the console, which can be
                         one of INFO, DEBUG, or WARNING [default: INFO]
  -s, --skip-duplicates  ignore files that have been downloaded already
  -q, --quiet            suppress output to console
  -v, --version          show program's version number and exit
  -h, --help             show this help message and exit

Written by {author}. Licensed under the {license}.
""".format(author = __author__, license = __license__)


# Decorators
# ---------------------------

def sessional(func):
    """
    Decorator that maintains the same session for URL requests within the given
    function. It relies on the wrapped function taking a ``session`` keyword
    argument. At the moment this is only used for the safe_request function,
    but if timeouts are not a problem it can be used to wrap all of the other
    functions that make requests instead.
    """
    session = requests.Session()
    session.mount('http://', HTTPAdapter(max_retries=5))
    session.headers['User-Agent'] = 'Mozilla/5.0 (Windows; U; Windows NT 5.1; it; rv:1.8.1.11) Gecko/20071127 Firefox/2.0.0.11'
    
    @wraps(func)
    def newfunc(*args, **kwargs):
        try:
            # Replace sessions in the function's (kw) arguments
            kwargs['session'] = session
        except KeyError:
            pass
        return func(*args, **kwargs)
    
    return newfunc

def cache(func):
    """
    Decorator that caches the results of calls to a function, so that if the
    same arguments are passed it will simply return the result obtained
    previously. This is useful when the function is deterministic and somewhat
    expensive to compute.

    You can obtain the cache for a decorated function from ``func.cache``.
    """
    cache = func.cache = {}
    
    @wraps(func)
    def cached(*args, **kwargs):
        key = str(args) + str(kwargs)
        if key not in cache:
            cache[key] = func(*args, **kwargs)
        return cache[key]
    
    return cached

def safe(func, delay = 10, exceptions = (Exception,), attempts = 5):
    """
    Decorator that sleeps the thread for a given delay if the function raises
    an exception. The exceptions to include and the number of attempts to make
    before giving up can also be given.
    """
    @wraps(func)
    def safely(*args, **kwargs):
        for tries in xrange(1, attempts + 1):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                if tries < attempts:
                    logging.info('<%s> raised exception <%s>. Sleeping for 10s before retry.', func.__name__, str(type(e)))
                    sleep(delay)
                else:
                    raise
    return safely

# Utility functions
# ---------------------------

def generate_name_from_url(url):
    """
    Generate a hexidecimal hash of the page name, so multiple galleries can be
    stored in one folder. Note that this is a deterministic process, so that
    one may 'retry' a scrape without creating duplicate images.

    The number of collisions should be more than low enough for this particular
    application, around 1 in 2^32 - 1.
    """
    return '%4x' % (zlib.crc32(url) & 0xffffffff)

def levenshtein(first, second):
    """
    Calculates the Levenshtein distance between two strings.

    See `Wikipedia`_ for details and the source.

    .. _Wikipedia: http://en.wikibooks.org/wiki/Algorithm_implementation/\
    Strings/Levenshtein_distance#Python
    """
    first = ' ' + first
    second = ' ' + second
    d = {}
    S = len(first)
    T = len(second)
    for i in xrange(S):
        d[i, 0] = i
    for j in xrange (T):
        d[0, j] = j
    for j in xrange(1,T):
        for i in xrange(1,S):
            if first[i] == second[j]:
                d[i, j] = d[i-1, j-1]
            else:
                d[i, j] = min(d[i-1, j] + 1, d[i, j-1] + 1, d[i-1, j-1] + 1)
    return d[S-1, T-1]

def _logme(name, level = logging.INFO, console = True):
    """
    Sets up logging at the given level. If console is False, output to STDIN is
    suppressed.
    """
    # So you can pass 'INFO' instead of 'logging.INFO'
    if isinstance(level, str):
        level = getattr(logging, level)
    
    log_dir = '/tmp/' + name.rsplit('/', 1)[0]
    if not os.path.exists(log_dir):
        os.mkdir(log_dir)
    
    logging.basicConfig(
        filename = "/tmp/" + name + ".log",
        filemode = "w",
        level = level,
        format = '[%(asctime)s][%(levelname)s] %(message)s',
        datefmt = '%y-%m-%d %H:%M:%S'
    )

    if console:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(
            fmt="[%(asctime)s][%(levelname)s] %(message)s",
            datefmt="%H:%M:%S")
        )
        logging.getLogger().addHandler(console)
        console.setLevel(level)

@sessional
@safe
def safe_request(url, type = 'get', session = None, **kwargs):
    """
    Wraps requests to retry after a timeout. This is quite useful, since many
    people do not like web scrapers, and drop the connection if they receive
    rapid get requests.
    """
    assert isinstance(session, requests.Session)
    return getattr(session, type)(url, timeout = 3.0, **kwargs)

# Parser functions
# ---------------------------

def parse_gallery_page(url):
    """
    Finds all image links on a page that contains a gallery. Also returns a
    dictionary of suspected thumnails and their links, and the title of the
    page (if there is one).
    """
    ImageSearchResult = namedtuple('ImageSearchResult', ['images', 'thumbnails', 'page_title'])
    images, thumbnail_map = [], dict()

    req = safe_request(url)
    soup = BeautifulSoup(req.text)

    # Sets the page title
    page_title = None
    try:
        page_title = soup.head.title.contents[0].strip()
    except Exception:
        logging.info('No page title found.')

    # Finds ALL image links on the page
    for link in soup.find_all('img'):
        if link.parent.get('href') is not None:  # It's probably a thumbnail
            source = urlparse.urljoin(url, link.parent['href'])
            thumb = urlparse.urljoin(url, link['src'])
            images.append(thumb)
            thumbnail_map[thumb] = source

            logging.debug('Thumbnail image found with link to <%s>.', source)
        elif 'src' not in link:
            continue
        else:
            source = urlparse.urljoin(url, link['src'])
            images.append(source)

            logging.debug('Non-thumbnail image found at <%s>.', source)

    assert len(images) > 0  # Just in case...

    # Group links together in clusters based on similarity of strings
    cid = 0
    images = sorted(images)
    clusters = defaultdict(list, {0: [images.pop(0)]})

    for i, line in enumerate(sorted(images)):
        last = clusters[cid][-1]
        if levenshtein(last, line) > 10:  # Strings are too dissimilar
            cid += 1
        clusters[cid].append(line)

    # Sort by size of cluster and get the largest
    largest = sorted(clusters.iterkeys(), key = lambda k: len(clusters[k]), reverse = True)[0]

    return ImageSearchResult(clusters[largest], thumbnail_map, page_title)


def find_largest_image_on_page(url):
    """
    Finds the largest image on a page (by content-length) and returns its url.
    """
    req = safe_request(url)
    soup = BeautifulSoup(req.text)

    dims, biggest_image = -1, ''

    for link in soup.find_all('img'):
        src = urlparse.urljoin(url, link['src'])
        is_image, link_dim, link_type = image_check(src)
        if not is_image:
            logging.debug('Non-image file as source for image at <%s> with content-type <%s>.', src, link_type)
        else:
            logging.debug('Image with content length %d found at <%s>.', link_dim, src)
            if link_dim > dims:
                dims = link_dim
                biggest_image = urlparse.urljoin(url, link['src'])

    return biggest_image


@cache
def image_check(url):
    """
    Checks if the file at the given url is an image, no matter its actual
    extension. Often banners on one part of the site will share the same url,
    so we cache the result to save rechecking them.
    """
    ImageCheckResult = namedtuple('ImageCheckResult', ['is_image', 'bytes', 'content_type'])

    page, size = safe_request(url, type = 'head'), 0
    if page.status_code != 200:
        logging.debug('Image request at <%s> returned code <%d>.', url, page.status_code)

    # Sometimes, the pages just don't have a content-length; ignore these
    try:
        size = int(page.headers['content-length'])
    except KeyError:
        pass

    return ImageCheckResult(True, size, page.headers['content-type']) if 'image' in page.headers['content-type'] else ImageCheckResult(False, size, page.headers['content-type'])


@cache
def download_image(url, filename, overwrite = False):
    """
    Downloads the image at the given url and writes it to filename.
    """
    filename += '.' + urlparse.urlparse(url).path.rsplit('.', 1)[1]  # Add the extension
    if os.path.exists(os.path.abspath(filename)) and not overwrite:
        logging.info('File already exists at <%s>. Skipping...', filename)
        return

    logging.info('Downloading image from <%s> to file %s.', url, filename)

    req = safe_request(url, stream = True)
    if req.status_code != 200:
        logging.debug('Image request at <%s> returned code <%d>.', url, req.status_code)

    with open(filename, 'wb') as f:
        for chunk in req.iter_content(1024):
            f.write(chunk)


def scrape_gallery(url, outdir = 'out', include_info = True, overwrite = False, threads = 2):
    """
    Scrapes a web page containing an image gallery, either as full images or in
    the form of thumbnails to be followed. The images are written to disk under
    the output directory ``outdir`` with a filename created from a hash of the
    website url and an index number. An info.txt file is also created if the
    ``include_info`` parameter is True (by default).
    """
    logging.info('Beginning to scrape <%s>.', url)
    images, thumbnail_map, page_title = parse_gallery_page(url)

    if not os.path.exists(os.path.abspath(outdir)):
        logging.info('Creating image directory...')
        os.mkdir(outdir)

    filename_prefix = '/'.join([outdir, generate_name_from_url(url)])
    logging.info('Filename prefix: %s', filename_prefix)

    # Work out whether to follow thumbnail links
    candidates = []
    for index, image in enumerate(images):
        try:
            candidates.append((index, thumbnail_map[image]))
        except KeyError:  # It's not a thumbnail
            candidates.append((index, image))
    assert len(candidates) == len(images)

    # The function that handles downloading images/finding, etc.
    def get_image(arg):
        index = arg[0]
        candidate = arg[1]
        if image_check(candidate).is_image:
            download_image(candidate, '-'.join([filename_prefix, str(index)]), overwrite)
        else:
            logging.info('Finding largest image on <%s>...', candidate)
            biggest_image = find_largest_image_on_page(candidate)
            download_image(biggest_image, '-'.join([filename_prefix, str(index)]), overwrite)

    # Threading. Vroom, vroom.
    pool = ThreadPool(threads)
    pool.map(get_image, candidates)
    pool.close()
    pool.join()

    # Create info header and write it to a text file
    if include_info:
        logging.info('Writing gallery data to disk.')
        info_dict = {}
        open_as = 'w'
        
        # Try to avoid redundancy
        if os.path.exists(os.path.abspath('/'.join([outdir, 'info.txt']))):
            with open('/'.join([outdir, 'info.txt']), 'r') as f:
                try:
                    info_dict = json.load(f)
                except ValueError:  # Probably failed to decode json
                    open_as = 'a'
                    logging.info('Failed to open info file. Appending new content without redundancy checks.')
        
        info_dict[generate_name_from_url(url)]  = {'url': url, 'size': len(images), 'title': page_title, 'updated': datetime.now().isoformat()}
        
        with open('/'.join([outdir, 'info.txt']), open_as) as f:
            f.write(json.dumps(info_dict, indent=4).encode('utf-8'))

    logging.info('Finished scraping <%s>.', url)

if __name__ == '__main__':
    args = docopt(__doc__, version = 'galleryscraper.py version: %s' % __version__)

    # Set up some logging
    _logme('/'.join(['scrape', generate_name_from_url(args['URL'])]), args['--log-level'], console = not args['--quiet'])

    # Perform the actual gallery scrape
    scrape_gallery(args['URL'], 'out/' + args['DIR'], overwrite = not args['--skip-duplicates'], threads = int(args['--threads']))
