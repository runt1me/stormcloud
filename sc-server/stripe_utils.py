import os
import traceback

import database_utils as db
import crypto_utils

import stripe

def create_customer(customer_email, customer_guid, payment_card_info):
    stripe.api_key = __get_stripe_key()

    try:
      payment_method = stripe.PaymentMethod.create(
        type="card",
        card={
          "number": payment_card_info['number'],
          "exp_month": payment_card_info['exp_month'],
          "exp_year": payment_card_info['exp_year'],
          "cvc": payment_card_info['cvc'],
        },
      )

      customer = stripe.Customer.create(
        email=customer_email,
        payment_method=payment_method.id,
        metadata={"CustomerGUID": customer_guid}
      )

      stripe.PaymentMethod.attach(
        payment_method.id,
        customer=customer.id,
      )

      stripe.Customer.modify(
        customer.id,
        invoice_settings={"default_payment_method": payment_method.id},
      )

      return customer.id

    except Exception as e:
      print("Caught exception on stripe.Customer.create")
      print(traceback.format_exc())
      return False

def charge_customer(charge_amount, currency, stripe_customer_id, description):
    stripe.api_key = __get_stripe_key()

    try:
      charge = stripe.Charge.create(
        amount=charge_amount,
        currency=currency,
        customer=stripe_customer_id,
        description=description
      )

      print("Received charge: %s" % str(charge))
      return charge

    except Exception as e:
      print("Caught exception on stripe.Customer.charge")
      print(traceback.format_exc())
      return False

def list_customers(limit, starting_after=None):
    stripe.api_key = __get_stripe_key()

    params = {
      'limit': limit
    }

    if starting_after:
      params['starting_after'] = starting_after

    try:
      result = stripe.Customer.list(**params)
      print("Got list: %s" % result)
      return result

    except Exception as e:
      print("Caught exception on stripe.Customer.list")
      print(traceback.format_exc())
      return False

def record_stripe_transaction(CustomerID, stripe_customer_id, amount, description):
    """
    Record a Stripe transaction in the database.
    """
    try:
        success = db.add_stripe_transaction(
            CustomerID=CustomerID,
            stripe_customer_id=stripe_customer_id,
            amount=amount,
            description=description,
            transaction_date=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
        return success
    except Exception as e:
        logger.error(f"Error recording Stripe transaction: {str(e)}")
        return False

def __get_stripe_key(key_type="test"):
  if key_type == "test":
    return os.getenv('STORMCLOUD_STRIPE_SECRET_KEY_TEST')
  elif key_type == "prod":
    return os.getenv('STORMCLOUD_STRIPE_SECRET_KEY_PROD')
