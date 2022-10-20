#!/usr/bin/python
from datetime import datetime
import argparse
import json

import database_utils as db
import network_utils  as scnet
import keepalive_utils

def main(listen_port):
    keepalive_utils.initialize_logging()
    s = scnet.initialize_socket(listen_port=listen_port)

    try:
        while True:
            wrappedSocket = scnet.accept_and_wrap_socket(s)
            request       = scnet.recv_json_until_eol(wrappedSocket)

            if request:
              ret_code, response_data = handle_request(request)
              wrappedSocket.sendall(bytes(response_data,encoding="utf-8"))

            else:
              ret_code, response_data = -1, json.dumps({'response': 'Bad request (data not in JSON format).'})
              wrappedSocket.sendall(bytes(response_data,encoding="utf-8"))

    finally:
        wrappedSocket.close()

def handle_request(request):
    if 'request_type' not in request.keys():
        return -1,json.dumps({'response':'Bad request.'})
    if 'api_key' not in request.keys():
        return -1,json.dumps({'response':'Unable to authorize request (no api key presented)'})

    if request['request_type'] == 'keepalive':
        ret_code, response_data = handle_keepalive_request(request)
    else:
        ret_code = 1
        response_data = json.dumps({'response':'Unknown request type.'})

    return ret_code, response_data

def handle_keepalive_request(request):
    print(request)
    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 1,json.dumps({'response': 'Could not find Customer associated with API key.'})

    results = db.get_device_by_agent_id(request['agent_id'])
    if not results:
        return 1,json.dumps({'response': 'Could not find device associated with Agent ID.'})

    device_id = results[0]
    ret = keepalive_utils.record_keepalive(device_id,datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    return 0,json.dumps({'keepalive-response':'ahh, ahh, ahh, ahh, staying alive'})

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", default=7443, type=int, help="port to listen on for keepalive handling")
    args = parser.parse_args()

    main(args.port)

