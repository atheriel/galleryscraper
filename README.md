# Gallery Scraper

This is a simple little scraper suitable for parsing web pages that contain a "gallery" of images, finding which images on the page are likely in the gallery, following their links, and downloading the full-sized images. It requires BeautifulSoup and Requests, both of which are standard third-party modules.

The code is very well documented. I wrote it primarily to learn something about working with web pages in Python, and to fool around a little with the tools in the collections library, so it is full of my inline comments.

## Usage

galleryscraper.py URL [DIRECTORY]