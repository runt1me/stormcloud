from cryptography.fernet import Fernet

def encrypt_content(content):
    with open('secret.key', 'rb') as keyfile:
        key = keyfile.read()

    f = Fernet(key)

    msg = str(content).encode('ascii')
    encrypted = f.encrypt(msg)

    return encrypted, len(encrypted)

def encrypt_file(file_path):
    with open('secret.key','rb') as keyfile:
        key = keyfile.read()

    f = Fernet(key)

    # TODO: handle permission denied errors
    file_content = file_path.read_bytes()
    encrypted = f.encrypt(file_content)

    return encrypted, len(encrypted)