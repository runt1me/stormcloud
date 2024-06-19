import os

import secrets
from cryptography.fernet import Fernet

import logging_utils
import database_utils as db

def __logger__():
    return logging_utils.logger

def create_key(key_path):
    key = Fernet.generate_key()

    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    with open(key_path, "wb") as mykey:
        mykey.write(key)

    return key

def generate_api_key(key_path):
    api_key = ""
    valid_token = False

    while not valid_token:
      api_key = secrets.token_urlsafe(16)

      if db.passes_sanitize(api_key):
        valid_token = True

      # Replace "-" with "_" to better accommodate some frontend display-logic
      api_key = api_key.replace("-", "_")

    return api_key

def generate_agent_id():
    valid_token = False
    token = ""

    while not valid_token:
      token = secrets.token_urlsafe(8) + "_" + secrets.token_urlsafe(8)

      if db.passes_sanitize(token):
        valid_token = True

      # Replace "-" with "_" to better accommodate some frontend display-logic
      token = token.replace("-", "_")

    return token

def decrypt_msg(path_to_device_secret_key,raw_msg,decode):
    f = get_fernet(path_to_device_secret_key)

    try:
        decrypted = f.decrypt(raw_msg)
    except Exception as e:
        __logger__().info("Caught exception when trying to decrypt. First ten bytes: %s" %raw_msg[0:10])
        return "", -1

    if decode:
        decrypted = decrypted.decode("utf-8")

    return decrypted, len(decrypted)

def decrypt_in_place(path_to_device_secret_key, file_path, decode):
    f = get_fernet(path_to_device_secret_key)
    outfile = file_path + ".tmp"
    file_size = 0

    with open(file_path, 'rb') as encrypted_file:
        encrypted_data = encrypted_file.read()

    decrypted_data = f.decrypt(encrypted_data)

    with open(outfile, 'wb') as decrypted_file:
        decrypted_file.write(decrypted_data)
        file_size = len(decrypted_data)

    os.rename(outfile, file_path)
    return True, file_size

def get_fernet(path_to_device_secret_key):
    with open(path_to_device_secret_key,'rb') as keyfile:
        key = keyfile.read()

    return Fernet(key)
