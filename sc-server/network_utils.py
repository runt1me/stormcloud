import json
import socket, ssl
import logging

CERTFILE="/root/certs/r3_pub_priv.pem"
KEYFILE="/root/certs/r3_pub_priv.pem"

# TODO: figure out automated cert renewal

def initialize_socket(listen_port):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    context.load_cert_chain(certfile=CERTFILE)

    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.bind(('0.0.0.0',listen_port))
    s.listen(5)

    print('Listening for connections')
    return s

def accept_and_wrap_socket(s):
    wrappedSocket = None

    while not wrappedSocket:
        connection, _ = s.accept()
        try:
            wrappedSocket = ssl.wrap_socket(
                connection,
                server_side=True,
                certfile=CERTFILE,
                keyfile=KEYFILE,
                ssl_version=ssl.PROTOCOL_TLS
            )
        except:
            logging.log(logging.INFO, "Caught exception when trying to wrap SSL socket.")
            wrappedSocket = None

    return wrappedSocket

def recv_json_until_eol(socket):
    # Borrowed from https://github.com/mdebbar/jsonsocket

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

    try:
      deserialized = json.loads(view.tobytes())
    except (TypeError, ValueError) as e:
      # TODO: Send error code back to client
      logging.log(logging.INFO, "Received data inside TLS socket which was not valid JSON.")
      deserialized = None

    return deserialized

