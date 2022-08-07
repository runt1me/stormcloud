from datetime import datetime
import socket, ssl
import json
import platform
from subprocess import Popen, PIPE

import logging

import argparse

SERVER_NAME="www2.darkage.io"
SERVER_PORT=8443
STORMCLOUD_VERSION="1.0.0"

def main(device_type="Important Server (from installer)"):
    initialize_logging()
    logging.log(logging.INFO, "Beginning install of Stormcloud v%s" % STORMCLOUD_VERSION)

    ret, _ = conduct_connectivity_test(SERVER_NAME, SERVER_PORT)
    if ret != 0:
        logging.log(
            logging.ERROR, "Install failed (Unable to conduct connectivity test with server). Return code: %d" % ret
        )
        exit()
    
    logging.log(logging.INFO, "Successfully conducted connectivity test with server.")
    logging.log(logging.INFO, "Conducting initial device survey.")
    
    survey_data = conduct_device_initial_survey(device_type)
    ret, response_data = tls_send_json_data(survey_data, "register_new_device-response", SERVER_NAME, SERVER_PORT)
    if ret != 0:
        logging.log(logging.ERROR, "Install failed (Unable to send survey data to server). Return code: %d" % ret)
        exit()
    
    logging.log(logging.INFO, "Successfully sent new device registration request to server.")
    _ = save_key(response_data['secret_key'])

    logging.log(logging.INFO, "Successfully wrote device encryption key to ./secret.key")
    
    # Configure settings

    # Launch stormcloud.py program and begin comms with the server

def conduct_connectivity_test(server_name, server_port):
    logging.log(
        logging.INFO, "Attempting connectivity test with server: %s:%d" % (server_name, server_port)
    )

    send_hello_data = json.dumps({'request_type': 'Hello'})
    return tls_send_json_data(send_hello_data, 'hello-response', server_name, server_port)

def conduct_device_initial_survey(dtype):
    try:
        operating_system = platform.platform()
        if 'macOS' in operating_system:
            device_name, ip_address = get_name_and_address_info_mac()
        elif 'Windows' in operating_system:
            device_name, ip_address = get_name_and_address_info_windows()

        customer_id = 1
        device_type = dtype
        device_status = 1

    except Exception as e:
        print("Exception")
        logging.log(
            logging.ERROR, "Initial survey failed: %s" % e
        )

    finally:
        return json.dumps({
            'request_type': "register_new_device",
            'customer_id': customer_id,
            'device_type': device_type,
            'device_name': device_name,
            'ip_address': ip_address,
            'operating_system': operating_system,
            'device_status': device_status
        })

def get_name_and_address_info_mac():
    # Originally I tried to do socket.gethostbyname() on the hostname, but that usually spit out localhost
    # This way runs netstat -rn -f inet and gets the interface associated with the default route
    # Then runs ifconfig <interface> and gets the inet address on that interface
    # TODO: handle if netstat doesn't work to get the routing table (maybe net-tools is not installed?)
    device_name = socket.gethostname()

    process = Popen(['netstat', '-rn', '-f', 'inet'], stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate()

    default_route_line = [l for l in str(stdout).split("\\n") if 'default' in l][0]
    default_route_interface = default_route_line.split()[3]

    process = Popen(['ifconfig', default_route_interface], stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate()

    ifconfig_inet_line = [l for l in str(stdout).split('\\n\\t') if l.split()[0] == "inet"][0]
    ip_address = ifconfig_inet_line.split()[1]

    return device_name, ip_address

def get_name_and_address_info_windows():
    return socket.gethostname(), socket.gethostbyname(device_name)

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
            data_json = json.loads(receive_data)
            print(data_json)
            if expected_response_data in data_json:
                return (0, data_json)
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

def save_key(key):
    key = key.encode("utf-8")

    with open('secret.key', 'wb') as keyfile:
        keyfile.write(key)

    return 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--device-type", type=str, help="device type that stormcloud is being installed on (freeform text)")
    args = parser.parse_args()

    main(args.device_type)