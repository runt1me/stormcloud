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

def send_logs_to_server(api_key,agent_id):
    #TODO: fix issue with logs not getting written if a logfile already exists at program startup
    logfiles_list = get_logfiles(uuid=agent_id)
    for logfile in logfiles_list:
        print("Shipping logfile: %s" % logfile)
        filepath = pathlib.Path(logfile)    
        network_utils.ship_file_to_server(api_key,agent_id,filepath)

        print("Removing logfile: %s" % logfile)
        os.remove(logfile)

def get_logfiles(uuid):
    return glob.glob("%s*.log" % uuid)

def initialize_logging(uuid):
    print("Creating new logfile.")
    logging.basicConfig(
        filename='%s_%s.log' % (uuid,datetime.now().strftime("%Y-%m-%d")),
        filemode='a',
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.DEBUG
    )
