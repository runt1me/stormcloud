import json
import os

import stripe_utils
import logging_utils

STRING_401_BAD_REQUEST = "Bad request."
RESPONSE_401_BAD_REQUEST = (
  401,json.dumps({'error':STRING_401_BAD_REQUEST})
)

def __logger__():
    return logging_utils.logger

def handle_create_customer_request(request):
    __logger__().info("Server handling create Stripe customer request.")
    result = None

    required_fields = [
      'customer_email',
      'customer_guid'
    ]

    for field in required_fields:
      if field not in request.keys():
        return RESPONSE_401_BAD_REQUEST

    else:
        result = stripe_utils.create_customer(
            request['customer_email'],
            request['customer_guid']
        )

    if result:
        __logger__().info("Successfully registered new customer with Stripe.")
        return 200, json.dumps({'stripe_create_customer-response': 'Successfully registered new customer [%s] with Stripe.' % request['customer_email']})
    else:
        __logger__().info("Got bad return code when trying to register new Stripe customer.")
        return 400, json.dumps({'error': 'Failed to add Stripe customer: %s' % request['customer_email']})
