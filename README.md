# Gallery Scraper

This is a simple little scraper suitable for parsing web pages that contain a "gallery" of images, finding which images on the page are likely in the gallery, following their links, and downloading the full-sized images. It requires BeautifulSoup, Requests, and Docopt, all of which are standard third-party modules.

The code is very well documented. I wrote it primarily to learn something about working with web pages in Python, and to fool around a little with the tools in the collections library, so it is full of my inline comments.

## Usage

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