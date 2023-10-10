import json
import os

import database_utils as db
import logging_utils

# Unfortunately currently imposing a size limit on restore until I can figure out how to stream responses
SIZE_LIMIT = 300*1024*1024

def __logger__():
    return logging_utils.logger

def handle_queue_file_for_restore_request(request):
    __logger__().info("Server handling queue file for restore request.")

    if 'file_path' not in request.keys():
        return 400,json.dumps({'error': 'Bad request.'})

    if 'api_key' not in request.keys():
        return 400,json.dumps({'error': 'Bad request.'})

    customer_id = db.get_customer_id_by_api_key(request['api_key'])
    if not customer_id:
        return 401,json.dumps({'error': 'Invalid API key.'})

    ret = db.add_file_to_restore_queue(request['agent_id'], request['file_path'])

    if ret:
        __logger__().info("Successfully added file to restore queue.")
        return 200, json.dumps({'queue_file_for_restore-response': 'Successfully added file to restore queue.'})
    else:
        __logger__().info("Got bad return code when trying to add file to restore queue.")
        return 400, json.dumps({'error': 'Failed to process file path [%s] in restore queue.' % request['file_path']})

def handle_restore_file_request(request):
    __logger__().info("Server handling restore file request.")
    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 401,json.dumps({'response': 'Bad request.'})

    results = db.get_device_by_agent_id(request['agent_id'])
    if not results:
        return 401,json.dumps({'response': 'Bad request.'})

    device_id = int(results[0])

    path_on_server = db.get_server_path_for_file(
            device_id,
            request['file_path'],
    )

    __logger__().info("Got path: %s" % path_on_server)
    file_size = os.path.getsize(path_on_server)

    if file_size > SIZE_LIMIT:
        __logger__().error("File too large to restore via API.")
        response_data = {
            
        }


    return 200, json.dumps(response_data)
