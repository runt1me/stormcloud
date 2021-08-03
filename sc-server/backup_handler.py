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
        print("Listening for connections...")
        connection, client_address = sock.accept()

        print("connection %s: %s" % (connection,client_address))
        header = connection.recv(560)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if header:
            client = get_client_id(header[0:16])
            file_path = get_file_path(header[16:528])
            length = get_content_length(header[528:560])

            print('Receiving file from client %d' % client)
            print(file_path)

        check_result = perform_integrity_check_delimiter(connection.recv(11))
        if check_result:
            print("delimiter validated, continuing")
        else:
            print("invalid delimiter")

        bytes_to_receive = length
        raw_content = b''

        while bytes_to_receive > 0:
            bytes_recvd = connection.recv(bytes_to_receive)
            raw_content += bytes_recvd
            if raw_content:
                print("(Received %d bytes)" % len(bytes_recvd))

            bytes_to_receive = bytes_to_receive - len(bytes_recvd)

        #store file
        store_file(client,file_path,length,raw_content)

def get_content_length(length_field):
    #replace null characters with '' for the purpose of converting string -> int
    length_field_as_string = length_field.decode('ascii').replace('\x00','')
    return int(length_field_as_string)

def get_file_path(path_field):
    return path_field.decode('ascii').replace('\x00','')

def get_client_id(client_id_field):
    client_id_as_string = client_id_field.decode('ascii').replace('\x00','')
    return int(client_id_as_string)

def store_file(client_id,file_path,file_length,file_raw_content):
    print("== STORING FILE : %s ==" %file_path)
    print("Client ID:\t%d" % client_id)
    print("File Length:\t%d" % file_length)

    #TODO: check and authenticate that its a legitimate client id
    #to prevent against spoofed packets and attacks
    #encryption should help with this, but also should have a 2-factor key
    #RSA style??
    client_id_root_folder = "/storage/%d/" % client_id

    #TODO: figure out a way to manage the directory structure so that the hierarchy is preserved
    #for now i am stripping out the directory structure and just doing the filename
    file_path_stripped = file_path.split("\\")[-1]
    path_on_server = client_id_root_folder + file_path_stripped

    print("writing content to %s" % path_on_server)
    with open(path_on_server,'wb') as outfile:
        outfile.write(file_raw_content)

def perform_integrity_check_delimiter(delim):
    return delim == "~||~TWT~||~"


if __name__ == "__main__":
    main()
