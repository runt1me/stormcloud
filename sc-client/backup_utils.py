from datetime import datetime, timedelta
from os import walk
from time import sleep
import pathlib

import socket
import logging

import crypto_utils
import network_utils

#return codes for checking hash db
BACKUP_STATUS_NO_CHANGE = 0
BACKUP_STATUS_CHANGE    = 1

def check_for_backup(backup_time,current_run_time,previous_run_time):
    datetime_of_backup = datetime(
        year=datetime.now().year,
        month=datetime.now().month,
        day=datetime.now().day,
        hour=backup_time,
        minute=0,
        second=0
    )

    logging.log(logging.INFO,"PREVIOUS RUN: %s" % previous_run_time)
    logging.log(logging.INFO,"BACKUP TIME: %s" % datetime_of_backup)
    logging.log(logging.INFO,"CURRENT RUN: %s" % current_run_time)

    if previous_run_time < datetime_of_backup and current_run_time > datetime_of_backup:
        return True
    else:
        return False

def perform_backup(paths,api_key,agent_id):
    logging.log(logging.INFO,"Beginning backup!")
    for path in paths.split(","):
        logging.log(logging.INFO,"==   %s   ==" % path)
        path_obj = pathlib.Path(path)

        #TODO: find a way to do this recursively
        if path_obj.is_file():
            logging.log(logging.INFO,"%s is a file" % path)
            process_file(path_obj,api_key,agent_id)

        elif path_obj.is_dir():
            logging.log(logging.INFO,"%s is a dir" % path)
            #[d for d in path_obj.iterdir() if d.is_dir()] ??? <- handle dirs so it keeps going into subdirs
            for file_obj in [p for p in path_obj.iterdir() if p.is_file()]:
                process_file(file_obj,api_key,agent_id)

def process_file(file_path_obj,api_key,agent_id):
    status = check_hash_db(file_path_obj)

    if status == BACKUP_STATUS_NO_CHANGE:
        logging.log(logging.INFO,"no change to file, continuing")
        return

    elif status == BACKUP_STATUS_CHANGE:
        if not verify_file_integrity(file_path_obj):
            logging.log(logging.WARNING,"File integrity check failed for file %s." %file_path_obj)
            return
        else:
            logging.log(logging.INFO,"proceeding to backup file %s" %file_path_obj.name)

            file_path = file_path_obj.resolve()
            file_content = file_path_obj.read_bytes()
            file_size = file_path_obj.stat().st_size
        
            network_utils.ship_file_to_server(api_key,agent_id,file_path)

def dump_file_info(path,size,encrypted_size):
    logging.log(logging.INFO,"==== SENDING FILE : INFO ====")
    logging.log(logging.INFO,"\tPATH: %s" %path)
    logging.log(logging.INFO,"\tSIZE: %d" %size)
    logging.log(logging.INFO,"\tENCRYPTED SIZE: %d" %encrypted_size)

def check_hash_db(file_path_obj):
    #TODO: this function
    return 1

def verify_file_integrity(file_path_obj):
    #TODO: make sure there is no ransomware in the file, anything wrong etc.
    return 1
