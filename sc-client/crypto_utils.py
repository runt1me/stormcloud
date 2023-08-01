import os

from cryptography.fernet import Fernet   # pip install cryptography

def encrypt_content(content,secret_key):
    # Should not be used for especially large content.
    # Reads entire message into memory to encrypt.
    f = Fernet(secret_key)

    msg = str(content).encode('ascii')
    encrypted = f.encrypt(msg)

    return encrypted, len(encrypted)

def encrypt_file(file_path,secret_key):
    # Read in chunks to limit memory footprint.
    f = Fernet(secret_key)
    encrypted = b""

    output_path_temp = "%s.tmp" % file_path

    with open(file_path, "rb") as src_file, open(output_path_temp, "wb") as dst_file:
        for chunk in iter(lambda: src_file.read(4096), b""):
            encrypted_chunk = f.encrypt(chunk)
            dst_file.write(encrypted_chunk)

    return output_path_temp, os.path.getsize(output_path_temp)

def remove_temp_file(path):
    os.remove(path)