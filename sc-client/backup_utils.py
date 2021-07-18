from datetime import datetime, timedelta
from os import walk
import pathlib

import socket

import logging

#connection port for file backup
CONNECTION_PORT = 8081
CONNECTION_SERVER = "www2.darkage.io"

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

        if path_obj.is_file():
            print("%s is a file" % path)
            process_file(path_obj,client_id)

        elif path_obj.is_dir():
            print("%s is a dir" % path)
            for file_obj in [p for p in path_obj.iterdir() if p.is_file()]:
                process_file(file_obj,client_id)

        dirns = []
        for (dirpath, dirnames, filenames) in walk(path):
            dirns.extend(dirnames)
            break

        for dirn in dirns:
            print("dir: %s" % dirn)


def process_file(file_path_obj,client_id):
    status = check_hash_db(file_path_obj)

    if status == BACKUP_STATUS_NO_CHANGE:
        print("no change to file, continuing")
        return

    elif status == BACKUP_STATUS_CHANGE:
        print("proceeding to backup file %s" %file_path_obj.name)

        file_name = file_path_obj.name
        file_path = file_path_obj.resolve()
        file_content = file_path_obj.read_bytes()
        file_size = file_path_obj.stat().st_size
        
        ship_file_to_server(client_id,file_name,file_path,file_content,file_size)

def ship_file_to_server(client_id,name,path,content,size):
    sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    server_address = (CONNECTION_SERVER,CONNECTION_PORT)

    print("connecting to %s port %s" % server_address)
    sock.connect(server_address)
    try:
        print("==== SENDING FILE : INFO ====")
        print("\t%sNAME: %s" %name)
        print("\t%sPATH: %s" %path)
        print("\t%sSIZE: %s" %size)
        message = wrap_file_for_delivery(client_id,name,path,content,size)
        #sock.sendall(message)

        #bytes expected to be sent and recvd
        amount_recvd = 0
        amount_expected = 16

        while amount_recvd < amount_expected:
            data = sock.recv(16)
            amount_recvd += len(data)
            print("received %s" % data)

    finally:
        print("closing socket")
        sock.close()

    sleep(interval)

def wrap_file_for_delivery(client_id,name,path,content,size):
    return b'%d,%s,%s,%d,%b' % (client_id,name,path,size,content)
    

def check_hash_db(file_path_obj):
    return 1