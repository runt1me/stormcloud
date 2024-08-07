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

def get_customer_payment_method(stripe_customer_id):
    stripe.api_key = __get_stripe_key()

    try:
        customer = stripe.Customer.retrieve(stripe_customer_id)
        if customer.invoice_settings.default_payment_method:
            return customer.invoice_settings.default_payment_method
        
        # If no default payment method is set, get the first attached payment method
        payment_methods = stripe.PaymentMethod.list(
            customer=stripe_customer_id,
            type="card"
        )
        
        if payment_methods and payment_methods.data:
            return payment_methods.data[0].id
        
        return None

    except Exception as e:
        print(f"Caught exception on get_customer_payment_method for customer {stripe_customer_id}")
        print(traceback.format_exc())
        return None

def __get_stripe_key(key_type="test"):
    if key_type == "test":
        return os.getenv('STORMCLOUD_STRIPE_SECRET_KEY_TEST')
    elif key_type == "prod":
        return os.getenv('STORMCLOUD_STRIPE_SECRET_KEY_PROD')