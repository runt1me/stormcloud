import socket, ssl
import sys
from datetime import datetime
import argparse
import json

import logging

import database_utils as db
import network_utils  as scnet
import crypto_utils

def main(LISTEN_PORT):
    initialize_logging()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    context.load_cert_chain(certfile="/root/certs/cert.pem")

    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.bind(('0.0.0.0',LISTEN_PORT))
    s.listen(5)

    print('Listening for connections')

    try:
        while True:
            logging.log(logging.INFO,"KEEPALIVE_HANDLER is waiting for a connection")
            # TODO: use actual signed cert for SSL
            # and use TLS 1.3
            connection, client_address = s.accept()
            wrappedSocket = ssl.wrap_socket(
                    connection,
                    server_side=True,
                    certfile="/root/certs/cert.pem",
                    keyfile="/root/certs/cert.pem",
                    ssl_version=ssl.PROTOCOL_TLS
            )

            request = scnet.recv_json_until_eol(wrappedSocket)

            if request:
              ret_code, response_data = handle_request(request)
              # Send the length of the serialized data first, then send the data
              # wrappedSocket.send(bytes('%d\n',encoding="utf-8") % len(response_data))
              wrappedSocket.sendall(bytes(response_data,encoding="utf-8"))

            else:
                break
    finally:
        wrappedSocket.close()


def handle_request(request):
    if 'request_type' not in request.keys():
        return -1,json.dumps({'response':'Bad request.'})
    if 'api_key' not in request.keys():
        return -1,json.dumps({'response':'Unable to authorize request (no api key presented)'})

    if request['request_type'] == 'keepalive':
        ret_code, response_data = handle_keepalive_request(request)
    else:
        ret_code = 1
        response_data = json.dumps({'response':'Unknown request type.'})

    return ret_code, response_data

def handle_keepalive_request(request):
    print(request)
    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 1,json.dumps({'response': 'Could not find Customer associated with API key.'})

    results = db.get_device_by_agent_id(request['agent_id'])
    if not results:
        return 1,json.dumps({'response': 'Could not find device associated with Agent ID.'})

    device_id = results[0]
    ret = record_keepalive(device_id,datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    return 0,json.dumps({'keepalive-response':'ahh, ahh, ahh, ahh, staying alive'})

def record_keepalive(device_id,current_time):
    logging.log(logging.INFO,"recording keepalive for device %d" %device_id)
    ret = db.update_callback_for_device(device_id,current_time,0)

    return ret

def initialize_logging():
    logging.basicConfig(
            filename='/var/log/stormcloud_ka.log',
            filemode='a',
            format='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=logging.DEBUG
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", default=7443, type=int, help="port to listen on for keepalive handling")
    args = parser.parse_args()

    main(args.port)

