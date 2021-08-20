from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
import ast

def create_key():
    key = RSA.generate(2048)
    with open('secret_key.pem','wb') as keyfile:
        keyfile.write(key.export_key('PEM'))

    #with open('id_rsa','wb') as privkeyfile:
    #    privkeyfile.write(key.export_key('DER'))

def encrypt_content_with_public_key(content):
    with open('secret_key.pem','r') as keyfile:
        key = RSA.import_key(keyfile.read())

    msg = content.encode('ascii')
    print("using message: %s" % msg)

    encryptor = PKCS1_OAEP.new(key)
    encrypted = encryptor.encrypt(msg)

    print(encrypted)

    decryptor = PKCS1_OAEP.new(key)
    decrypted = decryptor.decrypt(ast.literal_eval(str(encrypted)))

    print("===\n%s" % decrypted)
    assert(msg == decrypted)

def bin2hex(binStr):
    return binascii.hexlify(binStr)

def hex2bin(hexStr):
    return binascii.unhexlify(hexStr)