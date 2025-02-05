from datetime import datetime
import os
import glob
import pathlib

import logging

import network_utils

def send_logs_to_server(api_key,agent_id):
    logfiles_list = get_logfiles(uuid=agent_id)
    for logfile in logfiles_list:
        filepath = pathlib.Path(logfile)
        ret = network_utils.ship_file_to_server(api_key,agent_id,filepath)

        if ret == 200:
            os.remove(logfile)
        else:
            print("Failed to send logfile.")

def get_logfiles(uuid):
    return glob.glob("%s*.log" % uuid)

def initialize_logging(cwd, uuid):
    log_file_directory = cwd
    log_file_name = '%s_%s.log' % (uuid,datetime.now().strftime("%Y-%m-%d"))

    # Ensure log_file_directory ends with \\
    if not log_file_directory.endswith("\\"):
        log_file_directory += "\\"

    log_file_path = log_file_directory + log_file_name

    logging.basicConfig(
        filename=log_file_path,
        filemode='a',
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.DEBUG,
        force=True
    )
