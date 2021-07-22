import socket
import sys
from datetime import datetime

def main():
    addr = ("", 8083)
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
                header = connection.recv(560)
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if header:
                    client_field = header[0:16]
                    file_path_field = header[16:528]
                    length_field = header[528:560]

                    print('Receiving file from client %s' % client_field.decode('ascii'))
                    print(file_path_field.decode('ascii'))

                delimiter = connection.recv(11)
                if delimiter:
                    print(delimiter.decode('ascii'))

                raw_content = connection.recv(get_content_length(length_field))
                if raw_content:
                    print("==RAW BYTES==")
                    print(raw_content)
                    print(len(raw_content))

        finally:
            connection.close()
            exit()

def get_content_length(length_field):
    #replace null characters with '' for the purpose of converting string -> int
    print("receiving %d bytes" % int(length_field.decode('ascii').replace('\x00','')))
    return int(length_field.decode('ascii').replace('\x00',''))

def parse_client_keepalive(client_pkt):
    #clean up byte array by removing b''
    client_pkt_clean = str(client_pkt).replace("b","").replace("'","")

    client_id = int(client_pkt_clean.split(",")[0])
    return client_id




if __name__ == "__main__":
    main()
