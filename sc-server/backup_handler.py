import socket
import sys
from datetime import datetime
import argparse

import logging
import database_utils as db

from cryptography.fernet import Fernet

def main(LISTEN_PORT):
    initialize_logging()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    context.load_cert_chain(certfile="/root/certs/cert.pem")

    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.bind(('0.0.0.0',BIND_PORT))
    s.listen(5)

    try:
        while True:
            # TODO: use actual signed cert for SSL
            # and use TLS 1.3
            connection, client_address = s.accept()
            wrappedSocket = ssl.wrap_socket(
                    connection,
                    server_side=True,
                    certfile="/root/certs/cert.pem",
                    keyfile="/root/certs/cert.pem",
                    ssl_version=ssl.PROTOCOL_TLS
            )
    
            request = recv_json_until_eol(wrappedSocket)
    
            if request:
              ret_code, response_data = handle_request(request)
              # Send the length of the serialized data first, then send the data
              # wrappedSocket.send(bytes('%d\n',encoding="utf-8") % len(response_data))
              wrappedSocket.sendall(bytes(response_data,encoding="utf-8"))

            else:
                break
    finally:
        wrappedSocket.close()


def recv_json_until_eol(socket):
    # Borrowed from https://github.com/mdebbar/jsonsocket

    # read the length of the data, letter by letter until we reach EOL
    length_bytes = bytearray()
    char = socket.recv(1)
    while char != bytes('\n',encoding="UTF-8"):
      length_bytes += char

      char = socket.recv(1)
    total = int(length_bytes)

    # use a memoryview to receive the data chunk by chunk efficiently
    view = memoryview(bytearray(total))
    next_offset = 0
    while total - next_offset > 0:
      recv_size = socket.recv_into(view[next_offset:], total - next_offset)
      next_offset += recv_size

    try:
      deserialized = json.loads(view.tobytes())
    except (TypeError, ValueError) as e:
      # TODO: Send error code back to client
      raise Exception('Data received was not in JSON format')

    return deserialized




def handle_request(request):

    print(request)

    if 'request_type' not in request.keys():
        return -1,json.dumps({'response':'Bad request.'})
    if 'api_key' not in request.keys():
        return -1,json.dumps({'response':'Unable to authorize request (no api key presented)'})

    if request['request_type'] == 'Hello':
        ret_code, response_data = handle_hello_request(request)
    elif request['request_type'] == 'register_new_device':
        ret_code, response_data = handle_register_new_device_request(request)

    return ret_code, response_data

    store_file(client,file_path,length,raw_content)



def store_file(client_id,file_path,file_length,file_raw_content):
    decrypted_raw_content, decrypted_length = decrypt_file(client_id,file_length,file_raw_content)

    logging.log(logging.INFO,"== STORING FILE : %s ==" %file_path)
    logging.log(logging.INFO,"Client ID:\t%d" % client_id)
    logging.log(logging.INFO,"File Length:\t%d" % decrypted_length)

    #TODO: check and authenticate that its a legitimate client id
    #TODO: customer id and device id in backup data packets
    client_id_root_folder = "/storage/%d/" % client_id

    #TODO: figure out a way to manage the directory structure so that the hierarchy is preserved
    #for now i am stripping out the directory structure and just doing the filename
    file_path_stripped = file_path.split("\\")[-1]
    path_on_server = client_id_root_folder + file_path_stripped

    logging.log(logging.INFO,"writing content to %s" % path_on_server)
    with open(path_on_server,'wb') as outfile:
        outfile.write(decrypted_raw_content)

def decrypt_file(client_id,file_length,file_raw_content):
    f = get_fernet(client_id)
    decrypted = f.decrypt(file_raw_content)

    return decrypted, len(decrypted)

def decrypt_msg(client_id,raw_msg):
    #converts raw_msg (which is a byte string) to a byte array with \x00 (null bytes) removed
    raw_stripped_as_list = [i.to_bytes(1,sys.byteorder) for i in raw_msg if i.to_bytes(1,sys.byteorder)!=b'\x00']

    #strip the b'' and convert raw_stripped_as_list back to a bytestring
    raw_stripped = b''.join(raw_stripped_as_list[2:-1])

    f = get_fernet(client_id)
    decrypted = f.decrypt(raw_stripped)

    return decrypted, len(decrypted)

def get_fernet(client_id):
    path_to_client_key = "/keys/%d/secret.key" % client_id
    with open(path_to_client_key,'rb') as keyfile:
        key = keyfile.read()

    return Fernet(key)

def initialize_logging():
    logging.basicConfig(
            filename='/var/log/stormcloud.log',
            filemode='a',
            format='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=logging.DEBUG
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int, help="port to listen on for backup handling")
    args = parser.parse_args()

    main(args.port)
