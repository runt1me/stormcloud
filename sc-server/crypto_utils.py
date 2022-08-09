import os

import secrets
from cryptography.fernet import Fernet

def create_key(key_path):
    #For generating secret keys, one per device
    key = Fernet.generate_key()

    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    with open(key_path, "wb") as mykey:
        mykey.write(key)

    return key

def generate_api_key(key_path):
    #Generate api keys, one per customer
    api_key = secrets.token_urlsafe(16)

    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    with open(key_path, "wb") as api_key_file:
        api_key_file.write(api_key.encode("utf-8"))

    return api_key

def generate_agent_id():
    return secrets.token_urlsafe(8) + "-" + secrets.token_urlsafe(8)
