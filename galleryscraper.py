# Standard library modules
import os
import os.path
import time
import sys
import zlib
import logging
import urlparse
from collections import (namedtuple, defaultdict)

# 3rd party modules
import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup

# Internal
import utils


def generate_name_from_url(url):
    """
    Generate a hexidecimal hash of the page name, so multiple galleries can be
    stored in one folder. Note that this is a deterministic process, so that
    one may 'retry' a scrape without duplicating images.

    The number of collisions should be more than low enough for this particular
    application, around 1 in 2^32 - 1.
    """
    return '%4x' % (zlib.crc32(url) & 0xffffffff)


def safe_request(url, type = 'get', **kwargs):
    """
    Wraps requests to retry after a timeout. This is quite useful, since many
    people do not like web scrapers, and drop the connection if they receive
    rapid get requests.
    """
    try:
        return getattr(session, type)(url, timeout = 3.0, **kwargs)
    except Exception as e:
        logging.info('Request timeout for <%s> with exception <%s>. Sleeping for 10s before retry.', url, str(e))
        time.sleep(10)
        return safe_request(url, type, **kwargs)


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
        page_title = soup.head.title.contents[0]
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
        if utils.levenshtein(last, line) > 10:  # Strings are too dissimilar
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
        is_image, link_dim = image_check(src)
        if not is_image:
            logging.debug('Non-image file as source for image at <%s>.', src)
        else:
            logging.debug('Image with content length %d found at <%s>.', link_dim, src)
            if link_dim > dims:
                dims = link_dim
                biggest_image = urlparse.urljoin(url, link['src'])

    return biggest_image


@utils.cache
def image_check(url):
    """
    Checks if the file at the given url is an image, no matter its actual
    extension. Often banners on one part of the site will share the same url,
    so we cache the result to save rechecking them.
    """
    ImageCheckResult = namedtuple('ImageCheckResult', ['is_image', 'bytes'])

    page, size = safe_request(url, type = 'head'), 0

    # Sometimes, the pages just don't have a content-length; ignore these
    with utils.ignored(KeyError):
        size = int(page.headers['content-length'])

    return ImageCheckResult(True, size) if 'image' in page.headers['content-type'] else ImageCheckResult(False, size)


def download_image(url, filename):
    """
    Downloads the image at the given url and writes it to filename.
    """
    filename += '.' + urlparse.urlparse(url).path.rsplit('.', 1)[1]  # Add the extension

    logging.info('Downloading image from <%s> to file %s.', url, filename)

    req = safe_request(url, stream = True)
    assert req.status_code == 200

    with open(filename, 'wb') as f:
        for chunk in req.iter_content(1024):
            f.write(chunk)


def scrape_gallery(url, outdir = 'out', include_info = True):
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

    for count, link in enumerate(images):
        try:
            parent = thumbnail_map[link]

            if image_check(parent).is_image:
                download_image(parent, '-'.join([filename_prefix, str(count)]))
                continue

            logging.info('Finding largest image on <%s>...', parent)
            biggest_image = find_largest_image_on_page(parent)
            download_image(biggest_image, '-'.join([filename_prefix, str(count)]))

        except KeyError:  # It's not a thumbnail
            download_image(link, '-'.join([filename_prefix, str(count)]))

    # Create info header and write it to a text file
    if include_info:
        info_text = u'Gallery identifier: %(hash)s\nRetrieved from <%(url)s>\nTitle: %(title)s\nTotal images: %(size)d\n\n'
        info_text = info_text % {'hash': generate_name_from_url(url), 'url': url, 'size': len(images), 'title': page_title}

        with open('/'.join([outdir, 'info.txt']), 'a') as f:
            f.write(info_text.encode('utf-8'))

url = sys.argv[1]
custom_dir = sys.argv[2]
session = requests.Session()
session.mount('http://', HTTPAdapter(max_retries=5))
session.headers['User-Agent'] = 'Mozilla/5.0 (Windows; U; Windows NT 5.1; it; rv:1.8.1.11) Gecko/20071127 Firefox/2.0.0.11'

# Set up some logging
# Use logging.DEBUG to, well, debug
# Use console = True to see output on the console
utils.logme('/'.join(['scrape', generate_name_from_url(url)]), logging.INFO, console = False)

scrape_gallery(url, 'out/' + custom_dir)
