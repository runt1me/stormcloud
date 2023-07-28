import os
import sys

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

def decrypt_msg(path_to_device_secret_key,raw_msg,decode):
    f = get_fernet(path_to_device_secret_key)
    decrypted = f.decrypt(raw_msg)

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

