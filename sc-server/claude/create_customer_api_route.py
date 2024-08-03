@app.route('/api/stripe/create-customer', methods=['POST'])
def create_stripe_customer():
    logger.info(flask.request)
    if flask.request.headers['Content-Type'] != 'application/json':
        return RESPONSE_400_MUST_BE_JSON

    data = flask.request.get_json()
    if data:
        result, response = validate_request_generic(data, api_key_must_be_active=False, agent_id_required=False)
        if not result:
            return response

        ret_code, response_data = stripe_handlers.handle_create_customer_request(data)
        return response_data, ret_code, {'Content-Type': 'application/json'}
    else:
        return RESPONSE_400_BAD_REQUEST

def handle_create_customer_request(request):
    __logger__().info("Server handling create Stripe customer request.")
    result    = None
    stripe_id = None
    success   = False

    required_fields = [
      'customer_email',
      'customer_guid',
      'api_key',
      'payment_card_info'
    ]

    for field in required_fields:
      if field not in request.keys():
        return 400, json.dumps({'error': f'Missing required field: {field}'})

    # Validate payment_card_info
    card_info = request['payment_card_info']
    required_card_fields = ['number', 'exp_month', 'exp_year', 'cvc']
    for field in required_card_fields:
        if field not in card_info:
            return 400, json.dumps({'error': f'Missing required card field: {field}'})

    stripe_id = stripe_utils.create_customer(
        request['customer_email'],
        request['customer_guid'],
        request['payment_card_info']
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

def create_customer(customer_email, customer_guid, payment_card_info):
    stripe.api_key = __get_stripe_key()

    try:
      # Create a payment method using the provided card information
      payment_method = stripe.PaymentMethod.create(
        type="card",
        card={
          "number": payment_card_info['number'],
          "exp_month": payment_card_info['exp_month'],
          "exp_year": payment_card_info['exp_year'],
          "cvc": payment_card_info['cvc'],
        },
      )

      # Create a customer with the email and payment method
      customer = stripe.Customer.create(
        email=customer_email,
        payment_method=payment_method.id,
        metadata={"CustomerGUID": customer_guid}
      )

      # Attach the payment method to the customer
      stripe.PaymentMethod.attach(
        payment_method.id,
        customer=customer.id,
      )

      # Set the payment method as the default for the customer
      stripe.Customer.modify(
        customer.id,
        invoice_settings={"default_payment_method": payment_method.id},
      )

      return customer.id

    except stripe.error.StripeError as e:
      __logger__().error(f"Stripe error: {str(e)}")
      return False
    except Exception as e:
      __logger__().error(f"Caught exception on stripe.Customer.create: {str(e)}")
      __logger__().error(traceback.format_exc())
      return False