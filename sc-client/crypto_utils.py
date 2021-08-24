from cryptography.fernet import Fernet

def create_key():
    #This should only be called once,
    #during the installation of the client!
    #unless we have some recurring changing key generation every X days
    key = Fernet.generate_key()

    with open('secret.key', 'wb') as mykey:
        mykey.write(key)

def encrypt_content(content):
    with open('secret.key', 'rb') as keyfile:
        key = keyfile.read()

    f = Fernet(key)

    msg = content.encode('ascii')
    print("using message: %s" % msg)

    return f.encrypt(msg)

def encrypt_file(file_path):
    with open('secret.key','rb') as keyfile:
        key = keyfile.read()

    f = Fernet(key)

    file_content = file_path.read_bytes()
    print("original file: %s (...)" % file_content[0:100])

    encrypted = f.encrypt(file_content)
    verify_decrypt_integrity_check(f, file_content, encrypted)

    return encrypted, len(encrypted)

def verify_decrypt_integrity_check(f, orig, encrypted):
    decrypted = f.decrypt(encrypted)
    assert(orig == decrypted)

def bin2hex(binStr):
    return binascii.hexlify(binStr)

def hex2bin(hexStr):
    return binascii.unhexlify(hexStr)