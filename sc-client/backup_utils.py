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

def perform_backup(paths,paths_recursive,api_key,agent_id,dbconn,ignore_hash):
    logging.log(logging.INFO,"Beginning backup!")
    logging.log(logging.INFO,"Ignoring the hash database and attempting to force backup of files.")

    process_paths_nonrecursive(paths,api_key,agent_id,dbconn,ignore_hash)
    process_paths_recursive(paths_recursive,api_key,agent_id,dbconn,ignore_hash)

def process_paths_nonrecursive(paths,api_key,agent_id,dbconn,ignore_hash):
    for path in paths:
        logging.log(logging.INFO,"==   %s   ==" % path)
        path_obj = pathlib.Path(path)

        if path_obj.is_file():
            process_file(path_obj,api_key,agent_id,dbconn,ignore_hash)

        elif path_obj.is_dir():
            for file_obj in [p for p in path_obj.iterdir() if p.is_file()]:
                process_file(file_obj,api_key,agent_id,dbconn,ignore_hash)

def process_paths_recursive(paths,api_key,agent_id,dbconn,ignore_hash):
    for path in paths:
        logging.log(logging.INFO, "==   %s (-R)  ==" % path)
        path_obj = pathlib.Path(path)

        process_one_path_recursive(path_obj,api_key,agent_id,dbconn,ignore_hash)

def process_one_path_recursive(target_path,api_key,agent_id,dbconn,ignore_hash):
    for file in target_path.iterdir():
        if file.is_dir():
            process_one_path_recursive(file,api_key,agent_id,dbconn,ignore_hash)
        else:
            process_file(file,api_key,agent_id,dbconn,ignore_hash)

def process_file(file_path_obj,api_key,agent_id,dbconn,ignore_hash):
    if not ignore_hash:
        status = check_hash_db(file_path_obj,dbconn)
    else:
        status = BACKUP_STATUS_CHANGE

    if status == BACKUP_STATUS_NO_CHANGE:
        logging.log(logging.INFO,"no change to file, continuing")

    elif status == BACKUP_STATUS_CHANGE:
        if not verify_file_integrity(file_path_obj):
            logging.log(logging.WARNING,"File integrity check failed for file %s." %file_path_obj)
        else:
            logging.log(logging.INFO,"Backing up file: %s" %file_path_obj.name)

            ret = network_utils.ship_file_to_server(api_key,agent_id,file_path_obj.resolve())
            if ret == 0:
                update_hash_db(file_path_obj, dbconn)
            else:
                logging.log(logging.WARNING, "Did not receive success code from server when trying to backup file, so not updating hash db.")

def dump_file_info(path,size,encrypted_size):
    logging.log(logging.INFO,"==== SENDING FILE : INFO ====")
    logging.log(logging.INFO,"\tPATH: %s" %path)
    logging.log(logging.INFO,"\tSIZE: %d" %size)
    logging.log(logging.INFO,"\tENCRYPTED SIZE: %d" %encrypted_size)

def check_hash_db(file_path_obj,conn):
    cursor = conn.cursor()
    file_path = str(file_path_obj)

    results = is_file_in_db(file_path, cursor)
    
    if not results:
        logging.log(logging.INFO,"Could not find file in hash database.")
        return BACKUP_STATUS_CHANGE

    else:
        file_name, md5_from_db = results[0]
        logging.log(logging.INFO,"== %s == " % file_name)
        logging.log(logging.INFO,"Got md5 from database: %s" % md5_from_db)

        current_md5 = get_md5_hash(file_path)
        logging.log(logging.INFO,"Got md5 hash from file: %s" % current_md5)

        if md5_from_db == current_md5:
            return BACKUP_STATUS_NO_CHANGE
        else:
            return BACKUP_STATUS_CHANGE

def update_hash_db(file_path_obj,conn):
    cursor      = conn.cursor()
    file_path   = str(file_path_obj)
    results     = is_file_in_db(file_path, cursor)
    md5         = get_md5_hash(file_path)

    if not results:
        insert_into_hash_db(md5, file_path, conn, cursor)
    else:
        update_hash_in_db(md5, file_path, conn, cursor)

    logging.log(logging.INFO, "Updated file hash in database.")

def insert_into_hash_db(md5, file_path, conn, cursor):
    cursor.execute('''INSERT INTO files (file_name, md5) VALUES (?,?)''',(file_path,md5)) 
    conn.commit()

def update_hash_in_db(md5, file_path, conn, cursor):
    cursor.execute('''UPDATE files SET md5 = ? WHERE file_name = ?''',(md5,file_path))
    conn.commit()

def is_file_in_db(file_path, cursor):
    cursor.execute('''SELECT file_name,md5 FROM files WHERE file_name = ?;''', (file_path,))
    return cursor.fetchall()

def get_md5_hash(path_to_file):
    # TODO: handle permission denied errors
    # Reads in chunks to limit memory footprint
    with open(path_to_file, "rb") as f:
        file_hash = hashlib.md5()
        while chunk := f.read(8192):
            file_hash.update(chunk)

    return file_hash.hexdigest()

def verify_file_integrity(file_path_obj):
    #TODO: make sure there is no ransomware in the file, anything wrong etc.
    return 1
