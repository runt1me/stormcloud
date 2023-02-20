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

from flask import Flask, jsonify, request
app = Flask(__name__)

def main(listen_port):
    install_utils.initialize_logging()
    context = scnet.get_ssl_context()

    app.run(debug=True, host='0.0.0.0', port=8443, ssl_context=context)

@app.route('/api/hello', methods=['POST'])
def hello():
    if request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = request.get_json()
    if data:
        ret_code, response_data = handle_request_generic(data)

    return response_data, 200, {'Content-Type': 'application/json'}

@app.route('/api/register-new-device', methods=['POST'])
def register_new_device():
    if request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = request.get_json()
    if data:
        ret_code, response_data = handle_request_generic(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

def handle_request_generic(request):
    logging.log(logging.INFO,request)

    if 'api_key' not in request.keys():
        return 401,json.dumps({'response':'Unable to authorize request (no api key presented)'})

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

    return 200, response_data

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

    return 200, response_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", default=8443, type=int, help="port to listen on for install handling")
    args = parser.parse_args()

    main(args.port)
