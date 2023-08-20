import logging
import sys

logger = None

def initialize_logging():
    global logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # Using sys.stdout to appear in the WSGI logs.
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(levelname)-8s %(message)s')
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger
