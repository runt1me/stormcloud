# Requires Python 3.8!

from datetime import datetime, timedelta
from os import walk
from time import sleep

import pathlib
import hashlib

import socket
import logging

import crypto_utils
import network_utils

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

def perform_backup(paths,api_key,agent_id,dbconn):
    logging.log(logging.INFO,"Beginning backup!")
    for path in paths:
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
                process_file(file_obj,api_key,agent_id,dbconn)

def process_file(file_path_obj,api_key,agent_id,dbconn):
    status = check_hash_db(file_path_obj,dbconn)

    if status == BACKUP_STATUS_NO_CHANGE:
        logging.log(logging.INFO,"no change to file, continuing")
        return

    elif status == BACKUP_STATUS_CHANGE:
        if not verify_file_integrity(file_path_obj):
            logging.log(logging.WARNING,"File integrity check failed for file %s." %file_path_obj)
            return
        else:
            logging.log(logging.INFO,"proceeding to backup file %s" %file_path_obj.name)
            
            network_utils.ship_file_to_server(api_key,agent_id,file_path_obj.resolve())

def dump_file_info(path,size,encrypted_size):
    logging.log(logging.INFO,"==== SENDING FILE : INFO ====")
    logging.log(logging.INFO,"\tPATH: %s" %path)
    logging.log(logging.INFO,"\tSIZE: %d" %size)
    logging.log(logging.INFO,"\tENCRYPTED SIZE: %d" %encrypted_size)

def check_hash_db(file_path_obj,conn):
    # Returns 1 --> file is either new or changed, update the database and send to server
    # Returns 0 --> file has not changed from previous, no need to send to the server
    cursor = conn.cursor()
    file_path = str(file_path_obj)

    cursor.execute('''SELECT file_name,md5 FROM files WHERE file_name = ?;''', (file_path,))

    results = cursor.fetchall()
    if not results:
        logging.log(logging.INFO,"Could not find file in hash database, creating.")

        cursor.execute('''INSERT INTO files (file_name, md5) VALUES (?,?)''',(file_path,get_md5_hash(file_path))) 
        conn.commit()

    else:
        file_name, md5_from_db = results[0]
        logging.log(logging.INFO,"== %s == " % file_name)
        logging.log(logging.INFO,"Got md5 from database: %s" % md5_from_db)

        current_md5 = get_md5_hash(file_path)
        logging.log(logging.INFO,"Got md5 hash from file: %s" % current_md5)

        if md5_from_db == current_md5:
            return 0
        else:
            logging.log(logging.INFO,"Updating md5 in database.")
            cursor.execute('''UPDATE files SET md5 = ? WHERE file_name = ?''',(current_md5,file_path))
            conn.commit()

    return 1

def get_md5_hash(path_to_file):
    # Reads in chunks to limit memory footprint
    with open(path_to_file, "rb") as f:
        file_hash = hashlib.md5()
        while chunk := f.read(8192):
            file_hash.update(chunk)

    return file_hash.hexdigest()

def verify_file_integrity(file_path_obj):
    #TODO: make sure there is no ransomware in the file, anything wrong etc.
    return 1
