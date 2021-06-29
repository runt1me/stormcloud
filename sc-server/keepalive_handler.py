import socket
import sys

addr = ("", 8080)
sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)

sock.bind(addr)

#listen for incoming connections
sock.listen(1)
while True:
    print("waiting for a connection")
    connection, client_address = sock.accept()

    try:
        print("connection %s: %s" % (connection,client_address))
        while True:
            data = connection.recv(8)
            print("received %s" % data)

            if data:
                print("sending response")
                response_data = b'message received'
                connection.sendall(response_data)
            else:
                print("no more data from client")
                break
    finally:
        connection.close()
        
