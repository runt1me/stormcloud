# File: /var/www/stripe_api/app/routes.py

from flask import Blueprint, request, jsonify
import stripe

bp = Blueprint('stripe_api', __name__)

stripe.api_key = "sk_test_..." # Replace with your Stripe test secret key

@bp.route('/create_customer', methods=['POST'])
def create_customer():
    data = request.json
    try:
        customer = stripe.Customer.create(
            email=data['email'],
            metadata={"CustomerGUID": data['customer_guid']}
        )
        return jsonify({"customer_id": customer.id}), 200
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 400

@bp.route('/charge_customer', methods=['POST'])
def charge_customer():
    data = request.json
    try:
        charge = stripe.Charge.create(
            amount=int(data['amount'] * 100),  # amount in cents
            currency="usd",
            customer=data['customer_id'],
            description=data['description']
        )
        return jsonify({"charge_id": charge.id}), 200
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 400

@bp.route('/list_customers', methods=['GET'])
def list_customers():
    try:
        limit = request.args.get('limit', 10)
        starting_after = request.args.get('starting_after')
        
        params = {
            'limit': limit
        }
        if starting_after:
            params['starting_after'] = starting_after
        
        customers = stripe.Customer.list(**params)
        
        return jsonify({
            'customers': customers.data,
            'has_more': customers.has_more,
            'next_cursor': customers.data[-1].id if customers.has_more else None
        }), 200
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 400

@bp.route('/webhook', methods=['POST'])
def webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, "whsec_..." # Replace with your webhook signing secret
        )
    except ValueError as e:
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError as e:
        return jsonify({"error": "Invalid signature"}), 400

    # Handle the event
    if event['type'] == 'charge.succeeded':
        charge = event['data']['object']
        # Handle successful charge
        print(f"Charge succeeded: {charge['id']}")
    elif event['type'] == 'charge.failed':
        charge = event['data']['object']
        # Handle failed charge
        print(f"Charge failed: {charge['id']}")

    return jsonify({"success": True}), 200
