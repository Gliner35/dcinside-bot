import random
import time
import os
import logging

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(debug=False, log_file=None):
    level = logging.DEBUG if debug else logging.INFO
    handlers = []
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    handlers.append(console)
    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        handlers.append(fh)
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=DATE_FORMAT, handlers=handlers)
    return logging.getLogger("dcbot")


def jitter_sleep(a, b):
    time.sleep(random.uniform(a, b))