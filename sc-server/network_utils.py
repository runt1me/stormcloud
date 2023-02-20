import json
import socket, ssl
import logging

import traceback

CERTFILE="/etc/letsencrypt/live/www2.darkage.io/fullchain.pem"
KEYFILE="/etc/letsencrypt/live/www2.darkage.io/privkey.pem"

# TODO: figure out automated cert renewal

def get_ssl_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERTFILE,KEYFILE)
    return context

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
        logging.log(logging.ERROR, "Caught exception when trying to wrap SSL socket: %s" %traceback.format_exc())

    return wrappedSocket

def accept(wrappedSocket):
    connection = None
    while not connection:
        try:
            logging.log(logging.INFO, "Accepting connections.")
            connection, addr = wrappedSocket.accept()

            # Set server-side connection timeout to deal with premature client disconnects.
            # This addresses a wide range of bad client behavior, in particular, web browser spray.
            connection.settimeout(3.0)
            print("connection: %s" %connection)

        except Exception as e:
            logging.log(logging.INFO, "Caught exception when trying to accept connection: %s" %e)
   
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
        # In theory at this point the connection has passed the SSL, but is not pure JSON
        # Most likely event is an HTTPS request given the listening ports 7443,8443,9443
        logging.log(logging.INFO, "Could not read received data (maybe HTTP request?)")
        return None

    try:
      deserialized = json.loads(view.tobytes())
    except (Exception) as e:
      logging.log(logging.INFO, "Received data inside TLS socket which was not valid JSON: %s" %e)
      deserialized = None

    return deserialized

