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

def main(device_type, send_logs, backup_time, keepalive_freq, backup_paths):
    initialize_logging()
    logging.log(logging.INFO, "Beginning install of Stormcloud v%s" % STORMCLOUD_VERSION)

    ret, _ = conduct_connectivity_test(SERVER_NAME, SERVER_PORT)
    if ret != 0:
        logging.log(
            logging.ERROR, "Install failed (Unable to conduct connectivity test with server). Return code: %d" % ret
        )
        exit()
    
    logging.log(logging.INFO, "Successfully conducted connectivity test with server.")
    logging.log(logging.INFO, "Conducting initial device survey...")
    
    survey_data = conduct_device_initial_survey(device_type)

    logging.log(logging.INFO, "Device survey complete.")

    logging.log(logging.INFO, "Sending device registration request to server...")
    ret, response_data = tls_send_json_data(survey_data, "register_new_device-response", SERVER_NAME, SERVER_PORT)
    if ret != 0:
        logging.log(logging.ERROR, "Install failed (Unable to send survey data to server). Return code: %d" % ret)
        exit()
    
    logging.log(logging.INFO, "Device successfully registered.")

    _ = save_key(response_data['secret_key'])
    logging.log(logging.INFO, "Received device encryption key and wrote to ./secret.key")
    
    logging.log(logging.INFO, "Configuring backup process and writing settings file.")
    ret = configure_settings(send_logs, backup_time, keepalive_freq, backup_paths)

    logging.log(logging.INFO, "Ready to launch stormcloud!")
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

def save_key(key):
    key = key.encode("utf-8")

    with open('secret.key', 'wb') as keyfile:
        keyfile.write(key)

    return 0

def configure_settings(send_logs, backup_time, keepalive_freq, backup_paths):
    backup_time    = int(backup_time)
    keepalive_freq = int(keepalive_freq)

    with open("settings.cfg", "w") as settings_file:
        lines_to_write = []

        # Logging
        lines_to_write.append("# send logging and error information to dark age servers")
        lines_to_write.append("# to assist with development/bug fixes/discovery of errors")
        lines_to_write.append("# 1 = ON, 0 = OFF")
        if send_logs:
            lines_to_write.append("SEND_LOGS 1")
        else:
            lines_to_write.append("SEND_LOGS 0")

        # Backup time
        lines_to_write.append("# controls backup time of day")
        lines_to_write.append("# hour of the day/24hr time")
        lines_to_write.append("# i.e. 23 = 11PM (system time)")
        lines_to_write.append("BACKUP_TIME %d" % backup_time)

        # Keepalive frequency
        lines_to_write.append("# controls how frequently this device will send keepalive message to the stormcloud servers.")
        lines_to_write.append("# Interval in seconds (90=send keepalive every 90 seconds)")
        lines_to_write.append("KEEPALIVE_FREQ %d" % keepalive_freq)

        # Backup paths
        lines_to_write.append("# paths to backup")
        for bp in backup_paths:
            lines_to_write.append("%s" % bp)

        output_string = "\n".join(lines_to_write)
        settings_file.write(output_string)

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

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--device-type", type=str, required=True, help="device type that stormcloud is being installed on (freeform text)")
    parser.add_argument("-l", "--send-logs", type=int, default=1, help="send logs to assist with debugging/development of Stormcloud (1 or 0)")
    parser.add_argument("-t", "--backup-time", type=int, default=20, help="time of day (24hr) to perform the daily Stormcloud backup process")
    parser.add_argument("-k", "--keepalive-freq", type=int, default=100, help="frequency (in seconds) to send keepalives for this device to the Stormcloud servers")
    parser.add_argument("-p", "--backup-paths", type=str, required=True, help="Filesystem paths to backup, comma-separated")

    args = parser.parse_args()

    backup_paths_parsed = []
    for path in args.backup_paths.split(","):
        backup_paths_parsed.append(path)

    main(args.device_type, args.send_logs, args.backup_time, args.keepalive_freq, backup_paths_parsed)