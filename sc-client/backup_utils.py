from datetime import datetime, timedelta
from os import walk
from time import sleep
import pathlib

import socket

#TODO: change all prints to logging
#TODO: change client to log locally and maybe send logs to remote?
#      opt out of this maybe?
import logging

import crypto_utils

#connection port for file backup
#TODO: maybe have the server use multiple ports for clients?
#idea: clients could first reach out to the "request port" which would ask the server
#for a port to communicate on for the transfers, and then it could go from there
CONNECTION_PORT = 8083
CONNECTION_SERVER = "www2.darkage.io"

HEADER_PORTION_CLIENT_LEN = 16
HEADER_PORTION_PATH_LEN   = 512
HEADER_PORTION_SIZE_LEN   = 32

#I love you, T :)
DELIMITER="~||~TWT~||~"

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

    print("PREVIOUS RUN: %s" % previous_run_time)
    print("BACKUP TIME: %s" % datetime_of_backup)
    print("CURRENT RUN: %s" % current_run_time)

    if previous_run_time < datetime_of_backup and current_run_time > datetime_of_backup:
        return True
    else:
        return False

def perform_backup(paths,client_id):
    print("Beginning backup!")
    for path in paths.split(","):
        print("==   %s   ==" % path)
        path_obj = pathlib.Path(path)

        #TODO: find a way to do this recursively
        if path_obj.is_file():
            print("%s is a file" % path)
            process_file(path_obj,client_id)

        elif path_obj.is_dir():
            print("%s is a dir" % path)
            #[d for d in path_obj.iterdir() if d.is_dir()] ??? <- handle dirs so it keeps going into subdirs
            for file_obj in [p for p in path_obj.iterdir() if p.is_file()]:
                process_file(file_obj,client_id)

def process_file(file_path_obj,client_id):
    status = check_hash_db(file_path_obj)

    if status == BACKUP_STATUS_NO_CHANGE:
        print("no change to file, continuing")
        return

    elif status == BACKUP_STATUS_CHANGE:
        if not verify_file_integrity(file_path_obj):
            print("WARNING: FILE INTEGRITY CHECK FAILED!!!")
        else: 
            print("proceeding to backup file %s" %file_path_obj.name)

            file_path = file_path_obj.resolve()
            file_content = file_path_obj.read_bytes()
            file_size = file_path_obj.stat().st_size
        
            ship_file_to_server(client_id,file_path,file_content,file_size)

def ship_file_to_server(client_id,path,content,size):
    encrypted_content, encrypted_size = crypto_utils.encrypt_file(path)

    sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    server_address = (CONNECTION_SERVER,CONNECTION_PORT)

    print("connecting to %s port %s" % server_address)
    sock.connect(server_address)
    try:
        dump_file_info(path,size,encrypted_size)
        message = wrap_file_for_delivery(client_id,path,encrypted_content,encrypted_size)
        sock.sendall(message)

        #TODO: server response to client??
        #maybe respond with hash as verification check?
        #or is the security of tcp enough?

    finally:
        print("closing socket")
        sock.close()

    sleep(3)

def wrap_file_for_delivery(client_id,path,content,size):
    # PACKET STRUCTURE
    # +-----------------------------------------+
    # | HEADER       = 560 bytes                |
    # | DELIMITER    =  11 bytes                |
    # | CONTENT      =   n bytes*               |
    # | *content size defined                   |
    # |  in size field of header (offset 528)   |
    # +-----------------------------------------+
    # content begins at offset 571
    wrapped_header = wrap_header(client_id,path,size)
    return wrapped_header + DELIMITER.encode('ascii') + content

def wrap_header(client_id,path,size):
    # HEADER PACKET BREAKDOWN
    # +-----------------------------------------+
    # | client_id    -> padded to 16 bytes      |
    # | path         -> padded to 512 bytes     |
    # | size of file -> padded to 32 bytes      |
    # +-----------------------------------------+
    # Total header size: 560 bytes
    padded_client_id = pad_client_id(client_id)
    padded_path      = pad_path(path)
    padded_size      = pad_size(size)

    return padded_client_id + padded_path + padded_size

def pad_client_id(client_id):
    len_to_pad = HEADER_PORTION_CLIENT_LEN - len(str(client_id))
    print("adding %d characters to client id %s" % (len_to_pad,client_id))
    return str(client_id).encode('ascii') + ('\x00' * len_to_pad).encode('ascii')

def pad_path(path):
    len_to_pad = HEADER_PORTION_PATH_LEN - len(str(path))
    print("adding %d characters to path %s" % (len_to_pad,path))
    return str(path).encode('ascii') + ('\x00' * len_to_pad).encode('ascii')

def pad_size(size):
    len_to_pad = HEADER_PORTION_SIZE_LEN - len(str(size))
    print("adding %d characters to size %s" % (len_to_pad,size))
    return str(size).encode('ascii') + ('\x00' * len_to_pad).encode('ascii')

def dump_file_info(path,size,encrypted_size):
    print("==== SENDING FILE : INFO ====")
    print("\tPATH: %s" %path)
    print("\tSIZE: %d" %size)
    print("\tENCRYPTED SIZE: %d" %encrypted_size)

def check_hash_db(file_path_obj):
    #TODO: this function
    return 1

def verify_file_integrity(file_path_obj):
    #TODO: make sure there is no ransomware in the file, anything wrong etc.
    return 1
