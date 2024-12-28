import json
import os

import base64

import database_utils as db
import logging_utils, crypto_utils, backup_utils

from urllib.parse import unquote

# Unfortunately currently imposing a size limit on restore until I can figure out how to stream responses
SIZE_LIMIT = 300*1024*1024

STRING_401_BAD_REQUEST = "Bad request."
RESPONSE_401_BAD_REQUEST = (
  401,json.dumps({'error':STRING_401_BAD_REQUEST})
)

STRING_413_TOO_LARGE = "Error: File too large to restore via API. \
Please reach out to the Dark Age team for more information."

RESPONSE_413_TOO_LARGE = (
  413, json.dumps({'error': STRING_413_TOO_LARGE})
)

def __logger__():
    return logging_utils.logger

def handle_queue_file_for_restore_request(request):
    __logger__().info("Server handling queue file for restore request.")

    if 'file_path' not in request.keys() or 'api_key' not in request.keys() or 'agent_id' not in request.keys():
        return RESPONSE_401_BAD_REQUEST

    customer_id = db.get_customer_id_by_api_key(request['api_key'])
    if not customer_id:
        return RESPONSE_401_BAD_REQUEST

    # To account for multiple clients, try to be accepting of
    # multiple types of encoding.
    path_as_posix = backup_utils.normalize_path(request['file_path'])

    # Try to detect encoding
    if "%2F" in path_as_posix:
        # Assume URL-encoding
        path_as_posix = unquote(path_as_posix)
    else:
        __logger__().warning("Unknown encoding type for file_path, leaving as-is")

    ret = db.add_file_to_restore_queue(request['agent_id'], path_as_posix)

    if ret:
        __logger__().info("Successfully added file to restore queue.")
        return 200, json.dumps({'queue_file_for_restore-response': 'Successfully added file to restore queue.'})
    else:
        __logger__().info("Got bad return code when trying to add file to restore queue.")
        return 400, json.dumps({'error': 'Failed to process file path [%s] in restore queue.' % request['file_path']})

def handle_restore_file_request(request):
    """Handle restore file request with chunk support"""
    __logger__().info("Server handling restore file request.")
    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return RESPONSE_401_BAD_REQUEST

    device_id,_,_,_,_,_,_,_,_,_ = db.get_device_by_agent_id(request['agent_id'])
    path_on_device = base64.b64decode(request['file_path']).decode("utf-8")
    path_on_server = db.get_server_path_for_file(device_id, path_on_device)
    
    # Get file size
    file_size = os.path.getsize(path_on_server)

    # Handle info-only request
    if request.get('info_only'):
        return 200, json.dumps({'file_size': file_size})
    
    # Handle chunked request
    if 'offset' in request and 'length' in request:
        offset = int(request['offset'])
        length = int(request['length'])
        
        if offset + length > file_size:
            length = file_size - offset
            
        with open(path_on_server, 'rb') as f:
            f.seek(offset)
            chunk = f.read(length)
            
        return 200, json.dumps({
            'file_content': base64.b64encode(chunk).decode('utf-8'),
            'chunk_size': len(chunk)
        })
    
    # Handle full file request
    if file_size > SIZE_LIMIT:
        __logger__().error("File too large to restore via API.")
        return RESPONSE_413_TOO_LARGE

    file_content = open(path_on_server, 'rb').read()
    file_content_b64 = base64.b64encode(file_content).decode('utf-8')

    response_data = {
        'restore_file-response': 'File incoming',
        'file_content': file_content_b64
    }

    db.mark_file_as_restored(device_id, path_on_device)
    return 200, json.dumps(response_data)

def handle_restore_complete_request():
    pass

    # TODO: receive request with valid api key/agent id/file path (encrypted)
    # Mark file in database as restored, 
