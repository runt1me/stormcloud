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
                data = connection.recv(560)
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if data:
                    print(data)

        finally:
            connection.close()

def parse_client_keepalive(client_pkt):
    #clean up byte array by removing b''
    client_pkt_clean = str(client_pkt).replace("b","").replace("'","")

    client_id = int(client_pkt_clean.split(",")[0])
    return client_id

def record_keepalive(client_id,current_time):
    print("recording keepalive")

    if not client_is_known(client_id):
        add_client_to_file(client_id)

    record_keepalive_for_client(client_id,current_time)

def client_is_known(client_id):
    clients = []
    with open("/root/stormcloud/keepalives.csv","r") as keepalive_file:
        for line in [l for l in keepalive_file.read().split("\n") if l]:
            clients.append(int(line.split(",")[0]))

    return client_id in clients

def add_client_to_file(client_id):
    with open("/root/stormcloud/keepalives.csv","a") as keepalive_file:
        keepalive_file.write("%d,\n" % client_id)

def record_keepalive_for_client(client_id,current_time):

    #in order to update the file, read the whole thing first,
    #find the line to modify and change it, and then rewrite the whole file
    #this is a quick and dirty approach that wont apply once we implement a database
    with open("/root/stormcloud/keepalives.csv","r") as keepalive_file:
        original_lines = [l for l in keepalive_file.read().split("\n") if l]
        clients = [int(l.split(",")[0]) for l in original_lines]
        line_to_modify_idx = clients.index(client_id)

        original_lines[line_to_modify_idx] = "%d,%s\n" % (client_id,current_time)

    with open("/root/stormcloud/keepalives.csv","w") as keepalive_file:
        for line in original_lines:
            keepalive_file.write(line)

def display_file():
    with open("/root/stormcloud/keepalives.csv","r") as keepalive_file:
        for line in [l for l in keepalive_file.read().split("\n") if l]:
            print(line)

if __name__ == "__main__":
    main()
