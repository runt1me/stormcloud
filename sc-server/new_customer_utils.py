import database_utils as db
import crypto_utils

def register_new_customer(customer_name, plan):
    # Get next customer ID from database
    # TODO: maybe need to protect this from race conditions at some point. For now its fine.
    api_key = crypto_utils.generate_api_key()

    # TODO: generate customer GUID
    customer_guid = crypto_utils.generate_customer_guid()

    # We only write username here now.
    # The actual password hash and salt will be generated in coldfusion
    # And will be written through a separate process for now.
    # TODO: eventually we should port the hash and salt generation logic into python and use it here.
    # That would simplify the process and reduce 2 database inserts to 1.
    return db.add_or_update_customer(customer_name,customer_guid,plan,api_key)
