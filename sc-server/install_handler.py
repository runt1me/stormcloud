#!/usr/bin/python
import socket, ssl
import json
from datetime import datetime
import argparse

import logging

import network_utils as scnet
import database_utils as db
import crypto_utils
import install_utils

def main(listen_port):
    install_utils.initialize_logging()
    wrappedSocket = scnet.initialize_socket(listen_port=listen_port)

    while True:
        try:
            connection    = scnet.accept(wrappedSocket)
            request       = scnet.recv_json_until_eol(connection)

            if request:
                ret_code, response_data = handle_request(request)
                connection.sendall(bytes(response_data,encoding="utf-8"))

            else:
                ret_code, response_data = -1, json.dumps({'response': 'Bad request (data not in JSON format).'})
                connection.sendall(bytes(response_data,encoding="utf-8"))

        except Exception as e:
            logging.log(logging.INFO, "Caught exception when trying to send response to client: %s" %e)

        finally:
            connection.close()

def handle_request(request):
    logging.log(logging.INFO,request)

    if 'request_type' not in request.keys():
        return -1,json.dumps({'response':'Bad request.'})

    if 'api_key' not in request.keys():
        return -1,json.dumps({'response':'Unable to authorize request (no api key presented)'})

    if request['request_type'] == 'Hello':
        ret_code, response_data = handle_hello_request(request)
    elif request['request_type'] == 'register_new_device':
        ret_code, response_data = handle_register_new_device_request(request)

    return ret_code, response_data

def handle_hello_request(request):
    logging.log(logging.INFO,"Server handling hello request.")
    response_data = json.dumps({
        'hello-response': 'Goodbye'
    })

    return 0, response_data

def handle_register_new_device_request(request):
    logging.log(logging.INFO,"Server handling new device request.")
    customer_id      = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        logging.log(logging.INFO,"Could not find customer ID for the given API key: %s" % request['api_key'])

    device_name      = request['device_name']
    ip_address       = request['ip_address']
    device_type      = request['device_type']
    operating_system = request['operating_system']
    device_status    = request['device_status']

    # TODO: sanitize all strings for SQL injection

    # TODO: probably separate all of the above code into a "validate_request" or some similar type of function
    last_callback = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stormcloud_path_to_secret_key = "/keys/%s/device/%s/secret.key" % (customer_id,db.get_next_device_id())

    # Create crypt key and agent id before pushing to database
    key      = crypto_utils.create_key(stormcloud_path_to_secret_key)
    agent_id = crypto_utils.generate_agent_id()

    ret = db.add_or_update_device_for_customer(customer_id, device_name, device_type, ip_address, operating_system, device_status, last_callback, stormcloud_path_to_secret_key, agent_id)

    response_data = json.dumps({
        'register_new_device-response': 'thanks for the device',
        'secret_key': key.decode("utf-8"),
        'agent_id': agent_id
    })

    return 0, response_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", default=8443, type=int, help="port to listen on for install handling")
    args = parser.parse_args()

    main(args.port)
