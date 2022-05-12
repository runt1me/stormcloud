from datetime import datetime
import socket
import ssl
import json

import logging

SERVER_NAME="www2.darkage.io"
SERVER_PORT=8443
STORMCLOUD_VERSION="1.0.0"

def main():
    # Initialize install logging
    initialize_logging()
    logging.log(
        logging.INFO,
        "[%s] Beginning install of Stormcloud v%s" %
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), STORMCLOUD_VERSION)
    )

    # Conduct connectivity test with server
    ret = conduct_connectivity_test(SERVER_NAME, SERVER_PORT)
    if ret != 0:
        logging.log(
            logging.ERROR,
            "[%s] Install failed (Unable to conduct connectivity test with server). Return code: %d" %
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ret)
        )
    
    logging.log(
        logging.INFO,
        "[%s] Successfully conducted connectivity test with server." %
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )

    # Interactively gather information about device

    # Send new device registration request to server

    # Save key from server as secret key

    # Configure settings

    # Launch stormcloud.py program and begin comms with the server

def conduct_connectivity_test(SERVER_NAME, SERVER_PORT):
    logging.log(
        logging.INFO,
        "[%s] Attempting connectivity test with server: %s:%d" % 
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), SERVER_NAME, SERVER_PORT)
    )
    
    send_hello_data = json.dumps({
        "hello": "TWT",
        "a": "connectivity_test"
    })

    print(send_hello_data)

    s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.settimeout(10)

    wrappedSocket = ssl.wrap_socket(s, ssl_version=ssl.PROTOCOL_TLS)
    receive_hello_data = None

    try:
        wrappedSocket.connect((SERVER_NAME,SERVER_PORT))
        wrappedSocket.sendall(bytes(send_hello_data,encoding="utf-8"))

        receive_hello_data = wrappedSocket.recv(1024)

    finally:
        wrappedSocket.close()
        if receive_hello_data:
            if "RAT" in receive_hello_data.decode("utf-8"):
                return 0
        else:
            return 1

def initialize_logging():
    logging.basicConfig(
        filename='install.log',
        filemode='a',
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.DEBUG
    )

if __name__ == '__main__':
    main()