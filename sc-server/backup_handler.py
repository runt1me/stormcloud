import socket
import sys
from datetime import datetime
import argparse

import logging
import database_utils as db

from cryptography.fernet import Fernet

#packet data constants
HEADER_SIZE_BYTES=560

#offsets in the packet
CLIENT_FIELD_END_POS=16
FILE_PATH_FIELD_END_POS=528
LENGTH_FIELD_END_POS=560

def main(LISTEN_PORT):
    initialize_logging()
    sock = initialize_socket(LISTEN_PORT)

    sock.listen(1)
    while True:
        logging.log(logging.INFO, "Listening for connections...")
        connection, client_address = sock.accept()

        logging.log(logging.INFO, "connection %s: %s" % (connection,client_address))
        header = connection.recv(HEADER_SIZE_BYTES)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if header:
            print("entire header: %s" % header)
            client = get_client_id(header[0:CLIENT_FIELD_END_POS])
            file_path = get_file_path(client,header[CLIENT_FIELD_END_POS:FILE_PATH_FIELD_END_POS])
            length = get_content_length(header[FILE_PATH_FIELD_END_POS:LENGTH_FIELD_END_POS])

            logging.log(logging.INFO,'Receiving file from client %d' % client)
            logging.log(logging.INFO, file_path)

        check_result = perform_integrity_check_delimiter(connection.recv(11))
        if check_result:
            logging.log(logging.INFO,"delimiter validated, continuing")
        else:
            logging.log(logging.INFO,"invalid delimiter")

        bytes_to_receive = length
        raw_content = b''

        while bytes_to_receive > 0:
            bytes_recvd = connection.recv(bytes_to_receive)
            raw_content += bytes_recvd
            if raw_content:
                logging.log(logging.INFO,"(Received %d bytes)" % len(bytes_recvd))

            bytes_to_receive = bytes_to_receive - len(bytes_recvd)

        store_file(client,file_path,length,raw_content)

def get_content_length(length_field):
    #replace null characters with '' for the purpose of converting string -> int
    length_field_as_string = length_field.decode('ascii').replace('\x00','')
    return int(length_field_as_string)

def get_file_path(client_id,path_field):
    #path,_ = decrypt_msg(client_id,path_field)
    return path_field.decode('ascii').replace('\x00','')

def get_client_id(client_id_field):
    client_id_as_string = client_id_field.decode('ascii').replace('\x00','')
    return int(client_id_as_string)

def store_file(client_id,file_path,file_length,file_raw_content):
    decrypted_raw_content, decrypted_length = decrypt_file(client_id,file_length,file_raw_content)

    logging.log(logging.INFO,"== STORING FILE : %s ==" %file_path)
    logging.log(logging.INFO,"Client ID:\t%d" % client_id)
    logging.log(logging.INFO,"File Length:\t%d" % decrypted_length)

    #TODO: check and authenticate that its a legitimate client id
    #to prevent against spoofed packets and attacks
    #encryption should help with this, but also should have a 2-factor key
    #RSA style??
    client_id_root_folder = "/storage/%d/" % client_id

    #TODO: figure out a way to manage the directory structure so that the hierarchy is preserved
    #for now i am stripping out the directory structure and just doing the filename
    file_path_stripped = file_path.split("\\")[-1]
    path_on_server = client_id_root_folder + file_path_stripped

    logging.log(logging.INFO,"writing content to %s" % path_on_server)
    with open(path_on_server,'wb') as outfile:
        outfile.write(decrypted_raw_content)

def decrypt_file(client_id,file_length,file_raw_content):
    print(file_raw_content)
    print(type(file_raw_content))

    f = get_fernet(client_id)
    decrypted = f.decrypt(file_raw_content)

    return decrypted, len(decrypted)

def decrypt_msg(client_id,msg_encrypted):
    raw_msg = b''
    raw_msg += msg_encrypted

    print(msg_encrypted)
    print(type(msg_encrypted))
    print(len(msg_encrypted))

    f = get_fernet(client_id)

    print(f)
    print(client_id)
    decrypted = f.decrypt(raw_msg)

    return decrypted, len(decrypted)

def get_fernet(client_id):
    path_to_client_key = "/keys/%d/secret.key" % client_id
    with open(path_to_client_key,'rb') as keyfile:
        key = keyfile.read()

    return Fernet(key)

def perform_integrity_check_delimiter(delim):
    logging.log(logging.INFO,"%s (type %s)" % (delim,type(delim)))
    return delim == b'~||~TWT~||~'

def initialize_logging():
    logging.basicConfig(
            filename='/var/log/stormcloud.log',
            filemode='a',
            format='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=logging.DEBUG
    )

def initialize_socket(LISTEN_PORT):
    addr = ("", LISTEN_PORT)
    sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)

    sock.bind(addr)
    return sock

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int, help="port to listen on for backup handling")
    args = parser.parse_args()

    main(args.port)
