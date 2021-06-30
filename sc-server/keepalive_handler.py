import socket
import sys

def main():

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
                data = connection.recv(16)
                print("received %s" % data)

                if data:
                    print("sending response")
                    response_data = b'message received'
                    connection.sendall(response_data)
                    client_id = parse_client_keepalive(data)
                    print("saw client id %d" % client_id)

                else:
                    print("no more data from client")
                    break
        finally:
            connection.close()

def parse_client_keepalive(client_pkt):
    #clean up byte array by removing b''
    client_pkt_clean = str(client_pkt).replace("b","").replace("'","")

    client_id = int(client_pkt_clean.split(",")[0])
    return client_id

if __name__ == "__main__":
    main()
