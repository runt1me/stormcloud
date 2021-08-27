from time import sleep
import random

import socket
import sys

import logging

CONNECTION_SERVER = "www2.darkage.io"
CONNECTION_PORT = 8080

PACKET_LEN = 16

def execute_ping_loop(interval,client_id,name):
    while True:
        sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        server_address = (CONNECTION_SERVER,CONNECTION_PORT)

        logging.log(logging.INFO,"connecting to %s port %s" % server_address)
        sock.connect(server_address)
        try:
            ka = wrap_keepalive_data(client_id)
            logging.log(logging.INFO,"sending keepalive")
            sock.sendall(ka)

            #bytes expected to be sent and recvd
            amount_recvd = 0
            amount_expected = 16

            while amount_recvd < amount_expected:
                data = sock.recv(16)
                amount_recvd += len(data)
                logging.log(logging.INFO,"received %s" % data)

        finally:
            logging.log(logging.INFO,"closing socket")
            sock.close()

        sleep(interval)

def wrap_keepalive_data(client_id):
    #TODO: encrypt!!
    msg_text = '%d,%d' % (client_id,random.randint(0,1000000))
    
    #pad message
    len_to_pad = PACKET_LEN - len(msg_text)
    logging.log(logging.INFO,"adding %d characters to msg %s" % (len_to_pad,msg_text))

    #encode ascii to convert str to bytes
    final_msg = (msg_text + ("." * len_to_pad)).encode('ascii')
    return final_msg