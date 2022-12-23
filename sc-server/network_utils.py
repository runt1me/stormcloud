import json
import socket, ssl
import logging

import traceback

CERTFILE="/root/certs/r3_pub_priv.pem"
KEYFILE="/root/certs/r3_pub_priv.pem"

# TODO: figure out automated cert renewal

def initialize_socket(listen_port):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERTFILE,KEYFILE)

    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.bind(('0.0.0.0',listen_port))
    s.listen(5)

    wrappedSocket = wrap(s,context)

    print('Listening for connections')
    return wrappedSocket

def wrap(s, context):
    try:
        wrappedSocket = context.wrap_socket(sock=s,server_side=True)

    except Exception as e:
        logging.log(logging.INFO, "Caught exception when trying to wrap SSL socket.")

    return wrappedSocket

def accept(wrappedSocket):
    # TODO: narrowed down phantom server crash issue to probably something in ssl.wrap_socket
    # turns out its deprecated and should be using ssl context wrap socket instead, https://docs.python.org/3/library/ssl.html
    connection = None
    try:
        logging.log(logging.INFO, "Accepting connections...")
        connection, addr = wrappedSocket.accept()
        print("connection: %s" %connection)

    except Exception as e:
        logging.log(logging.INFO, "Caught exception when trying to accept connection (maybe non-SSL connection?)")
   
    return connection

def recv_json_until_eol(socket):
    try:
        # read the length of the data, letter by letter until we reach EOL
        length_bytes = bytearray()
        char = socket.recv(1)
        while char != bytes('\n',encoding="UTF-8"):
          length_bytes += char

          char = socket.recv(1)
        total = int(length_bytes)

        # use a memoryview to receive the data chunk by chunk efficiently
        view = memoryview(bytearray(total))
        next_offset = 0
        while total - next_offset > 0:
          recv_size = socket.recv_into(view[next_offset:], total - next_offset)
          next_offset += recv_size
    except:
        logging.log(logging.INFO, "Could not read received data (maybe HTTP request?)")
        return None

    try:
      deserialized = json.loads(view.tobytes())
    except (Exception) as e:
      logging.log(logging.INFO, "Received data inside TLS socket which was not valid JSON: %s" %e)
      deserialized = None

    return deserialized

