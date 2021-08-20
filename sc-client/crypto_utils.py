from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
import ast

from cryptography.fernet import Fernet

def create_key():
    key = Fernet.generate_key()

    with open('secret.key', 'wb') as mykey:
        mykey.write(key)

def encrypt_content(content):
    with open('secret.key', 'rb') as mykey:
        key = mykey.read()

    f = Fernet(key)

    msg = content.encode('ascii')
    print("using message: %s" % msg)

    encrypted = f.encrypt(msg)

    print(encrypted)

    decrypted = f.decrypt(encrypted)

    print("===\n%s" % decrypted)
    print(type(decrypted))
    assert(msg == decrypted)
    #return encrypted

def encrypt_file(file_path):
    with open('secret_key.pem','r') as keyfile:
        key = RSA.import_key(keyfile.read())

    file_content = file_path.read_bytes()
    print("original file: %s" % file_content)

    encryptor = PKCS1_OAEP.new(key)
    encrypted = encryptor.encrypt(file_content)

    print(encrypted)

    decryptor = PKCS1_OAEP.new(key)
    decrypted = decryptor.decrypt(ast.literal_eval(str(encrypted)))

    print("===\n%s" % decrypted)
    assert(file_content == decrypted)
    return encrypted, len(encrypted)

def bin2hex(binStr):
    return binascii.hexlify(binStr)

def hex2bin(hexStr):
    return binascii.unhexlify(hexStr)