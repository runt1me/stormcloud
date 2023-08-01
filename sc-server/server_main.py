#!/usr/bin/python
import json
from datetime import datetime

import pathlib

import database_utils as db
import crypto_utils, backup_utils, keepalive_utils

from werkzeug.formparser import parse_form_data
from werkzeug.formparser import default_stream_factory

from flask import Flask, jsonify
import flask   # used for flask.request to prevent namespace conflicts with other variables named request
app = Flask(__name__)

# globals for server
global_logger = backup_utils.initialize_logging()

CHUNK_SIZE = 1024*1024

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

def handle_backup_file_request(request, file):
    global_logger.info("Server handling backup file request.")
    global_logger.info("File type: %s" % type(file))
    backup_utils.print_request_no_file(request)

    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 401,json.dumps({'response': 'Bad request.'})

    results = db.get_device_by_agent_id(request['agent_id'])
    if not results:
        return 401,json.dumps({'response': 'Bad request.'})

    device_id,_,_,_,_,_,_,_,path_to_device_secret_key,_ = results

    path_on_device, _ = crypto_utils.decrypt_msg(path_to_device_secret_key,request['file_path'].encode("UTF-8"),decode=True)
    path_on_server, device_root_directory_on_server = backup_utils.get_server_path(customer_id,device_id,path_on_device)

    file_size = backup_utils.stream_write_file_to_disk(path=path_on_server,file_handle=file,max_versions=3,chunk_size=CHUNK_SIZE)

    # TODO: eventually respond to client more quickly and queue the writes to disk / database calls until afterwards
    global_logger.info("Done writing file to %s" % path_on_server)

    #result, file_size = crypto_utils.decrypt_in_place(path_to_device_secret_key,path_on_server,decode=False)

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

    return 200,json.dumps({'backup_file-response': 'Received file successfully.'})

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

def handle_validate_api_key_request(request):
    global_logger.info("Server handling validate API key request.")
    global_logger.info("Server received API key: %s" % request['api_key'])
    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 401,json.dumps({'response': 'Invalid API key.'})

    return 200, json.dumps({'validate_api_key-response': 'Valid API key.'})

@app.route('/api/validate-api-key', methods=['POST'])
def validate_api_key():
    global_logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data, api_key_required=True, agent_id_required=False):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}
            
        ret_code, response_data = handle_validate_api_key_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

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
    global_logger.info(flask.request.headers)

    if 'multipart/form-data' not in flask.request.headers['Content-Type']:
        return jsonify({'error': 'Request must be multipart/form-data'}), 400

    try:
        data = json.loads(flask.request.form['json'])
    except:
        return jsonify({'error': 'Request must contain JSON.'}), 400

    try:
        file = flask.request.files['file_content']
    except:
        return jsonify({'error': 'Request must contain file_content.'}), 400

    if data:
        if not validate_request_generic(data):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = handle_backup_file_request(data, file)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/backup-file-stream', methods=['POST'])
def backup_file_stream():
    # This endpoint should be used for clients that are streaming their uploads
    # The server should stream the receipt of the file regardless of the endpoint that is used.
    global_logger.info(flask.request)
    global_logger.info(flask.request.headers)

    if 'multipart/form-data' not in flask.request.headers['Content-Type']:
        return jsonify({'error': 'Request must be multipart/form-data'}), 400

    stream, form, files = parse_form_data(flask.request.environ, stream_factory=default_stream_factory)
    data = form
    file = files.get('file_content')

    if file is None:
        return jsonify({'error': 'File content not found in request'}), 400
    else:
        print("Parsed file from stream-based request")

    if data:
        if not validate_request_generic(data):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = handle_backup_file_request(data, file.stream)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'Bad request'}), 400, {'Content-Type': 'application/json'}

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
