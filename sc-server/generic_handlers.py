import json

import database_utils as db
import logging_utils

def __logger__():
    return logging_utils.logger

def handle_hello_request(request):
    __logger__().info("Server handling hello request.")
    response_data = json.dumps({
        'hello-response': 'Goodbye'
    })

    return 200, response_data

def handle_validate_api_key_request(request):
    __logger__().info("Server handling validate API key request.")
    __logger__().info("Server received API key: %s" % request['api_key'])
    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 401,json.dumps({'response': 'Invalid API key.'})

    return 200, json.dumps({'validate_api_key-response': 'Valid API key.'})
