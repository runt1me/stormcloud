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

# globals for server
global_logger = backup_utils.initialize_logging()
ChunkHandler = backup_utils.ChunkHandler()

def main():
    app.run()

def validate_request_generic(request, api_key_required=True, agent_id_required=True):
    if api_key_required:
        if 'api_key' not in request.keys():
            global_logger.info("Did not find api_key field which was required for request.")
            return False

    if agent_id_required:
        if 'agent_id' not in request.keys():
            global_logger.info("Did not find agent_id field which was required for request.")
            return False

    for field in request.keys():
        if not db.passes_sanitize(str(request[field])):
            global_logger.warning("Failed sanitization check: %s" %request[field])
            return False

    return True

def handle_hello_request(request):
    global_logger.info("Server handling hello request.")
    response_data = json.dumps({
        'hello-response': 'Goodbye'
    })

    return 200, response_data

def handle_register_new_device_request(request):
    global_logger.info("Server handling new device request.")

    customer_id      = db.get_customer_id_by_api_key(request['api_key'])
    if not customer_id:
        global_logger.warning("Could not find customer ID for the given API key: %s" % request['api_key'])
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

def handle_backup_file_in_chunks_request(request):
    global_logger.info("Server handling backup file in chunks request.")
    backup_utils.print_request_no_file(request)

    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 401,json.dumps({'response': 'Bad request.'})

    results = db.get_device_by_agent_id(request['agent_id'])
    if not results:
        return 401,json.dumps({'response': 'Bad request.'})

    device_id,_,_,_,_,_,_,_,path_to_device_secret_key,_ = results

    ChunkHandler.add_active_chunk(
        request['agent_id'], request['file_path'],
        request['chunk_number'], request['total_chunks'],
        request['file_content_chunk']
    )

    if request['chunk_number'] == request['total_chunks'] - 1:
        # If final chunk, combine chunks and write to disk
        # respond with a 200 and indicate file written successfully
        file_content_raw = ChunkHandler.combine_chunks(request['agent_id'],request['file_path'])

        if file_content_raw is None:
            raise Exception("Server could not combine chunks")

        print("Successfully (?) combined file chunks into file_content_raw?")

        path_on_server, device_root_directory_on_server, path_on_device, file_size = backup_utils.store_file(
            customer_id,
            device_id,
            path_to_device_secret_key,
            request['file_path'].encode("utf-8"),
            file_content_raw.encode("utf-8"),
            max_versions=3
        )

        # TODO: clean this up and put as a helper function in backup_utils
        if "\\" in path_on_device:
            p = pathlib.PureWindowsPath(r'%s'%path_on_device)
            path_on_device_posix = str(p.as_posix())
            directory_on_device = p.parents[0]
            directory_on_device_posix = str(directory_on_device.as_posix())
        else:
            # TODO: test does this work on unix?
            p = pathlib.Path(path_on_device)
            path_on_device_posix = path_on_device
            directory_on_device = p.parents[0]
            directory_on_device_posix = str(directory_on_device)

        file_name = backup_utils.get_file_name(path_on_server)
        file_path = backup_utils.get_file_path_without_name(path_on_server)
        file_type = backup_utils.get_file_type(path_on_server)

        _ = db.add_or_update_file_for_device(
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

        return 200,json.dumps({'backup_file_in_chunks-response': 'Received all chunks and wrote file successfully.'})

    else:
        # If not final chunk, respond with a 200
        # and indicate chunk received successfully
        return 200,json.dumps({'backup_file_in_chunks-response':'Received chunk successfully.'})

def handle_keepalive_request(request):
    global_logger.info("Server handling keepalive request.")
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
    global_logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data, api_key_required=False, agent_id_required=False):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}
            
        ret_code, response_data = handle_hello_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/register-new-device', methods=['POST'])
def register_new_device():
    global_logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data, agent_id_required=False):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = handle_register_new_device_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/backup-file', methods=['POST'])
def backup_file():
    global_logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = handle_backup_file_in_chunks_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/backup-file-in-chunks', methods=['POST'])
def backup_file_in_chunks():
    global_logger.info(flask.request)

    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = handle_backup_file_in_chunks_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/keepalive', methods=['POST'])
def keepalive():
    global_logger.info(flask.request)
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
    main()
