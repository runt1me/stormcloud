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

def decrypt_in_place(file_path, secret_key):
    f = get_fernet(secret_key)
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

def remove_temp_file(path):
    os.remove(path)