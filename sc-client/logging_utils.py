from time import sleep
from datetime import datetime, timedelta
import socket
import sys
import glob
import pathlib

import logging

import crypto_utils
import network_utils

CONNECTION_PORT = 8081

def send_logfile_to_server(client_id):
    filepath = pathlib.Path(get_most_recent_logfile(client_id=client_id))    
    network_utils.ship_file_to_server(client_id,filepath,port=CONNECTION_PORT)

def get_most_recent_logfile(client_id):
    #TODO: look for all files that have name patterned client_CID*.log
    #send most recent logfile
    path = "client_%s*.log" % client_id
    all_bytes = []
    for filename in glob.glob(path):
        print("using filename %s" % filename)
        return filename

def initialize_logging(client_id):
    logging.basicConfig(
        filename='client_%s_%s.log' % (client_id,datetime.now().strftime("%Y-%m-%d")),
        filemode='a',
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.DEBUG
    )
