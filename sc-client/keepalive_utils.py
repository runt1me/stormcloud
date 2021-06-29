from time import sleep

import socket
import sys

import logging

CONNECTION_SERVER = "www2.darkage.io"
CONNECTION_PORT = 8080

def execute_ping_loop(interval,name):
    while True:
        sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        server_address = (CONNECTION_SERVER,CONNECTION_PORT)

        print("connecting to %s port %s" % server_address)
        sock.connect(server_address)
        try:
            message = wrap_keepalive_data()
            print("sending message '%s'" % message)
            sock.sendall(message)

            #bytes expected to be sent and recvd
            amount_recvd = 0
            amount_expected = 16

            while amount_recvd < amount_expected:
                data = sock.recv(16)
                amount_recvd += len(data)
                print("received %s" % data)

        finally:
            print("closing socket")
            sock.close()

        sleep(interval)

def wrap_keepalive_data():
    return b'1,clienthello'