from cryptography.fernet import Fernet

def encrypt_content(content,secret_key):
    f = Fernet(secret_key)

    msg = str(content).encode('ascii')
    encrypted = f.encrypt(msg)

    return encrypted, len(encrypted)

def encrypt_file(file_path,secret_key):
    f = Fernet(secret_key)

    file_content = file_path.read_bytes()
    encrypted = f.encrypt(file_content)

    return encrypted, len(encrypted)