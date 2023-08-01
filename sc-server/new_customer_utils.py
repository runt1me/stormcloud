import database_utils as db
import crypto_utils

def register_new_customer(customer_name,username,password):
    # Get next customer ID from database
    # TODO: maybe need to protect this from race conditions at some point. For now its fine.
    api_key = crypto_utils.generate_api_key("/keys/%s/api/api.key" % db.get_next_customer_id())
    db.add_or_update_customer(customer_name,username,password,api_key)