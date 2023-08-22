import json

import database_utils as db
import logging_utils, keepalive_utils

def __logger__():
    return logging_utils.logger

def handle_keepalive_request(request):
    logger.info("Server handling keepalive request.")
    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 401,json.dumps({'response': 'Bad request.'})

    results = db.get_device_by_agent_id(request['agent_id'])
    if not results:
        return 401,json.dumps({'response': 'Bad request.'})

    device_id = results[0]
    keepalive_utils.record_keepalive(device_id,datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    response_data = keepalive_utils.get_keepalive_response_data(device_id)

    return 200,json.dumps(response_data)

