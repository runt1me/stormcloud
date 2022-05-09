import socket
import sys
from datetime import datetime

import logging

import database_utils as db

def main():
    initialize_logging()
    sock = initialize_socket()

    sock.listen(1)
    #TODO: handle random junk coming into 8080
    #or maybe pick a different port?
    while True:
        logging.log(logging.INFO,"KEEPALIVE_HANDLER is waiting for a connection")
        connection, client_address = sock.accept()

        try:
            logging.log(logging.INFO,"connection %s: %s" % (connection,client_address))
            while True:
                data = connection.recv(16)
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if data:
                    response_data = b'message received'
                    connection.sendall(response_data)

                    client_id = parse_client_keepalive(data)
                    record_keepalive(client_id,current_time)
                else:
                    break
        finally:
            connection.close()

def parse_client_keepalive(client_pkt):
    #clean up byte array by removing b''
    client_pkt_clean = str(client_pkt).replace("b","").replace("'","")

    client_id = int(client_pkt_clean.split(",")[0])
    return client_id

def record_keepalive(client_id,current_time):
    logging.log(logging.INFO,"recording keepalive for device %d" %client_id)
    db.update_callback_for_device(client_id,current_time,0)

def initialize_logging():
    logging.basicConfig(
            filename='/var/log/stormcloud_ka.log',
            filemode='a',
            format='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=logging.DEBUG
    )

def initialize_socket():
    addr = ("", 8080)
    sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)

    sock.bind(addr)
    return sock

if __name__ == "__main__":
    main()
