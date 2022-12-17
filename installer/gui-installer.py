from datetime import datetime
import socket, ssl
import json
import platform
from subprocess import Popen, PIPE

import logging
import argparse

import tkinter as tk
from tkinter import filedialog

# saving this as a test case for later when i make unit tests
#ret, _ = tls_send_json_data("not valid json data", "response", SERVER_NAME, SERVER_PORT)

SERVER_NAME="www2.darkage.io"
SERVER_PORT=8443
STORMCLOUD_VERSION="1.0.0"

def main(device_type, send_logs, backup_time, keepalive_freq, backup_paths, backup_paths_recursive, api_key_file_path):
    initialize_logging()
    logging.log(logging.INFO, "Beginning install of Stormcloud v%s" % STORMCLOUD_VERSION)

    api_key = read_api_key_file(api_key_file_path)

    ret, _ = conduct_connectivity_test(api_key, SERVER_NAME, SERVER_PORT)
    if ret != 0:
        logging.log(
            logging.ERROR, "Install failed (Unable to conduct connectivity test with server). Return code: %d. Please verify that you are connected to the internet." % ret
        )
        exit()
    
    logging.log(logging.INFO, "Successfully conducted connectivity test with server.")
    logging.log(logging.INFO, "Conducting initial device survey...")
    
    survey_data = conduct_device_initial_survey(api_key,device_type)

    logging.log(logging.INFO, "Device survey complete.")

    logging.log(logging.INFO, "Sending device registration request to server...")
    ret, response_data = tls_send_json_data(survey_data, "register_new_device-response", SERVER_NAME, SERVER_PORT)
    if ret != 0:
        logging.log(logging.ERROR, "Install failed (Unable to send survey data to server). Return code: %d" % ret)
        exit()
    
    logging.log(logging.INFO, "Device successfully registered.")

    secret_key = response_data['secret_key']
    logging.log(logging.INFO, "Received device encryption key.")

    agent_id = response_data['agent_id']
    logging.log(logging.INFO, "Received agent ID.")

    logging.log(logging.INFO, "Configuring backup process and writing settings file.")
    ret = configure_settings(
        send_logs,
        backup_time,
        keepalive_freq,
        backup_paths,
        backup_paths_recursive,
        secret_key,
        agent_id,
        api_key
    )

    logging.log(logging.INFO, "Ready to launch stormcloud!")

def conduct_connectivity_test(api_key,server_name,server_port):
    logging.log(
        logging.INFO, "Attempting connectivity test with server: %s:%d" % (server_name, server_port)
    )

    send_hello_data = json.dumps({'request_type':'Hello','api_key':api_key})
    return tls_send_json_data(send_hello_data, 'hello-response', server_name, server_port)

def conduct_device_initial_survey(api_key,dtype):
    try:
        operating_system = platform.platform()

        if 'macOS' in operating_system:
            device_name, ip_address = get_name_and_address_info_mac()
        elif 'Windows' in operating_system:
            device_name, ip_address = get_name_and_address_info_windows()

        device_type = dtype
        device_status = 1

    except Exception as e:
        logging.log(
            logging.ERROR, "Initial survey failed: %s" % e
        )

    finally:
        return json.dumps({
            'request_type': "register_new_device",
            'api_key': api_key,
            'device_type': device_type,
            'device_name': device_name,
            'ip_address': ip_address,
            'operating_system': operating_system,
            'device_status': device_status
        })

def get_name_and_address_info_mac():
    # Originally I tried to do socket.gethostbyname() on the hostname, but that usually spit out localhost
    # This way runs netstat -rn -f inet and gets the interface associated with the default route
    # Then runs ifconfig <interface> and gets the inet address on that interface
    # TODO: handle if netstat doesn't work to get the routing table (maybe net-tools is not installed?)

    try:
        device_name = socket.gethostname()

    except Exception as e:
        logging.log(
            logging.ERROR, "Unable to get device name: %s" % e
        )
        device_name = "UNKNOWN_HOSTNAME"

    try: 
        process = Popen(['netstat', '-rn', '-f', 'inet'], stdout=PIPE, stderr=PIPE)
        stdout, stderr = process.communicate()

        default_route_line = [l for l in str(stdout).split("\\n") if 'default' in l][0]
        default_route_interface = default_route_line.split()[3]

        process = Popen(['ifconfig', default_route_interface], stdout=PIPE, stderr=PIPE)
        stdout, stderr = process.communicate()

        ifconfig_inet_line = [l for l in str(stdout).split('\\n\\t') if l.split()[0] == "inet"][0]
        ip_address = ifconfig_inet_line.split()[1]

    except Exception as e:
        logging.log(
            logging.ERROR, "Unable to get IP address: %s" %e
        )
        ip_address = "UNKNOWN_IP_ADDRESS"

    return device_name, ip_address
 
def get_name_and_address_info_windows():
    # Runs route print -4 and gets the address associated with the default route
    # TODO: handle if route print -4 doesnt work?
    device_name = socket.gethostname()

    process = Popen(['route', 'print', '-4'], stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate()

    lines = [l for l in stdout.decode("utf-8").split("\r\n") if l]
    default_route_line = [l for l in lines if l.split()[0] == '0.0.0.0'][0]
    default_route_address = default_route_line.split()[3]

    return device_name, default_route_address

def read_api_key_file(keyfile_path):
    with open(keyfile_path,'rb') as keyfile:
        api_key = keyfile.read()

    return api_key.decode("utf-8")

def configure_settings(send_logs, backup_time, keepalive_freq, backup_paths, backup_paths_recursive, secret_key, agent_id, api_key):
    backup_time    = int(backup_time)
    keepalive_freq = int(keepalive_freq)

    with open("settings.cfg", "w") as settings_file:
        lines_to_write = []

        # Logging
        lines_to_write.append("# send logging and error information to dark age servers")
        lines_to_write.append("# to assist with development/bug fixes/discovery of errors")
        lines_to_write.append("# 1 = ON, 0 = OFF")
        if send_logs:
            lines_to_write.append("SEND_LOGS 1")
        else:
            lines_to_write.append("SEND_LOGS 0")

        # Backup time
        lines_to_write.append("# controls backup time of day")
        lines_to_write.append("# hour of the day/24hr time")
        lines_to_write.append("# i.e. 23 = 11PM (system time)")
        lines_to_write.append("BACKUP_TIME %d" % backup_time)

        # Keepalive frequency
        lines_to_write.append("# controls how frequently this device will send keepalive message to the stormcloud servers.")
        lines_to_write.append("# Interval in seconds (90=send keepalive every 90 seconds)")
        lines_to_write.append("KEEPALIVE_FREQ %d" % keepalive_freq)

        # Secret Key
        lines_to_write.append("# symmetric key for device encryption")
        lines_to_write.append("SECRET_KEY %s" % secret_key)
        
        # Agent ID
        lines_to_write.append("# Agent ID, for identifying this device to the stormcloud servers")
        lines_to_write.append("AGENT_ID %s" % agent_id)

        # API key my husband is so smart
        lines_to_write.append("# API key")
        lines_to_write.append("API_KEY %s" % api_key)

        # Backup paths
        lines_to_write.append("# paths to backup")
        lines_to_write.append("BACKUP_PATHS")
        for bp in backup_paths:
            lines_to_write.append("%s" % bp)

        # Recursive backup paths
        lines_to_write.append("# paths to recursively backup")
        lines_to_write.append("RECURSIVE_BACKUP_PATHS")
        if backup_paths_recursive:
            for rbp in backup_paths_recursive:
                lines_to_write.append("%s" % rbp)

        output_string = "\n".join(lines_to_write)
        settings_file.write(output_string)

def tls_send_json_data(json_data, expected_response_data, server_name, server_port):
    if not validate_json(json_data):
        logging.log("Invalid JSON data received in tls_send_json_data(); not sending to server.")
        return

    s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.settimeout(10)

    wrappedSocket = ssl.wrap_socket(s, ssl_version=ssl.PROTOCOL_TLS)
    receive_data = None

    try:
        wrappedSocket.connect((server_name,server_port))

        print("Sending %s" % json_data)
        logging.log(
            logging.INFO, "Sending %s" %json_data
        )

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

            logging.log(
                logging.INFO, "Received data: %s" %data_json
            )

            if expected_response_data in data_json:
                return (0, data_json)
        else:
            return (1, receive_data)

def validate_json(data):
    try:
        json.loads(data)
    except json.decoder.JSONDecodeError:
        return False
    else:
        return True

def initialize_logging():
    logging.basicConfig(
        filename='install.log',
        filemode='a',
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.DEBUG
    )

class MainApplication(tk.Frame):
    def __init__(self,parent,*args,**kwargs):
        tk.Frame.__init__(self,parent,*args,**kwargs)
        self.parent = parent
        self.backup_paths = []
        self.recursive_backup_paths = []
        self.api_key_file_path = ""
        self.configure_gui()

    def __str__(self):
        return "%s" % vars(self)

    def configure_gui(self):
        self.add_device_name_label_and_entry()
        self.add_backup_paths_labels_and_browse_button()
        self.add_recursive_backup_paths_labels_and_browse_button()
        self.add_api_key_labels_and_browse_button()
        self.add_submit_button()
        self.add_error_label()

    def add_device_name_label_and_entry(self):
        self.device_name_label                   = tk.Label(window,text="Device Nickname",bg="white")
        self.device_name_label.place(x = 30, y = 100)

        self.device_name_entry                   = tk.Entry(window, width=50)
        self.device_name_entry.place(x = 200, y = 100)

    def add_backup_paths_labels_and_browse_button(self):
        self.backup_paths_label                  = tk.Label(window,text="Paths to backup",bg="white")
        self.backup_paths_label.place(x = 30, y = 150)

        self.backup_paths_actual_label           = tk.Label(window,bg="white")
        self.backup_paths_actual_label.place(x = 200, y = 150)

        self.paths_browse_button                 = tk.Button(window,text="Add a Folder",command=self.browse_files)
        self.paths_browse_button.place(x = 600, y = 150)

    def add_recursive_backup_paths_labels_and_browse_button(self):
        self.recursive_backup_paths_label        = tk.Label(window,text="Recursive paths to backup",bg="white")
        self.recursive_backup_paths_label.place(x = 30, y = 200)

        self.recursive_backup_paths_actual_label = tk.Label(window,bg="white")
        self.recursive_backup_paths_actual_label.place(x = 200, y = 200)

        self.recursive_paths_browse_button       = tk.Button(window,text="Add a Folder",command=self.browse_files_recursive)
        self.recursive_paths_browse_button.place(x = 600, y = 200)

    def add_api_key_labels_and_browse_button(self):
        self.api_key_label                       = tk.Label(window,text="Path to API key file",bg="white")
        self.api_key_label.place(x = 30, y = 250)

        self.api_key_actual_label                = tk.Label(window,bg="white")
        self.api_key_actual_label.place(x = 200, y = 250)

        self.api_key_browse_button               = tk.Button(window,text="Select a File",command=self.browse_api_key)
        self.api_key_browse_button.place(x = 600, y = 250)

    def add_submit_button(self):
        self.submit_button                       = tk.Button(window,text="Install",width=20,command=self.verify_settings_and_close_gui)
        self.submit_button.place(x = 120, y = 300)

    def add_error_label(self):
        self.error_label                         = tk.Label(window,text="",bg="white",fg="red")
        self.error_label.place(x = 50, y = 350)

        # TODO: add
        # checkbox for "send diagnostic logs to help developers troubleshoot issues with my devices." default to yes
        # advanced settings (make a openable tab somehow):
        # keepalive frequency - default to 300 seconds

    def browse_files(self):
        filename = tk.filedialog.askdirectory(
            initialdir = "/",
            title = "Select a Folder",
        )

        if filename:
            self.backup_paths.append(filename)
            self.backup_paths_actual_label.configure(text=",".join(self.backup_paths))

    def browse_files_recursive(self):
        filename = filedialog.askdirectory(
            initialdir = "/",
            title = "Select a Folder",
        )

        if filename:
            self.recursive_backup_paths.append(filename)
            self.recursive_backup_paths_actual_label.configure(text=",".join(self.recursive_backup_paths))

    def browse_api_key(self):
        filename = filedialog.askopenfilename(
            initialdir = ".",
            title = "Select your API key file",
        )

        if filename:
            self.api_key_file_path = filename
            self.api_key_actual_label.configure(text="%s" % filename)

    def verify_settings_and_close_gui(self):
        if self.verify_settings():
            window.quit()

    def verify_settings(self):
        if not self.recursive_backup_paths and not self.backup_paths:
            error_text = "You must have at least one path to backup."
            self.error_label.configure(text="Error: %s" %error_text)

            return False

        if not self.api_key_file_path:
            error_text = "You must provide the path to your API key."
            self.error_label.configure(text="Error: %s" %error_text)

            return False

        return True

if __name__ == '__main__':
    window = tk.Tk()
    app = MainApplication(window)
    window.title("Stormcloud Installer")
    window.geometry("700x500")
    window.config(background="white")

    window.mainloop()
    
    print(app.backup_paths)
    print(app.recursive_backup_paths)
    print(app.api_key_file_path)

    send_logs = True

    # TODO: figure out how to get device type out of GUI
    device_type = "Just a computer"
    backup_time = 23
    keepalive_freq = 300

    if not app.recursive_backup_paths and not app.backup_paths:
        raise Exception("Must have at least one path to backup.")

    if not app.api_key_file_path:
        raise Exception("You must provide the path to your API key.")

    main(
        device_type,
        send_logs,
        backup_time,
        keepalive_freq,
        app.backup_paths,
        app.recursive_backup_paths,
        app.api_key_file_path
    )