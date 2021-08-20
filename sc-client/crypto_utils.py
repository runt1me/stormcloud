from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
import ast

def create_key():
    key = RSA.generate(2048)
    with open('secret_key.pem','wb') as keyfile:
        keyfile.write(key.export_key('PEM'))

    #with open('id_rsa','wb') as privkeyfile:
    #    privkeyfile.write(key.export_key('DER'))

def encrypt_content(content):
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
    return encrypted

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