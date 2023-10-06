#!/usr/bin/python
import json

import database_utils as db
import logging_utils

import backup_handlers, keepalive_handlers, restore_handlers
import generic_handlers

from werkzeug.formparser import parse_form_data
from werkzeug.formparser import default_stream_factory

from flask import Flask, jsonify
import flask   # used for flask.request to prevent namespace conflicts with other variables named request
app = Flask(__name__)

logger = logging_utils.initialize_logging()

def main():
    app.run()

def validate_request_generic(request, api_key_required=True, agent_id_required=True):
    if api_key_required:
        if 'api_key' not in request.keys():
            logger.info("Did not find api_key field which was required for request.")
            return False

    if agent_id_required:
        if 'agent_id' not in request.keys():
            logger.info("Did not find agent_id field which was required for request.")
            return False

    for field in request.keys():
        if not db.passes_sanitize(str(request[field])):
            logger.warning("Failed sanitization check: %s" %request[field])
            return False

    return True

@app.route('/api/validate-api-key', methods=['POST'])
def validate_api_key():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data, api_key_required=True, agent_id_required=False):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}
            
        ret_code, response_data = generic_handlers.handle_validate_api_key_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/hello', methods=['POST'])
def hello():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data, api_key_required=False, agent_id_required=False):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}
            
        ret_code, response_data = generic_handlers.handle_hello_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/register-new-device', methods=['POST'])
def register_new_device():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data, agent_id_required=False):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = backup_handlers.handle_register_new_device_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/backup-file', methods=['POST'])
def backup_file():
    logger.info(flask.request)
    logger.info(flask.request.headers)

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

        ret_code, response_data = backup_handlers.handle_backup_file_request(data, file)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/backup-file-stream', methods=['POST'])
def backup_file_stream():
    # This endpoint should be used for clients that are streaming their uploads
    # The server should stream the receipt of the file regardless of the endpoint that is used.
    logger.info(flask.request)
    logger.info(flask.request.headers)

    if 'multipart/form-data' not in flask.request.headers['Content-Type']:
        return jsonify({'error': 'Request must be multipart/form-data'}), 400

    stream, form, files = parse_form_data(flask.request.environ, stream_factory=default_stream_factory)
    data = form
    file = files.get('file_content')

    if file is None:
        return jsonify({'error': 'File content not found in request'}), 400
    else:
        logger.info("Parsed file from stream-based request")

    if data:
        if not validate_request_generic(data):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = backup_handlers.handle_backup_file_request(data, file.stream)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'Bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/keepalive', methods=['POST'])
def keepalive():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = keepalive_handlers.handle_keepalive_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/queue-file-for-restore', methods=['POST'])
def queue_file_for_restore():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()

    if data:
        if not validate_request_generic(data):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = restore_handlers.handle_queue_file_for_restore_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'Bad request'}), 400, {'Content-Type': 'application/json'}

@app.route('/api/restore-file', methods=['GET'])
def restore_file():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return jsonify({'error': 'Request must be JSON'}), 400

    data = flask.request.get_json()
    if data:
        if not validate_request_generic(data):
            return jsonify({'response':'Unable to authorize request'}), 401, {'Content-Type': 'application/json'}

        ret_code, response_data = restore_handlers.handle_restore_file_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return jsonify({'error': 'bad request'}), 400, {'Content-Type': 'application/json'}

if __name__ == "__main__":
    main()
