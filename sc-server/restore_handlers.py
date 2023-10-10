import json

import database_utils as db
import logging_utils

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

    # TODO:
    # 1. get path on server for file
    path_on_server = db.get_server_path_for_file(
            device_id,
            request['file_path'],
    )

    __logger__().info("Got path: %s" % path_on_server)
    
    # 2. read content into memory (stream?)

    return 200,json.dumps({'handle_restore_file-response': 'File incoming.'})

