#!/usr/bin/python
import json
import os
import traceback

import database_utils as db
import logging_utils

import backup_handlers, keepalive_handlers, restore_handlers
import generic_handlers
import new_customer_handlers
import stripe_handlers
import claude_handlers

from werkzeug.formparser import parse_form_data
from werkzeug.formparser import default_stream_factory

from flask import request, Flask, jsonify
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
def validate_request_generic(request, api_key_required=True, api_key_must_be_active=True, agent_id_required=True):
    for field in request.keys():
        # TODO: need to figure out how to validate these separately...
        # they will probably contain banned characters
        if 'payment_card_info' in field or 'build_command' in field:
            continue

        if not db.passes_sanitize(str(request[field])):
            logger.warning("Failed sanitization check (field name: '%s'): %s" %(field,request[field]))
            return False, RESPONSE_401_UNSAFE_CHARACTERS

    if api_key_required:
        if 'api_key' not in request.keys():
            logger.info("Did not find api_key field which was required for request.")
            return False, RESPONSE_401_BAD_REQUEST

        if api_key_must_be_active:
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

@app.route('/api/login', methods=['POST'])
def login():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if not data:
        return RESPONSE_400_BAD_REQUEST
        
    # Validate required fields
    if 'email' not in data or 'password' not in data:
        return jsonify({
            'success': False,
            'message': 'Missing required fields'
        }), 400
        
    # Validate credentials against SCLogin table
    result = db.validate_user_credentials(data['email'], data['password'])
    if not result['success']:
        return jsonify({
            'success': False,
            'message': 'Invalid credentials'
        }), 401
        
    # Return user info and API key
    return jsonify({
        'success': True,
        'data': {
            'api_key': result['api_key'],
            'user_info': {
                'email': data['email'],
                'verified': result['verified'],
                'mfa_enabled': result['mfa_enabled']
            }
        }
    }), 200

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

@app.route('/api/get-builds', methods=['POST'])
def get_builds():
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

        ret_code, response_data = generic_handlers.handle_get_builds_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/update-build-result', methods=['POST'])
def update_build_result():
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

        ret_code, response_data = generic_handlers.handle_update_build_result_request(data)
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

@app.route('/api/build-software', methods=['POST'])
def build_software():
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

        ret_code, response_data = generic_handlers.handle_build_software_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/fetch-backup-folders', methods=['POST'])
def fetch_backup_folders():
    data = request.json
    api_key = data.get('api_key')
    agent_id = data.get('agent_id')
    
    if not api_key or not agent_id:
        return jsonify({"SUCCESS": False, "message": "Missing api_key or agent_id"}), 400
    
    # Validate the API key
    customer_id = db.get_customer_id_by_api_key(api_key)
    if not customer_id:
        return jsonify({"SUCCESS": False, "message": "Invalid API key"}), 401
    
    # Validate the agent ID
    device = db.get_device_by_agent_id(agent_id)
    if not device:
        return jsonify({"SUCCESS": False, "message": "Invalid agent ID"}), 401
    
    # Assuming we have a function to fetch folders from the database
    folders = db.get_backup_folders(customer_id, device[0])  # device[0] should be the device_id
    
    if folders:
        return jsonify({
            "SUCCESS": True,
            "DATA": {
                "COLUMNS": ["FOLDER_PATH", "IS_RECURSIVE"],
                "DATA": folders
            }
        })
    else:
        return jsonify({"SUCCESS": False, "message": "No folders found"}), 404

@app.route('/api/register-backup-folders', methods=['POST'])
def register_backup_folders():
    try:
        data = request.json
        api_key = data.get('api_key')
        agent_id = data.get('agent_id')
        folders = data.get('folders')
        
        if not api_key or not agent_id or not folders:
            return jsonify({"SUCCESS": False, "message": "Invalid data provided."}), 400
        
        # Validate the API key and agent ID using the existing stored procedure
        validation_result = db.validate_api_key_and_agent_id(api_key, agent_id)
        
        # Check if the validation was successful
        if not validation_result or not validation_result.get('success'):
            return jsonify({"SUCCESS": False, "message": "Invalid data provided."}), 401
        
        # Get customer_id
        customer_id = db.get_customer_id_by_api_key(api_key)
        
        if not customer_id or not agent_id:
            return jsonify({"SUCCESS": False, "message": "Failed to retrieve customer or device information."}), 500
        
        # Register the folders
        success = db.register_backup_folders(customer_id, agent_id, folders)
        
        if success:
            return jsonify({
                "SUCCESS": True,
                "message": "Backup folders registered successfully"
            })
        else:
            return jsonify({"SUCCESS": False, "message": f"Failed to register backup folders. No changes made. Values: {customer_id}, {agent_id}, {folders}"}), 500
    except Exception as e:
        return jsonify({"SUCCESS": False, "message": f"Failed to register backup folders. {e}"}), 500

@app.route('/api/file-metadata', methods=['POST'])
def get_file_metadata():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data)
        if not result:
            return response

        agent_id = data.get('agent_id')
        if not agent_id:
            return json.dumps({'error': 'Missing agent_id'}), 400, {'Content-Type': 'application/json'}

        file_metadata = db.get_file_metadata_for_agent(agent_id)
        
        return jsonify({
            'success': True,
            'data': file_metadata
        }), 200

    else:
        return RESPONSE_400_BAD_REQUEST
        
@app.route('/api/authenticate', methods=['POST'])
def authenticate():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if not data:
        return RESPONSE_400_BAD_REQUEST
        
    # Validate required fields
    if 'username' not in data or 'password' not in data:
        return jsonify({
            "success": False,
            "message": "Missing required fields"
        }), 400

    # No need to validate API key for auth endpoint
    result, response = validate_request_generic(
        data, 
        api_key_required=False,
        agent_id_required=False
    )
    if not result:
        return response

    username = data['username']
    password = data['password']

    # Validate credentials
    auth_result = db.validate_user_credentials(username, password)
    
    if auth_result.get('success'):
        return jsonify({
            "success": True,
            "message": "Authentication successful",
            "data": {
                "api_key": auth_result.get('api_key'),
                "user_info": {
                    "email": auth_result.get('email'),
                    "verified": auth_result.get('verified'),
                    "mfa_enabled": auth_result.get('mfa_enabled')
                }
            }
        })
    else:
        return jsonify({
            "success": False,
            "message": "Invalid credentials"
        }), 401

# Stripe calls
# -------------------------
@app.route('/api/stripe/create-customer', methods=['POST'])
def create_stripe_customer():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data, api_key_must_be_active=False, agent_id_required=False)
        if not result:
            return response

        ret_code, response_data = stripe_handlers.handle_create_customer_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

@app.route('/api/stripe/remove-customer', methods=['POST'])
def remove_stripe_customer():
    logger.info("Received request to /api/stripe/remove-customer")
    logger.info(f"Request method: {flask.request.method}")
    logger.info(f"Request headers: {flask.request.headers}")
    logger.info(f"Request data: {flask.request.get_data()}")

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

        ret_code, response_data = stripe_handlers.handle_remove_customer_request(data)
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
# -------------------------

# Claude/External LLM calls
# -------------------------
@app.route('/api/summarize-file', methods=['POST'])
def summarize_file():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data)
        if not result:
            return response

        ret_code, response_data = claude_handlers.handle_summarize_file_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST
# -------------------------

@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def catch_all(path):
    logger.warning(f"Unmatched route: {path}")
    logger.warning(f"Method: {flask.request.method}")
    logger.warning(f"Headers: {flask.request.headers}")
    return "Not Found", 404

if __name__ == "__main__":
    main()
