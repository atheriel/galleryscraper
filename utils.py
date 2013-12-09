import os
import os.path
import logging
from functools import wraps
from contextlib import contextmanager

def logme(name, level = logging.INFO, console = True):
    log_dir = '/tmp/' + name.rsplit('/', 1)[0]
    if not os.path.exists(log_dir):
        os.mkdir(log_dir)
    
    logging.basicConfig(
        filename = "/tmp/" + name + ".log",
        filemode = "w",
        level = level,
        format='[%(asctime)s][%(levelname)s] %(message)s',
        datefmt='%y-%m-%d %H:%M:%S')

    if console:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(
            fmt="[%(asctime)s][%(levelname)s] %(message)s",
            datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(console)
        console.setLevel(level)

def cache(func):
    """
    Caching decorator.
    """
    saved = {}
    @wraps(func)
    def newfunc(*args):
        if args in saved:
            return saved[args]
        result = func(*args)
        saved[args] = result
        return result
    return newfunc

@contextmanager
def ignored(*exceptions):
    """
    Simple way to minimize try...catch blocks where the exceptions don't really
    matter.
    """
    try:
        yield
    except exceptions:
        pass

def levenshtein(first, second):
    """
    The Levenshtein distance (or edit distance) between two strings 
    is the minimal number of "edit operations" required to change 
    one string into the other. The two strings can have different 
    lengths. There are three kinds of "edit operations": deletion, 
    insertion, or alteration of a character in either string.

    Example: the Levenshtein distance of "ag-tcc" and "cgctca" is 3.
    source: http://en.wikibooks.org/wiki/Algorithm_implementation/Strings/Levenshtein_distance#Python
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
