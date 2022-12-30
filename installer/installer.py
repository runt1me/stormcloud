from datetime import datetime
import socket, ssl
import json
import platform
from subprocess import Popen, PIPE

import logging
import argparse

from time import sleep

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import filedialog

import webbrowser

# saving this as a test case for later when i make unit tests
#ret, _ = tls_send_json_data("not valid json data", "response", SERVER_NAME, SERVER_PORT)

SERVER_NAME="www2.darkage.io"
SERVER_PORT=8443
STORMCLOUD_VERSION="1.0.0"

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
        self.device_name = ""
        self.stdout_msgs = []

        self.backup_label_current_row = 1
        self.backup_paths_master_list = []

        self.configure_gui()

    def __str__(self):
        return "%s" % vars(self)

    def configure_gui(self):
        self.add_device_name_label_and_entry()
        self.add_backup_paths_labels()
        self.add_backup_browse_button()
        self.add_api_key_labels()
        self.add_api_key_browse_button()
        self.add_diagnostic_checkbox_and_label()
        self.add_submit_button()
        self.add_error_label()
        self.add_stdout_label()

    def add_device_name_label_and_entry(self):
        self.device_name_label                   = tk.Label(window,text="Device Nickname",bg="white")
        self.device_name_label.grid(row=0,column=0,padx=(30,15),pady=(100,20),sticky=tk.W)

        self.device_name_entry                   = tk.Entry(window, width=50)
        self.device_name_entry.grid(row=0,column=1,padx=(15,15),pady=(100,20),columnspan=3,sticky=tk.E)

    def add_backup_paths_labels(self):
        self.backup_paths_label                  = tk.Label(window,text="Paths to backup",bg="white")
        self.backup_paths_label.grid(row=1,column=0,padx=(30,15),pady=(0,5),sticky=tk.NS)

    def add_backup_browse_button(self):
        # Place backup label and checkboxes at self.backup_label_current_row
        self.paths_browse_button                 = tk.Button(window,text="Add a Folder",bg="blue",command=self.browse_files)
        self.paths_browse_button.grid(row=2,column=0,padx=(30,15),pady=(0,10),sticky=tk.NS)

    def add_api_key_labels(self):
        self.api_key_label                       = tk.Label(window,text="Path to API key file",bg="white")
        self.api_key_label.grid(row=3,column=0,padx=(30,15),pady=(0,10),sticky=tk.W)

        self.api_key_actual_label                = tk.Label(window,bg="white")
        self.api_key_actual_label.grid(row=3,column=1,padx=(15,15),pady=(0,10),sticky=tk.W)

    def add_api_key_browse_button(self):
        self.api_key_browse_button               = tk.Button(window,text="Select a File",command=self.browse_api_key)
        self.api_key_browse_button.grid(row=4,column=0,padx=(30,15),pady=(0,10),sticky=tk.NS)

    def add_diagnostic_checkbox_and_label(self):
        def callback(url):
            webbrowser.open_new_tab(url)

        self.agree_checkbox                  = ttk.Checkbutton(window)

        # clear checkbox "half-checked" state and set new state
        self.agree_checkbox.state(['!alternate'])
        self.agree_checkbox.state(['!disabled','selected'])

        self.agree_checkbox.grid(row=5,column=0,padx=(30,5),pady=(0,20),sticky=tk.E)

        self.link_label                      = tk.Label(window, text="I agree to the Stormcloud Terms and Conditions.", fg="blue", cursor="hand2")
        self.link_label.bind("<Button-1>", lambda e: callback("https://www.github.com/runt1me/stormcloud"))
        self.link_label.grid(row=5,column=1,padx=(0,15),pady=(0,20),columnspan=3,sticky=tk.W)

    def add_submit_button(self):
        self.submit_button                       = tk.Button(window,text="Install",width=20,command=self.verify_settings_and_begin_install)
        self.submit_button.place(x = 120, y = 300)
        self.submit_button.grid(row=6,column=0,padx=(40,0),pady=(0,20),columnspan=2,sticky=tk.NS)

    def add_error_label(self):
        self.error_label                         = tk.Label(window,text="",bg="white",fg="red")
        self.error_label.grid(row=7,column=0,padx=(40,0),pady=(0,5),columnspan=2,sticky=tk.NS)

    def add_stdout_label(self):
        self.stdout_label                        = tk.Label(window,text="",bg="white",fg="green",anchor="w",justify=tk.LEFT)
        self.stdout_label.grid(row=8,column=0,padx=(40,0),pady=(0,20),columnspan=2,sticky=tk.NS)

    def browse_files(self):
        filename = tk.filedialog.askdirectory(
            initialdir = "/",
            title = "Select a Folder",
        )

        if filename:
            # TODO: clean this hot garbage up later
            # Add file path label, checkbox and label in the correct row
            actual_label_this_row = tk.Label(window,bg="white")
            actual_label_this_row.grid(
                row=self.backup_label_current_row,
                column=1,
                padx=(15,15),pady=(0,5),
                sticky=tk.W
            )

            actual_label_this_row.configure(text=filename)

            checkbox_this_row = ttk.Checkbutton(window)
            checkbox_this_row.state(['!alternate'])
            checkbox_this_row.state(['!disabled','selected'])

            checkbox_this_row.grid(
                row=self.backup_label_current_row,
                column=2,
                padx=(15,0),pady=(0,5),
                sticky=tk.E
            )

            include_subfolders_label_this_row = tk.Label(window,bg="white")
            include_subfolders_label_this_row.grid(
                row=self.backup_label_current_row,
                column=3,
                padx=(0,15),pady=(0,5),
                sticky=tk.W
            )

            include_subfolders_label_this_row.configure(text="Include Subfolders")

            # Add to master list of paths and rows
            self.backup_paths_master_list.append((filename, checkbox_this_row))

            # Increment row
            self.backup_label_current_row += 1

            if self.backup_label_current_row > 1:
                # Move everything below this row down
                self.api_key_label.grid(row=self.api_key_label.grid_info()['row']+1)
                self.api_key_actual_label.grid(row=self.api_key_actual_label.grid_info()['row']+1)
                self.api_key_browse_button.grid(row=self.api_key_browse_button.grid_info()['row']+1)
                self.agree_checkbox.grid(row=self.agree_checkbox.grid_info()['row']+1)
                self.link_label.grid(row=self.link_label.grid_info()['row']+1)
                self.submit_button.grid(row=self.submit_button.grid_info()['row']+1)
                self.error_label.grid(row=self.error_label.grid_info()['row']+1)
                self.stdout_label.grid(row=self.stdout_label.grid_info()['row']+1)

    def browse_api_key(self):
        filename = filedialog.askopenfilename(
            initialdir = ".",
            title = "Select your API key file",
        )

        if filename:
            self.api_key_file_path = filename
            self.api_key_actual_label.configure(text="%s" % filename)

    def verify_settings_and_begin_install(self):
        self.device_name = self.device_name_entry.get()

        for path, checkbox in self.backup_paths_master_list:
            if checkbox.instate(['selected']):
                self.recursive_backup_paths.append(path)
            else:
                self.backup_paths.append(path)

        if self.verify_settings():
            self.begin_install()

    def verify_settings(self):
        if not self.device_name:
            error_text = "You must supply a device name."
            self.error_label.configure(text="Error: %s" %error_text)

            return False

        if not self.recursive_backup_paths and not self.backup_paths:
            error_text = "You must have at least one path to backup."
            self.error_label.configure(text="Error: %s" %error_text)

            return False

        if not self.api_key_file_path:
            error_text = "You must provide the path to your API key."
            self.error_label.configure(text="Error: %s" %error_text)

            return False

        if not self.agree_checkbox.instate(['selected']):
            error_text = "You must agree to the terms and conditions."
            self.error_label.configure(text="Error: %s" %error_text)

            return False

        self.error_label.configure(text="Settings are valid, continuing...",fg="black")
        self.error_label.update()
        return True

    def begin_install(self):
        # Set default values here, might make these alterable through "advanced settings" later
        backup_time = 23
        keepalive_freq = 300

        print("Nonrecursive %s" %self.backup_paths)
        print("Recursive %s" %self.recursive_backup_paths)

        self.main(
            self.device_name,
            self.agree_checkbox.instate(['selected']),
            backup_time,
            keepalive_freq,
            self.backup_paths,
            self.recursive_backup_paths,
            self.api_key_file_path
        )

    def update_stdout(self, msg):
        self.stdout_msgs.append(msg)
        self.stdout_label.configure(text="\n".join(self.stdout_msgs))
        self.stdout_label.update()

    def clear_stdout_and_display_error(self, msg):
        self.stdout_msgs.clear()
        self.stdout_label.configure(text="")

        self.error_label.configure(text=msg, fg="red")
        self.error_label.update()

    def log_and_update_stdout(self, msg):
        logging.log(logging.INFO, msg)
        self.update_stdout(msg)

        sleep(1)

    def log_and_update_stderr(self, msg):
        logging.log(logging.ERROR, msg)
        self.clear_stdout_and_display_error(msg)

        sleep(1)

    def main(self, device_type, send_logs, backup_time, keepalive_freq, backup_paths, backup_paths_recursive, api_key_file_path):
        initialize_logging()
        self.log_and_update_stdout("Beginning install of Stormcloud v%s" % STORMCLOUD_VERSION)

        api_key = read_api_key_file(api_key_file_path)

        ret, _ = conduct_connectivity_test(api_key, SERVER_NAME, SERVER_PORT)
        if ret != 0:
            self.log_and_update_stderr("Install failed (unable to conduct connectivity test with server). Return code: %d.\nPlease verify that you are connected to the internet.\nIf problems continue, please contact our customer support team." % ret)
            return
        
        self.log_and_update_stdout("Successfully conducted connectivity test with server.")
        return
        
        logging.log(logging.INFO, "Conducting initial device survey...")

        survey_data = conduct_device_initial_survey(api_key,device_type)

        logging.log(logging.INFO, "Device survey complete.")
        self.log_and_update_stdout("Sending device registration request to server...")

        ret, response_data = tls_send_json_data(survey_data, "register_new_device-response", SERVER_NAME, SERVER_PORT)
        if ret != 0:
            self.log_and_update_stderr("Install failed (unable to register device with server). Return code: %d" % ret)
            return

        self.log_and_update_stdout("Device successfully registered.")

        secret_key = response_data['secret_key']
        logging.log(logging.INFO, "Received device encryption key.")

        agent_id = response_data['agent_id']
        logging.log(logging.INFO, "Received agent ID.")

        logging.log(logging.INFO, "Configuring backup process and writing settings file.")
        ret = configure_settings(
            send_logs, backup_time,
            keepalive_freq, backup_paths,
            backup_paths_recursive,
            secret_key, agent_id,
            api_key
        )

        self.log_and_update_stdout("Ready to launch stormcloud!")

if __name__ == '__main__':
    window = tk.Tk()
    app = MainApplication(window)
    window.title("Stormcloud Installer")
    window.geometry("800x600")
    window.config(background="white")

    # TODO: try to figure out how to center window on screen
    
    def on_closing():
        if messagebox.askokcancel("Quit", "Are you sure you want to exit?"):
            window.destroy()

    window.protocol("WM_DELETE_WINDOW", on_closing)
    window.mainloop()