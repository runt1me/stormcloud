from time import sleep
from datetime import datetime, timedelta
import socket
import sys
import os
import glob
import pathlib

import logging

import crypto_utils
import network_utils

LOGGING_PORT = 8081

def send_logs_to_server(uuid):
    #random note
    #make sure that there isnt an issue with initializing logging
    #creating new files and then immediately sending them up as blank files
    #and deleting them immediately
    logfiles_list = get_logfiles(uuid=uuid)
    for logfile in logfiles_list:
        filepath = pathlib.Path(logfile)    
        network_utils.ship_file_to_server(uuid,filepath,port=LOGGING_PORT)
        os.remove(logfile)

def get_logfiles(uuid):
    return glob.glob("%s*.log" % uuid)

def initialize_logging(uuid):
    logging.basicConfig(
        filename='%s_%s.log' % (uuid,datetime.now().strftime("%Y-%m-%d")),
        filemode='a',
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.DEBUG
    )
