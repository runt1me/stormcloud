#!/usr/bin/python
import socket, ssl

BIND_PORT=8443

def main():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    context.load_cert_chain(certfile="/root/certs/cert.pem")

    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.bind(('0.0.0.0',BIND_PORT))
    s.listen(5)

    print("Listening for connections")

    try:
        while True:
            connection, client_address = s.accept()
            wrappedSocket = ssl.wrap_socket(
                    connection,
                    server_side=True,
                    certfile="/root/certs/cert.pem",
                    keyfile="/root/certs/cert.pem",
                    ssl_version=ssl.PROTOCOL_TLS
            )
    
            request = wrappedSocket.recv(1024)
            print(request)
    
            if request:
                response_data = b'RAT'
                wrappedSocket.sendall(response_data)
            else:
                break
    finally:
        wrappedSocket.close()



if __name__ == "__main__":
    main()
