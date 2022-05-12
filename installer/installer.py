from datetime import datetime
import socket, ssl
import json
import platform

import logging

import argparse

SERVER_NAME="www2.darkage.io"
SERVER_PORT=8443
STORMCLOUD_VERSION="1.0.0"

def main(device_type="Important Server (from installer)"):
    # Initialize install logging
    initialize_logging()
    logging.log(
        logging.INFO, "Beginning install of Stormcloud v%s" % STORMCLOUD_VERSION
    )

    # Conduct connectivity test with server
    ret, _ = conduct_connectivity_test(SERVER_NAME, SERVER_PORT)
    if ret != 0:
        logging.log(
            logging.ERROR, "Install failed (Unable to conduct connectivity test with server). Return code: %d" % ret
        )
        exit()
    
    logging.log(
        logging.INFO, "Successfully conducted connectivity test with server."
    )

    logging.log(
        logging.INFO, "Conducting initial device survey."
    )
    
    survey_data = conduct_device_initial_survey(device_type)
    ret, response_data = tls_send_json_data(survey_data, "RAT", SERVER_NAME, SERVER_PORT)
    if ret != 0:
        logging.log(
            logging.ERROR, "Install failed (Unable to send survey data to server). Return code: %d" % ret
        )
        exit()
    
    logging.log(
        logging.INFO, "Successfully sent new device registration request to server. Received response data: %s" % response_data
    )
    
    # Save key from server as secret key
    secret_key = response_data['secret_key']

    # Configure settings

    # Launch stormcloud.py program and begin comms with the server

def conduct_connectivity_test(server_name, server_port):
    logging.log(
        logging.INFO, "Attempting connectivity test with server: %s:%d" % (server_name, server_port)
    )

    send_hello_data = json.dumps({'hello': 'TWT',})
    return tls_send_json_data(send_hello_data, 'RAT', server_name, server_port)

def conduct_device_initial_survey(dtype):
    try:
        customer_id = 1
        device_type = dtype
        device_name = socket.gethostname()
        ip_address = socket.gethostbyname(device_name)
        operating_system = platform.platform()
        device_status = "Green"

    except Exception as e:
        logging.log(
            logging.ERROR, "Initial survey failed: %s" % e
        )

    finally:
        return json.dumps({
            'new_device_register': 1,
            'customer_id': customer_id,
            'device_type': device_type,
            'device_name': device_name,
            'ip_address': ip_address,
            'operating_system': operating_system,
            'device_status': device_status
        })

def tls_send_json_data(json_data, expected_response_data, server_name, server_port):
    s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.settimeout(10)

    wrappedSocket = ssl.wrap_socket(s, ssl_version=ssl.PROTOCOL_TLS)
    receive_data = None

    try:
        wrappedSocket.connect((server_name,server_port))

        print("Sending %s" % json_data)

        # Send the length of the serialized data first, then send the data
        wrappedSocket.send(bytes('%d\n',encoding="utf-8") % len(json_data))
        wrappedSocket.sendall(bytes(json_data,encoding="utf-8"))

        receive_data = wrappedSocket.recv(1024)

    except Exception as e:
        logging.log(
            logging.ERROR, "Send data failed: %s" % (e)
        )

    finally:
        wrappedSocket.close()
        if receive_data:
            if expected_response_data in receive_data.decode("utf-8"):
                return (0, receive_data)
        else:
            return (1, receive_data)

def initialize_logging():
    logging.basicConfig(
        filename='install.log',
        filemode='a',
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.DEBUG
    )

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--device-type", type=str, help="device type that stormcloud is being installed on (freeform text)")
    args = parser.parse_args()

    main(args.device_type)