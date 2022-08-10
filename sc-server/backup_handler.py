#!/usr/bin/python
import argparse
import json

import database_utils as db
import network_utils  as scnet
import crypto_utils
import backup_utils

def main(listen_port):
    backup_utils.initialize_logging()
    s = scnet.initialize_socket(listen_port=listen_port)

    try:
        while True:
            wrappedSocket = scnet.accept_and_wrap_socket(s)
            request       = scnet.recv_json_until_eol(wrappedSocket)
    
            if request:
              ret_code, response_data = handle_request(request)
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
    else:
        ret_code = 1
        response_data = json.dumps({'response':'Unknown request type.'})

    return ret_code, response_data

def handle_backup_file_request(request):
    backup_utils.print_request_no_file(request)

    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 1,json.dumps({'response': 'Could not find Customer associated with API key.'})

    results = db.get_device_by_agent_id(request['agent_id'])
    if not results:
        return 1,json.dumps({'response': 'Could not find device associated with Agent ID.'})

    device_id,_,_,_,_,_,_,_,path_to_device_secret_key,_ = results

    path_on_server, device_root_directory_on_server, path_on_device, file_size = backup_utils.store_file(
        customer_id,
        device_id,
        path_to_device_secret_key,
        request['file_path'].encode("utf-8"),
        request['file_content'].encode("utf-8")
    )

    file_name = backup_utils.get_file_name(path_on_server)
    file_path = backup_utils.get_file_path_without_name(path_on_server)
    file_type = backup_utils.get_file_type(path_on_server)

    ret = db.add_or_update_file_for_device(
        device_id,
        file_name,
        file_path,
        path_on_device,
        file_size,
        file_type,
        path_on_server
    )

    return 0,json.dumps({'backup_file-response':'hell yeah brother'})

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", default=9443, type=int, help="port to listen on for backup handling")
    args = parser.parse_args()

    main(args.port)
