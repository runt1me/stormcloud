#!/usr/bin/python
import socket, ssl
import json
from datetime import datetime

import database_utils as db
import crypto_utils

BIND_PORT=8443

def main():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    context.load_cert_chain(certfile="/root/certs/cert.pem")

    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.bind(('0.0.0.0',BIND_PORT))
    s.listen(5)

    print("Listening for connections")

    try:
        while True:
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
    
            request = recv_json_until_eol(wrappedSocket)
    
            if request:
              ret_code, response_data = handle_request(request)
              # Send the length of the serialized data first, then send the data
              # wrappedSocket.send(bytes('%d\n',encoding="utf-8") % len(response_data))
              wrappedSocket.sendall(bytes(response_data,encoding="utf-8"))

            else:
                break
    finally:
        wrappedSocket.close()

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

def handle_request(request):
    print(request)

    if 'request_type' not in request.keys():
        return -1,'Bad request.'

    if request['request_type'] == 'Hello':
        ret_code, response_data = handle_hello_request(request)
    elif request['request_type'] == 'register_new_device':
        ret_code, response_data = handle_register_new_device_request(request)

    return ret_code, response_data

def handle_hello_request(request):
    print("Server handling hello request.")
    response_data = json.dumps({
        'hello-response': 'Goodbye'
    })

    return 0, response_data

def handle_register_new_device_request(request):
    # TODO: need to guard this request with an API key.
    # API key will probably have to be one per account.
    # Account credentials will need to be passed into the installer
    print("Server handling new device request.")

    customer_id      = request['customer_id']
    device_name      = request['device_name']
    ip_address       = request['ip_address']
    device_type      = request['device_type']
    operating_system = request['operating_system']
    device_status    = request['device_status']

    # TODO: sanitize all strings for SQL injection

    # Verify that the device is not already in the database
    # If it is not, create a new device in the device table
    # For now, a device is considered uniquely identified by its customer id, hostname and ip address
    ret = verify_device_uniqueness(customer_id,device_name,ip_address)
    if ret != 0:
        print("Device is already in database, device id: %s" % ret)

    # TODO: probably separate all of the above code into a "validate_request" or some similar type of function
    last_callback = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stormcloud_path_to_secret_key = "/keys/%s/device/%s/secret.key" % (customer_id,db.get_next_device_id())

    # Create crypt key before pushing to database
    key = crypto_utils.create_key(stormcloud_path_to_secret_key)

    ret = db.add_or_update_device_for_customer(customer_id, device_name, device_type, ip_address, operating_system, device_status, last_callback, stormcloud_path_to_secret_key)

    response_data = json.dumps({
        'register_new_device-response': 'thanks for the device',
        'secret_key': key.decode("utf-8")
    })

    return 0, response_data

def verify_device_uniqueness(customer_id,device_name,ip_address):
    # TODO: probably a database-side pass the info and database returns <device id> or 0
    return 0

if __name__ == "__main__":
    main()
