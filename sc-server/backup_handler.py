import socket, ssl
import sys
from datetime import datetime
import argparse
import pathlib
import logging
import os
import json

import database_utils as db
import network_utils  as scnet
import crypto_utils

def main(LISTEN_PORT):
    initialize_logging()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    context.load_cert_chain(certfile="/root/certs/cert.pem")

    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.bind(('0.0.0.0',LISTEN_PORT))
    s.listen(5)

    print('Listening for connections')

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
    
            request = scnet.recv_json_until_eol(wrappedSocket)
    
            if request:
              ret_code, response_data = handle_request(request)
              # Send the length of the serialized data first, then send the data
              # wrappedSocket.send(bytes('%d\n',encoding="utf-8") % len(response_data))
              wrappedSocket.sendall(bytes(response_data,encoding="utf-8"))

            else:
                break
    finally:
        wrappedSocket.close()

def handle_request(request):
    if 'request_type' not in request.keys():
        return -1,json.dumps({'response':'Bad request.'})
    if 'api_key' not in request.keys():
        return -1,json.dumps({'response':'Unable to authorize request (no api key presented)'})

    if request['request_type'] == 'backup_file':
        ret_code, response_data = handle_backup_file_request(request)

    return ret_code, response_data

def handle_backup_file_request(request):
    print_request_no_file(request)

    # Query database to verify API key
    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 1,json.dumps({'response': 'Could not find Customer associated with API key.'})

    # Query database to verify agent ID and get device ID
    results = db.get_device_by_agent_id(request['agent_id'])
    if not results:
        return 1,json.dumps({'response': 'Could not find device associated with Agent ID.'})

    device_id,_,_,_,_,_,_,_,path_to_device_secret_key,_ = results
    print("got device id %s and path %s" % (device_id,path_to_device_secret_key))

    store_file(
        customer_id,
        device_id,
        path_to_device_secret_key,
        request['file_path'].encode("utf-8"),
        request['file_content'].encode("utf-8")
    )

    # Add file metadata record to database

def store_file(customer_id,device_id,path_to_device_secret_key,file_path,file_raw_content):
    decrypted_raw_content, _ = crypto_utils.decrypt_msg(path_to_device_secret_key,file_raw_content,decode=False)
    decrypted_path, _        = crypto_utils.decrypt_msg(path_to_device_secret_key,file_path,decode=True)

    path_on_server = get_server_path(customer_id,device_id,decrypted_path)
    write_file_to_disk(path_on_server,decrypted_raw_content)

    #verify_hash()
    #send_response_to_client()

    log_file_info(decrypted_path,device_id,path_on_server)

    with open(path_on_server,'wb') as outfile:
        outfile.write(decrypted_raw_content)

def get_server_path(customer_id,device_id,decrypted_path):
    device_root_directory_on_server = "/storage/%s/device/%s/" % (customer_id,device_id)
   
    print("Combining %s with %s" % (device_root_directory_on_server,decrypted_path))
    if "\\" in decrypted_path:
        # Replace \ with /
        p = pathlib.PureWindowsPath(r'%s'%decrypted_path)
        print(p)
        path = device_root_directory_on_server + str(p.as_posix())

    elif "\\" not in decrypted_path:
        path = device_root_directory_on_server + decrypted_path

    # Remove any double slashes with single slashes
    path = path.replace("//","/")
    print(path)
    return path

def write_file_to_disk(path,content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as outfile:
        outfile.write(content)

def print_request_no_file(request):
    print("== RECEIVED NEW REQUEST ==")
    print("Request type: %s" % request['request_type'])
    print("Agent ID: %s"     % request['agent_id'])
    print("API key: %s\n"    % request['api_key'])

def initialize_logging():
    logging.basicConfig(
            filename='/var/log/stormcloud.log',
            filemode='a',
            format='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=logging.DEBUG
    )

def log_file_info(decrypted_path,device_id,path_on_server):
    logging.log(logging.INFO,"== STORING FILE : %s ==" % decrypted_path)
    logging.log(logging.INFO,"Device ID:\t%d" % device_id)
    logging.log(logging.INFO,"writing content to %s" % path_on_server)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", default=9443, type=int, help="port to listen on for backup handling")
    args = parser.parse_args()

    main(args.port)
