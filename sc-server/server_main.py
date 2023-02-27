#!/usr/bin/python
import json
from datetime import datetime
import argparse

import logging
import pathlib

import network_utils as scnet
import database_utils as db
import crypto_utils, install_utils, backup_utils, keepalive_utils

from flask import Flask, jsonify
import flask   # used for flask.request to prevent namespace conflicts with other variables named request
app = Flask(__name__)

def main(listen_port):
    # Figure out how to initialize logging for each backup, install, keepalive
    # or maybe just have one file for all? setup logrotate?
    backup_utils.initialize_logging()
    context = scnet.get_ssl_context()

    app.run(debug=False, host='0.0.0.0', port=listen_port, ssl_context=context)

def validate_request_generic(request, api_key_required=True):
    if api_key_required:
        if 'api_key' not in request.keys():
            return False

    return True

def handle_hello_request(request):
    print("Server received hello request: %s" % request)
    logging.log(logging.INFO,"Server handling hello request.")
    response_data = json.dumps({
        'hello-response': 'Goodbye'
    })

    return 200, response_data

def handle_register_new_device_request(request):
    logging.log(logging.INFO,"Server handling new device request.")

    customer_id = None
    if db.passes_sanitize(request['api_key']):
        customer_id      = db.get_customer_id_by_api_key(request['api_key'])
    else:
        logging.log(logging.WARNING, "Failed input sanitization for request: %s" % request)

    if not customer_id:
        logging.log(logging.WARNING,"Could not find customer ID for the given API key: %s" % request['api_key'])
        response_code = 401
        response_data = json.dumps({
            'response': 'Unable to authorize request',
        })

        return response_code, response_data

        
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

def handle_backup_file_request(request):
    logging.log(logging.INFO,"Server handling backup file request.")
    backup_utils.print_request_no_file(request)

    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 401,json.dumps({'response': 'Bad request.'})

    results = db.get_device_by_agent_id(request['agent_id'])
    if not results:
        return 401,json.dumps({'response': 'Bad request.'})

    device_id,_,_,_,_,_,_,_,path_to_device_secret_key,_ = results

    # TODO: probably configure this per customer in database
    max_versions = 3

    path_on_server, device_root_directory_on_server, path_on_device, file_size = backup_utils.store_file(
        customer_id,
        device_id,
        path_to_device_secret_key,
        request['file_path'].encode("utf-8"),
        request['file_content'].encode("utf-8"),
        max_versions
    )

    if "\\" in path_on_device:
        p = pathlib.PureWindowsPath(r'%s'%path_on_device)
        path_on_device_posix = str(p.as_posix())
        directory_on_device = p.parents[0]
        directory_on_device_posix = str(directory_on_device.as_posix())
    else:
        # TODO: does this work on unix?
        p = pathlib.Path(path_on_device)
        path_on_device_posix = path_on_device
        directory_on_device = p.parents[0]
        directory_on_device_posix = str(directory_on_device)

    file_name = backup_utils.get_file_name(path_on_server)
    file_path = backup_utils.get_file_path_without_name(path_on_server)
    file_type = backup_utils.get_file_type(path_on_server)

    ret = db.add_or_update_file_for_device(
        device_id,
        file_name,
        file_path,
        path_on_device,
        path_on_device_posix,
        directory_on_device_posix,
        file_size,
        file_type,
        path_on_server
    )

    return 200,json.dumps({'backup_file-response':'hell yeah brother'})

def handle_keepalive_request(request):
    logging.log(logging.INFO,"Server handling keepalive request.")
    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 401,json.dumps({'response': 'Bad request.'})

    results = db.get_device_by_agent_id(request['agent_id'])
    if not results:
        return 401,json.dumps({'response': 'Bad request.'})

    device_id = results[0]
    ret = keepalive_utils.record_keepalive(device_id,datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    return 200,json.dumps({'keepalive-response':'ahh, ahh, ahh, ahh, staying alive'})

@app.route('/api/hello', methods=['POST'])
def hello():
    logging.log(logging.INFO,flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data, api_key_required=False):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}
            
        ret_code, response_data = handle_hello_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/register-new-device', methods=['POST'])
def register_new_device():
    logging.log(logging.INFO,flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data):
            logging.log(logging.INFO,"Sending 401 response")
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = handle_register_new_device_request(data)
        logging.log(logging.INFO,"Sending %d response: %s" %(ret_code,response_data))
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        logging.log(logging.INFO,"Sending 400 response")
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/backup-file', methods=['POST'])
def backup_file():
    logging.log(logging.INFO,flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = handle_backup_file_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/keepalive', methods=['POST'])
def keepalive():
    logging.log(logging.INFO,flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = handle_keepalive_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", default=8443, type=int, help="server port for listening")
    args = parser.parse_args()

    main(args.port)
