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

def send_logs_to_server(client_id):
    #random note
    #make sure that there isnt an issue with initializing logging
    #creating new files and then immediately sending them up as blank files
    #and deleting them immediately
    logfiles_list = get_logfiles(client_id=client_id)
    for logfile in logfiles_list:
        filepath = pathlib.Path(logfile)    
        network_utils.ship_file_to_server(client_id,filepath,port=LOGGING_PORT)
        os.remove(logfile)

def get_logfiles(client_id):
    return glob.glob("client_%s*.log" % client_id)

def initialize_logging(client_id):
    logging.basicConfig(
        filename='client_%s_%s.log' % (client_id,datetime.now().strftime("%Y-%m-%d")),
        filemode='a',
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.DEBUG
    )
