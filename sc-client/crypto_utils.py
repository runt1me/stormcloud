import os

from cryptography.fernet import Fernet   # pip install cryptography

CHUNK_SIZE = 1024 * 1024  # 1 MB chunks

def encrypt_content(content,secret_key):
    # Should not be used for especially large content.
    # Reads entire message into memory to encrypt.
    f = Fernet(secret_key)

    msg = str(content).encode('ascii')
    encrypted = f.encrypt(msg)

    return encrypted, len(encrypted)

def encrypt_file(file_path, secret_key):
    f = Fernet(secret_key)
    output_path_temp = f"{file_path}.tmp"
    
    with open(file_path, "rb") as src_file, open(output_path_temp, "wb") as dst_file:
        while True:
            chunk = src_file.read(CHUNK_SIZE)
            if not chunk:
                break
            encrypted_chunk = f.encrypt(chunk)
            dst_file.write(encrypted_chunk)

    return output_path_temp, os.path.getsize(output_path_temp)

def decrypt_in_place(file_path, secret_key):
    f = Fernet(secret_key)
    outfile = f"{file_path}.tmp"
    file_size = 0

    with open(file_path, 'rb') as encrypted_file, open(outfile, 'wb') as decrypted_file:
        while True:
            chunk = encrypted_file.read(CHUNK_SIZE)
            if not chunk:
                break
            decrypted_chunk = f.decrypt(chunk)
            decrypted_file.write(decrypted_chunk)
            file_size += len(decrypted_chunk)

    os.replace(outfile, file_path)
    return True, file_size

def remove_temp_file(path):
    os.remove(path)