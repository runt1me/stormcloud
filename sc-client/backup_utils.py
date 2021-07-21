from datetime import datetime, timedelta
from os import walk
from time import sleep
import pathlib

import socket

import logging

#connection port for file backup
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
    print("\n\n\nBacking up!\n\n\n")
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
        print("proceeding to backup file %s" %file_path_obj.name)

        file_path = file_path_obj.resolve()
        file_content = file_path_obj.read_bytes()
        file_size = file_path_obj.stat().st_size
        
        ship_file_to_server(client_id,file_path,file_content,file_size)

def ship_file_to_server(client_id,path,content,size):
    sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    server_address = (CONNECTION_SERVER,CONNECTION_PORT)

    print("connecting to %s port %s" % server_address)
    sock.connect(server_address)
    try:
        print("==== SENDING FILE : INFO ====")
        print("\tPATH: %s" %path)
        print("\tSIZE: %d" %size)
        message = wrap_file_for_delivery(client_id,path,content,size)
        sock.sendall(message)

        """
        #bytes expected to be sent and recvd
        amount_recvd = 0
        amount_expected = 16

        while amount_recvd < amount_expected:
            data = sock.recv(16)
            amount_recvd += len(data)
            print("received %s" % data)
        """

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

def check_hash_db(file_path_obj):
    return 1