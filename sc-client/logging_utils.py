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

def send_logs_to_server(api_key,agent_id,secret_key):
    logfiles_list = get_logfiles(uuid=agent_id)
    for logfile in logfiles_list:
        filepath = pathlib.Path(logfile)
        ret = network_utils.ship_file_to_server(api_key,agent_id,secret_key,filepath)

        if ret == 0:
            os.remove(logfile)
        else:
            print("Failed to send logfile.")

def get_logfiles(uuid):
    return glob.glob("%s*.log" % uuid)

def initialize_logging(uuid):
    logging.basicConfig(
        filename='%s_%s.log' % (uuid,datetime.now().strftime("%Y-%m-%d")),
        filemode='a',
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.DEBUG,
        force=True
    )
