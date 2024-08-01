#!/usr/bin/python
import json
import os

import database_utils as db
import logging_utils

import backup_handlers, keepalive_handlers, restore_handlers
import generic_handlers
import new_customer_handlers
import stripe_handlers

from werkzeug.formparser import parse_form_data
from werkzeug.formparser import default_stream_factory

from flask import Flask, jsonify
from flask_cors import CORS
import flask   # used for flask.request to prevent namespace conflicts with other variables named request
app = Flask(__name__)
cors = CORS(app, resources={r"/api/*": {"origins": "https://apps.darkage.io"}})

logger = logging_utils.initialize_logging()

STRING_400_BAD_REQUEST = "Bad request."
STRING_400_MUST_BE_JSON = "Request must be JSON."
STRING_400_MUST_BE_MULTIPART = "Request must be multipart/form-data."
STRING_401_BAD_REQUEST = "Unable to authorize request."
STRING_401_INACTIVE_API_KEY = "API key is not active."
STRING_401_UNSAFE_CHARACTERS = "Request contained illegal characters."

# Doing responses this way, we don't get a few of the benefits that jsonify() provides,
# but this should probably suffice for the simple error cases.
RESPONSE_400_BAD_REQUEST = (
    json.dumps({'error': STRING_400_BAD_REQUEST}),
    400,
    {'Content-Type': 'application/json'}
)

RESPONSE_400_MUST_BE_JSON = (
    json.dumps({'error': STRING_400_MUST_BE_JSON}),
    400,
    {'Content-Type': 'application/json'}
)

RESPONSE_400_MUST_BE_MULTIPART = (
    json.dumps({'error': STRING_400_MUST_BE_MULTIPART}),
    400,
    {'Content-Type': 'application/json'}
)

RESPONSE_401_BAD_REQUEST = (
    json.dumps({'error': STRING_401_BAD_REQUEST}),
    401,
    {'Content-Type': 'application/json'}
)

RESPONSE_401_INACTIVE_API_KEY = (
    json.dumps({'error': STRING_401_INACTIVE_API_KEY}),
    401,
    {'Content-Type': 'application/json'}
)

RESPONSE_401_UNSAFE_CHARACTERS = (
    json.dumps({'error': STRING_401_UNSAFE_CHARACTERS}),
    401,
    {'Content-Type': 'application/json'}
)

def main():
    app.run()

# TODO: each call to validate_request_generic needs to adopt the new definition
def validate_request_generic(request, api_key_required=True, agent_id_required=True):
    for field in request.keys():
        if not db.passes_sanitize(str(request[field])):
            logger.warning("Failed sanitization check (field name: '%s'): %s" %(field,request[field]))
            return False, RESPONSE_401_UNSAFE_CHARACTERS

    if api_key_required:
        if 'api_key' not in request.keys():
            logger.info("Did not find api_key field which was required for request.")
            return False, RESPONSE_401_BAD_REQUEST

        result = db.get_api_key_status(str(request["api_key"]))
        if result == "API_KEY_DOES_NOT_EXIST":
            # API key doesn't exist here, no need to give more information back to the client than necessary
            logger.info("Request was made with a non-existent API key.")
            return False, RESPONSE_401_BAD_REQUEST
        elif result == "API_KEY_INACTIVE":
            # Valid API key, but inactive, subscription probably expired
            logger.info("Request was made with a valid, but inactive, API key.")
            return False, RESPONSE_401_INACTIVE_API_KEY
        elif result == "API_KEY_UNKNOWN":
            logger.warning("Got unknown response when trying to determine API key status.")
            return False, RESPONSE_401_BAD_REQUEST
        elif result == "API_KEY_ACTIVE":
            pass

    if agent_id_required:
        if 'agent_id' not in request.keys():
            logger.info("Did not find agent_id field which was required for request.")
            return False, RESPONSE_401_BAD_REQUEST

    # For consistency, return 2 values if it's a valid request, but the second value will be ignored
    return True, ""

def validate_request_admin(request):
    if 'api_key' not in request.keys():
        logger.info("Did not find api_key field which was required for request.")
        return False

    if not db.is_api_key_superuser(request['api_key']):
        logger.warning("Found non-superuser api_key field on request which required it!")
        return False

    return True

@app.route('/api/validate-api-key', methods=['POST'])
def validate_api_key():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data, api_key_required=True, agent_id_required=False)
        if not result:
            return response
            
        ret_code, response_data = generic_handlers.handle_validate_api_key_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/hello', methods=['POST'])
def hello():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data, api_key_required=False, agent_id_required=False)
        if not result:
            return response
            
        ret_code, response_data = generic_handlers.handle_hello_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/register-new-device', methods=['POST'])
def register_new_device():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data, agent_id_required=False)
        if not result:
            return response

        ret_code, response_data = backup_handlers.handle_register_new_device_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/backup-file', methods=['POST'])
def backup_file():
    logger.info(flask.request)
    logger.info(flask.request.headers)

    if 'multipart/form-data' not in flask.request.headers['Content-Type']:
        return RESPONSE_400_MUST_BE_MULTIPART

    try:
        data = json.loads(flask.request.form['json'])
    except:
        logger.warn('Saw request in backup-file which did not contain JSON.')
        return RESPONSE_400_BAD_REQUEST

    try:
        file = flask.request.files['file_content']
    except:
        logger.warn('Saw request in backup-file which did not contain file content.')
        return RESPONSE_400_BAD_REQUEST

    if data:
        result, response = validate_request_generic(data)
        if not result:
            return response

        ret_code, response_data = backup_handlers.handle_backup_file_request(data, file)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/backup-file-stream', methods=['POST'])
def backup_file_stream():
    # This endpoint should be used for clients that are streaming their uploads
    # The server should stream the receipt of the file regardless of the endpoint that is used.
    logger.info(flask.request)
    logger.info(flask.request.headers)

    if 'multipart/form-data' not in flask.request.headers['Content-Type']:
        return RESPONSE_400_MUST_BE_MULTIPART

    stream, form, files = parse_form_data(flask.request.environ, stream_factory=default_stream_factory)
    data = form
    file = files.get('file_content')

    if file is None:
        return RESPONSE_400_BAD_REQUEST
    else:
        logger.info("Parsed file from stream-based request")

    if data:
        result, response = validate_request_generic(data)
        if not result:
            return response

        ret_code, response_data = backup_handlers.handle_backup_file_request(data, file.stream)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/keepalive', methods=['POST'])
def keepalive():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data)
        if not result:
            return response

        ret_code, response_data = keepalive_handlers.handle_keepalive_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/queue-file-for-restore', methods=['POST'])
def queue_file_for_restore():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()

    if data:
        result, response = validate_request_generic(data)
        if not result:
            return response

        ret_code, response_data = restore_handlers.handle_queue_file_for_restore_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/restore-file', methods=['GET'])
def restore_file():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data)
        if not result:
            return response

        # TODO: streaming, but its difficult
        # Probably need to do multipart response or just do octet-stream and ONLY send file
        ret_code, response_data = restore_handlers.handle_restore_file_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/create-customer', methods=['POST'])
def create_customer():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data, agent_id_required=False)
        if not result:
            return response

        if not validate_request_admin(data):
            return RESPONSE_401_BAD_REQUEST

        ret_code, response_data = new_customer_handlers.handle_create_customer_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/stripe/create-customer', methods=['POST'])
def create_stripe_customer():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data, agent_id_required=False)
        if not result:
            return response

        ret_code, response_data = stripe_handlers.handle_create_customer_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

# TODO: remove this functionality from API
@app.route('/api/stripe/charge-customer', methods=['POST'])
def charge_stripe_customer():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data, agent_id_required=False)
        if not result:
            return response

        ret_code, response_data = stripe_handlers.handle_charge_customer_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/stripe/list-customers', methods=['GET'])
def list_stripe_customers():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data, agent_id_required=False)
        if not result:
            return response

        if not validate_request_admin(data):
            return RESPONSE_401_BAD_REQUEST

        ret_code, response_data = stripe_handlers.handle_list_customers_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

if __name__ == "__main__":
    main()
