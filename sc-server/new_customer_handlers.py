import json
import os

import new_customer_utils as ncu
import logging_utils, crypto_utils

STRING_401_BAD_REQUEST = "Bad request."
RESPONSE_401_BAD_REQUEST = (
  401,json.dumps({'error':STRING_401_BAD_REQUEST})
)

def __logger__():
    return logging_utils.logger

def handle_create_customer_request(request):
    __logger__().info("Server handling create customer request.")
    ret = None

    required_fields = [
      'customer_name',
      'customer_email',
      'plan'
    ]

    for field in required_fields:
      if field not in request.keys():
        return RESPONSE_401_BAD_REQUEST

    else:
        ncu.register_new_customer(
            request['customer_name'],
            request['customer_email'],
            request['plan']
        )

        ret = True

    if ret:
        __logger__().info("Successfully registered new customer.")
        return 200, json.dumps({'create_customer-response': 'Successfully registered new customer [%s].' % request['customer_email']})
    else:
        __logger__().info("Got bad return code when trying to register new customer.")
        return 400, json.dumps({'error': 'Failed to add customer: %s' % request['customer_email']})
