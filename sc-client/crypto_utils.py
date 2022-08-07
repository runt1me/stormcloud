from cryptography.fernet import Fernet

def encrypt_content(content):
    with open('secret.key', 'rb') as keyfile:
        key = keyfile.read()

    f = Fernet(key)

    msg = str(content).encode('ascii')
    encrypted = f.encrypt(msg)
    verify_decrypt_integrity_check(f,str(content).encode('ascii'),encrypted)

    return encrypted, len(encrypted)

def encrypt_file(file_path):
    with open('secret.key','rb') as keyfile:
        key = keyfile.read()

    f = Fernet(key)

    file_content = file_path.read_bytes()

    encrypted = f.encrypt(file_content)
    verify_decrypt_integrity_check(f, file_content, encrypted)

    return encrypted, len(encrypted)

def verify_decrypt_integrity_check(f, orig, encrypted):
    decrypted = f.decrypt(encrypted)
    assert(orig == decrypted)
