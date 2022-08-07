import os

from cryptography.fernet import Fernet

def create_key(key_path):
    #This should only be called once,
    #during the installation of the client!
    key = Fernet.generate_key()

    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    with open(key_path, "wb") as mykey:
        mykey.write(key)

    return key
