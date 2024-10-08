import json
from datetime import datetime

import database_utils as db
import logging_utils, keepalive_utils

STRING_401_BAD_REQUEST = "Bad request."
RESPONSE_401_BAD_REQUEST = (
  401,json.dumps({'error':STRING_401_BAD_REQUEST})
)

def __logger__():
    return logging_utils.logger

def handle_keepalive_request(request):
    __logger__().info("Server handling keepalive request.")

    customer_id = db.get_customer_id_by_api_key(request['api_key'])
    if not customer_id:
        return RESPONSE_401_BAD_REQUEST

    results = db.get_device_by_agent_id(request['agent_id'])
    if not results:
        return RESPONSE_401_BAD_REQUEST

    device_id = results[0]
    keepalive_utils.record_keepalive(device_id,datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    response_data = keepalive_utils.get_keepalive_response_data(device_id)

    return 200,json.dumps(response_data)

