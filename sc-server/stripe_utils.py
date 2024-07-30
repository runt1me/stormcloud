import os
import traceback

import database_utils as db
import crypto_utils

import stripe

def create_customer(customer_email, customer_guid):
    stripe.api_key = os.getenv('STORMCLOUD_STRIPE_SECRET_KEY_TEST')
    print("Stripe API key from environment: %s" % os.getenv('STORMCLOUD_STRIPE_SECRET_KEY_TEST'))
    print("Stripe API key : %s" % stripe.api_key)

    try:
      customer = stripe.Customer.create(
        email=customer_email,
        metadata={"CustomerGUID": customer_guid}
      )

      print("Received customer: %s" % customer)

      return customer.id

    except Exception as e:
      print("Caught exception on stripe.Customer.create")
      print(traceback.format_exc())
      return False
