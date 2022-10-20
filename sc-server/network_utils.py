import json
import socket, ssl

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
    connection, _ = s.accept()
    wrappedSocket = ssl.wrap_socket(
        connection,
        server_side=True,
        certfile=CERTFILE,
        keyfile=KEYFILE,
        ssl_version=ssl.PROTOCOL_TLS
    )

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
      raise Exception('Data received was not in JSON format')

    return deserialized


