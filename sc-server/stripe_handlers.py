import json
import os

import stripe_utils
import logging_utils

import database_utils as db

STRING_401_BAD_REQUEST = "Bad request."
RESPONSE_401_BAD_REQUEST = (
  401,json.dumps({'error':STRING_401_BAD_REQUEST})
)

def __logger__():
    return logging_utils.logger

def handle_create_customer_request(request):
    __logger__().info("Server handling create Stripe customer request.")
    result    = None
    stripe_id = None
    success   = False

    required_fields = [
      'customer_email',
      'customer_guid',
      'api_key',
      'payment_method_id'
    ]

    for field in required_fields:
      if field not in request.keys():
        return RESPONSE_401_BAD_REQUEST

    stripe_id = stripe_utils.create_customer(
      request['customer_email'],
      request['customer_guid'],
      # request['payment_card_method_id']
      request['payment_method_id']
    )

    if stripe_id:
      customer_id = db.get_customer_id_by_api_key(request['api_key'])

      # Update the customer with the Stripe ID,
      # and also mark their account as active.
      update_result = db.update_customer_with_stripe_id(customer_id, stripe_id)

      if update_result == 1:
        __logger__().info("Successfully registered new customer with Stripe.")
        return 200, json.dumps({'stripe_create_customer-response': 'Successfully registered new customer [%s] with Stripe.' % request['customer_email']})
      else:
        __logger__().warning("Successfully registered new customer with Stripe, but failed to add to database.")
        return 200, json.dumps({'stripe_create_customer-response': 'Successfully registered new customer with Stripe, but failed to add to database.'})

    else:
      __logger__().info("Got bad return code when trying to register new Stripe customer.")
      return 400, json.dumps({'error': 'Failed to add Stripe customer: %s' % request['customer_email']})

def handle_remove_customer_request(request):
    __logger__().info("Server handling remove Stripe customer request.")

    required_fields = [
        'api_key',
        'stripe_customer_id'
    ]

    for field in required_fields:
        if field not in request.keys():
            return RESPONSE_401_BAD_REQUEST

    stripe_customer_id = request['stripe_customer_id']

    try:
        # Delete the customer from Stripe
        deleted_customer = stripe_utils.delete_customer(stripe_customer_id)

        # If successful, update your database to reflect the removal
        if deleted_customer:
            # customer_id = db.get_customer_id_by_stripe_id(stripe_customer_id)
            # if customer_id:
                # db.remove_stripe_id_from_customer(customer_id)

            __logger__().info(f"Successfully removed Stripe customer: {stripe_customer_id}")
            return 200, json.dumps({'stripe_remove_customer-response': f'Successfully removed Stripe customer: {stripe_customer_id}'})
        else:
            __logger__().warning(f"Failed to remove Stripe customer: {stripe_customer_id}")
            return 400, json.dumps({'error': f'Failed to remove Stripe customer: {stripe_customer_id}'})

    except Exception as e:
        __logger__().error(f"Error removing Stripe customer: {str(e)}")
        return 500, json.dumps({'error': 'Internal server error while removing customer'})

def handle_charge_customer_request(request):
    __logger__().info("Server handling charge Stripe customer request.")
    result = None

    required_fields = [
      'api_key',
      'stripe_customer_id',
      'description'
    ]

    for field in required_fields:
      if field not in request.keys():
        return RESPONSE_401_BAD_REQUEST

    # TODO: handle failure
    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    # TODO: handle -1 return
    billing_amount = db.get_billing_amount(customer_id)
    if billing_amount == -1:
      __logger__().warning("Did not get valid billing amount for customer [%d], unable to charge." % customer_id)
      return RESPONSE_401_BAD_REQUEST

    charge_amount = int(billing_amount*100)
    currency = "usd"

    print("Got customer id: %d" % customer_id)
    print("Got billing amount (cents): %d" % charge_amount)

    result = stripe_utils.charge_customer(
        charge_amount,
        currency,
        request['stripe_customer_id'],
        request['description']
    )

    if result:
        transaction_recorded = stripe_utils.record_stripe_transaction(
            customer_id,
            request['stripe_customer_id'],
            charge_amount,
            request['description']
        )
    
        __logger__().info("Successfully charged %d cents to API key: %s." % (charge_amount, request['api_key']))
        return 200, json.dumps({'stripe_charge_customer-response': "Successfully charged %d cents to API key: %s." % (charge_amount, request['api_key'])})
    else:
        __logger__().info("Got bad return code when trying to charge customer. API key: [%s] Amount: [%d]." % (request['api_key'], charge_amount))
        return 400, json.dumps({'error': "Got bad return code when trying to charge customer. API key: [%s] Amount: [%d]." % (request['api_key'], charge_amount)})

def handle_list_customers_request(request):
    __logger__().info("Server handling list Stripe customers request.")
    result = None

    required_fields = [
      'limit'
    ]

    for field in required_fields:
      if field not in request.keys():
        return RESPONSE_401_BAD_REQUEST

    starting_after = None if 'starting_after' not in request else request['starting_after']

    customer_list = stripe_utils.list_customers(
        limit=request['limit'],
        starting_after=starting_after
    )

    if customer_list:
        __logger__().info("Successfully retrieved Stripe customer list.")
        return 200, json.dumps({'stripe_list_customers-response': customer_list})
    else:
        __logger__().info("Got bad return code when trying to list Stripe customers.")
        return 400, json.dumps({'error': 'Failed to get list of Stripe customers.'})

def handle_get_payment_method_request(request):
    __logger__().info("Server handling get payment method request.")

    required_fields = [
        'apikey'
    ]

    for field in required_fields:
        if field not in request.keys():
            return RESPONSE_401_BAD_REQUEST

    customer_id = request['customer_id']

    try:
        payment_method = stripe_utils.get_payment_method(customer_id)

        if payment_method:
            __logger__().info(f"Successfully retrieved payment method for customer: {customer_id}")
            return 200, json.dumps({'paymentMethod': payment_method})
        else:
            __logger__().warning(f"No payment method found for customer: {customer_id}")
            return 404, json.dumps({'error': 'No payment method found for this customer'})

    except Exception as e:
        __logger__().error(f"Error retrieving payment method: {str(e)}")
        return 500, json.dumps({'error': 'Internal server error while retrieving payment method'})
