from datetime import datetime, timedelta
from os import walk
from time import sleep
import pathlib

import json

import socket, ssl
import logging

import crypto_utils

SERVER_NAME = "www2.darkage.io"
SERVER_PORT = 9443

def ship_file_to_server(api_key,agent_id,path):
    encrypted_content, encrypted_size   = crypto_utils.encrypt_file(path)
    encrypted_path, encrypted_path_size = crypto_utils.encrypt_content(path)

    file_backup_request_data = json.dumps({
        'request_type': "backup_file",
        'api_key': api_key,
        'agent_id': agent_id,
        'file_content': encrypted_content.decode("utf-8"),
        'file_path': encrypted_path.decode("utf-8")
    })

    logging.log(logging.INFO,"Sending to %s:%s" % (SERVER_NAME,SERVER_PORT))
    logging.log(logging.INFO,dump_file_info(path,encrypted_size))
    ret, response_data = tls_send_json_data(file_backup_request_data, "backup_file-response", SERVER_NAME, SERVER_PORT)

    sleep(0.1)

def tls_send_json_data(json_data, expected_response_data, server_name, server_port, show_json=False):
    s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)

    timeout = calculate_timeout(len(json_data))
    s.settimeout(timeout)

    wrappedSocket = ssl.wrap_socket(s, ssl_version=ssl.PROTOCOL_TLS)
    receive_data = None

    try:
        wrappedSocket.connect((server_name,server_port))

        if show_json:
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

def dump_file_info(path,encrypted_size):
    logging.log(logging.INFO,"==== SENDING FILE : INFO ====")
    logging.log(logging.INFO,"\tPATH: %s" %path)
    logging.log(logging.INFO,"\tSIZE WHEN ENCRYPTED: %d" %encrypted_size)

def calculate_timeout(data_length):
    # TODO: address issues with timeouts.
    # maybe change timeout based on how much data is being sent?
    # import speedtest; s = speedtest.Speedtest(); s.get_servers(); s.get_best_server(); s.download(); s.upload();
    # res = s.results.dict(); return res['download'], res['upload'], res['ping']
    return 300