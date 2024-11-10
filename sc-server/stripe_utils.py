import os
import traceback

import database_utils as db
import crypto_utils

import stripe

def create_customer(customer_email, customer_guid, payment_method_id):
    stripe.api_key = __get_stripe_key()

    try:
      customer = stripe.Customer.create(
        email=customer_email,
        payment_method=payment_method_id,
        metadata={"CustomerGUID": customer_guid}
      )

      stripe.PaymentMethod.attach(
        payment_method_id,
        customer=customer.id,
      )

      stripe.Customer.modify(
        customer.id,
        invoice_settings={"default_payment_method": payment_method_id},
      )

      return customer.id

    except Exception as e:
      print("Caught exception on stripe.Customer.create")
      print(traceback.format_exc())
      return False

def delete_customer(stripe_customer_id):
    stripe.api_key = __get_stripe_key()

    try:
        deleted_customer = stripe.Customer.delete(stripe_customer_id)
        return deleted_customer
    except Exception as e:
        print(f"Caught exception on stripe.Customer.delete: {str(e)}")
        return False

def charge_customer(charge_amount, currency, stripe_customer_id, description):
    stripe.api_key = __get_stripe_key()

    # SAFETY AMOUNT -- NO CHARGES OVER 50 USD FOR NOW
    if charge_amount > 5000:
      print("ERROR: Tried to charge an amount that was above the safety amount, bailing!")
      return False

    try:
      customer = stripe.Customer.retrieve(
        stripe_customer_id
      )

      intent = stripe.PaymentIntent.create(
        amount=charge_amount,
        currency=currency,
        customer=stripe_customer_id,
        payment_method=customer.invoice_settings.default_payment_method,
        off_session=True,
        confirm=True,
        description=description
      )

      print("Received payment intent: %s" % str(intent))
      return intent

    except Exception as e:
      print("Caught exception on stripe.PaymentIntent.create")
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

def __get_stripe_key(key_type="prod"):
  if key_type == "test":
    return os.getenv('STORMCLOUD_STRIPE_SECRET_KEY_TEST')
  elif key_type == "prod":
    return os.getenv('STORMCLOUD_STRIPE_SECRET_KEY_PROD')
