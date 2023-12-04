import json
import logging
import netifaces   # pip install netifaces
import os
import platform
import psutil      # pip install psutil
import requests    # pip install requests
import socket
import sys
import winshell    # pip install winshell
import subprocess
import yaml        # pip install pyyaml
from win32com.client import Dispatch    # pip install pywin32

# pip install pyqt5
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QLabel, QPushButton, QProgressBar, QMainWindow
from PyQt5.QtWidgets import QWizard, QWizardPage, QLineEdit, QTextEdit, QMessageBox, QFormLayout
from PyQt5.QtWidgets import QCheckBox, QFileDialog, QScrollArea, QWidget, QHBoxLayout, QGridLayout
from PyQt5.QtCore import Qt
from requests.exceptions import SSLError

from pathlib import Path

class Installer(QWizard):
    def __init__(self):
        super().__init__()
        # TODO: logging - best practices for how to incorporate this?

        self.setWindowTitle("Stormcloud Installer")
        self.setFixedSize(640, 480)

        # Scoping these variables to the installer so that I can use them at another time
        self.system_info            = None
        self.api_key                = None
        self.target_folder          = None
        self.install_directory      = None
        self.backup_paths           = None
        self.backup_paths_recursive = None

        self.addPage(WelcomePage())
        self.addPage(APIKeyPage())
        self.addPage(SystemInfoPage())
        self.addPage(BackupPage())
        self.addPage(InstallPage())
        self.addPage(FinishPage())

    def initialize_logging():
        logging.basicConfig(
            filename='install.log',
            filemode='a',
            format='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=logging.DEBUG
        )


class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        label = QLabel("Welcome to the Stormcloud Installer. Click 'Next' to begin.")
        layout.addWidget(label)
        self.setLayout(layout)

class APIKeyPage(QWizardPage):    
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        label = QLabel("Enter your API key:")
        self.api_key_edit = QLineEdit()
        layout.addWidget(label)
        layout.addWidget(self.api_key_edit)
        self.setLayout(layout)

    def initializePage(self):
        pass

    def validatePage(self):
        if self.validate_api_key(self.api_key_edit.text()):
            self.wizard().api_key = self.api_key_edit.text()
            return True
        else:
            QMessageBox.warning(self, "Invalid API Key", "The entered API key is invalid or could not be verified. Please try again.")
            return False

    def validate_api_key(self, api_key):
        url = "https://www2.darkage.io:8443/api/validate-api-key"
        headers = {"Content-Type": "application/json"}
        data = {"api_key": api_key}        
        
        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                QMessageBox.information(self, "API Key Validated", "The API key has been successfully validated!")
                return True
            else:
                return False

        except Exception as e:
            print(e)
            return False

class SystemInfoPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("System Information")
        
        layout = QFormLayout()
        self.setLayout(layout)

    def initializePage(self):
        self.wizard().system_info = self.get_system_info()
        
        # Clear and repopulate the layout every time the page is shown
        self.layout().removeRow(0)
        for key, value in self.wizard().system_info.items():
            self.layout().addRow(QLabel(key), self.createReadOnlyText(str(value)))

    def get_system_info(self):
        BYTES_IN_A_GB = 1073741824
        system_info = {
            "hostname": socket.gethostname(),
            "ip_address": self.get_ipv4_address_associated_with_default_gateway(),
            "available_ram": str(round(psutil.virtual_memory().available / BYTES_IN_A_GB, 1)) + " GB",
            "total_ram": str(round(psutil.virtual_memory().total / BYTES_IN_A_GB, 1)) + " GB",
            "operating_system": platform.platform(),
            "device_name": "foo"
        }
        return system_info

    def get_ipv4_address_associated_with_default_gateway(self):
        default_gateway = netifaces.gateways()['default'][netifaces.AF_INET]
        default_gateway_interface = default_gateway[1]
        ipv4_addresses = [
            addr['addr']
            for addr in netifaces.ifaddresses(default_gateway_interface)[netifaces.AF_INET]
        ]
        return ipv4_addresses[0] if ipv4_addresses else None

    def validatePage(self):
        self.wizard().system_info["request_type"] = "register_new_device"
        self.wizard().system_info["device_status"] = 1
        self.wizard().system_info["device_type"] = "bar"

        return True

    def createReadOnlyText(self, text):
        readOnlyText = QTextEdit()
        readOnlyText.setPlainText(text)
        readOnlyText.setReadOnly(True)
        readOnlyText.setFixedHeight(25)
        readOnlyText.setStyleSheet("""
            QTextEdit {
                background-color: #F0F0F0;
                color: #333;
                border: none;
            }
        """)
        return readOnlyText

class BackupPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.folder_layouts = []
        
        self.setTitle("Backup and Installation Settings")
        
        self.scrollArea = QScrollArea()
        self.scrollArea.setWidgetResizable(True)

        self.scrollContent = QWidget(self.scrollArea)
        self.scrollLayout = QFormLayout(self.scrollContent)
        self.scrollArea.setWidget(self.scrollContent)

        self.addButton = QPushButton("Add Folder", self)
        self.addButton.clicked.connect(self.addFolder)
        self.addButton.setMaximumWidth(80)
        
        self.install_label = QLineEdit()
        
        self.install_label.setText(os.getenv("HOMEDRIVE") + os.getenv("HOMEPATH") + "\\AppData\\Roaming")
        self.install_label.setReadOnly(True)
        
        self.install_button = QPushButton("Select Installation Directory")
        self.install_button.clicked.connect(self.select_install_directory)
        self.install_button.setMaximumWidth(180)
        
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Select the folders you want to backup:"))
        layout.addWidget(self.scrollArea)
        layout.addWidget(self.addButton)
        layout.addWidget(self.install_label)
        layout.addWidget(self.install_button)
        self.setLayout(layout)

    def initializePage(self):
        self.wizard().install_directory = os.getenv("HOMEDRIVE") + os.getenv("HOMEPATH") + "\\AppData\\Roaming"

    def addFolder(self):
        folder = str(QFileDialog.getExistingDirectory(self, "Select Directory"))
        if folder:
            checkbox = QCheckBox("Include subfolders")
            checkboxLayout = QHBoxLayout()
            checkboxLayout.addSpacing(20)
            checkboxLayout.addWidget(checkbox)

            removeButton = QPushButton("Remove Folder")
            removeButton.setMaximumWidth(120)
            
            path_layout = QHBoxLayout()
            path_layout.addWidget(QLabel(folder))
            path_layout.addWidget(removeButton, alignment=Qt.AlignRight)
            
            path_and_checkbox_layout = QVBoxLayout()
            path_and_checkbox_layout.addLayout(path_layout)
            path_and_checkbox_layout.addLayout(checkboxLayout)

            self.scrollLayout.addWidget(self.createFolderWidget(folder, checkbox))  # Pass checkbox to method

            # self.folder_layouts.append((folder, checkbox, path_and_checkbox_layout, removeButton))  # Store checkbox

            removeButton.clicked.connect(lambda: self.removeFolder(folder, checkbox, path_and_checkbox_layout, removeButton))

    def removeFolder(self, folder, checkbox, widget, button):
        button.clicked.disconnect()
        self.scrollLayout.removeWidget(widget)
        widget.deleteLater()

        self.folder_layouts.remove((folder, checkbox, widget, button))

    def createFolderWidget(self, folder, checkbox):  # Receive checkbox from caller
        checkboxLayout = QHBoxLayout()
        checkboxLayout.addSpacing(20)
        checkboxLayout.addWidget(checkbox)

        removeButton = QPushButton("Remove Folder")
        removeButton.setMaximumWidth(120)

        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel(folder))
        path_layout.addWidget(removeButton, alignment=Qt.AlignRight)

        path_and_checkbox_layout = QVBoxLayout()
        path_and_checkbox_layout.addLayout(path_layout)
        path_and_checkbox_layout.addLayout(checkboxLayout)

        folderWidget = QWidget()
        folderWidget.setLayout(path_and_checkbox_layout)

        self.folder_layouts.append((folder, checkbox, folderWidget, removeButton))  # Store checkbox

        removeButton.clicked.connect(lambda: self.removeFolder(folder, checkbox, folderWidget, removeButton))  # Pass checkbox to method

        return folderWidget
        
    def select_install_directory(self):
        directory = str(QFileDialog.getExistingDirectory(self, "Select Installation Directory"))
        if directory:
            self.wizard().install_directory = directory
            self.install_label.setText(f"{self.wizard().install_directory}")

    def validatePage(self):
        self.wizard().backup_paths = [folder for folder, checkbox, _, _ in self.folder_layouts if not checkbox.isChecked()]
        self.wizard().backup_paths_recursive = [folder for folder, checkbox, _, _ in self.folder_layouts if checkbox.isChecked()]
        
        if not self.wizard().install_directory:
            QMessageBox.warning(self, "No Installation Directory", "Please select an installation directory.")
            return False
        return True

class InstallPage(QWizardPage):
    def __init__(self):
        super().__init__()

        self.SERVER_NAME="www2.darkage.io"
        self.SERVER_PORT_API=8443
        self.SERVER_PORT_DOWNLOAD=443
        self.STORMCLOUD_VERSION="1.0.0"

        self.stormcloud_client_url   = "https://%s:%s/sc-dist/windows-x86_64-stormcloud-client-%s.exe" % (
            self.SERVER_NAME,
            self.SERVER_PORT_DOWNLOAD,
            self.STORMCLOUD_VERSION
        )
        self.register_new_device_url   = "https://%s:%s/api/register-new-device" % (
            self.SERVER_NAME,
            self.SERVER_PORT_API
        )

        layout = QVBoxLayout()
        label = QLabel("Installing Stormcloud...")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(label)
        layout.addWidget(self.progress)
        self.setLayout(layout)

    def initializePage(self):
        # TODO: need to find the right place to call self.install()
        # Need to make the progress bar move appropriately as functions complete
        # Need to figure out how to display text on the screen while bar moves
        # i.e. "registering device", "configuring settings", "downloading stormcloud client", "configuring startup process"
        self.progress.setValue(0)
        self.install()

    def install(self):
        def get_result(result, result_type):
            # Input checks
            valid_result_types = ('register', 'download', 'configure', 'persist')
            if result_type not in valid_result_types:
                QMessageBox.warning(self, "Error", 'Invalid result_type provided. Valid result types include: `{}`'.format("`, `".join(valid_result_types)))
            
            if result:
                return True
            return False
        
        if not self.wizard().install_directory.endswith('\\'):
            self.wizard().install_directory += "\\Stormcloud\\"
        else:
            self.wizard().install_directory += "Stormcloud\\"

        register_result = self.register_new_device()
        if not get_result(register_result, result_type='register'):
            QMessageBox.warning(self, "Error", "Failed to register the new device. Please try again.")

        self.progress.setValue(30)

        download_result, full_exe_path = self.download_to_folder(self.stormcloud_client_url, self.wizard().install_directory, "stormcloud.exe")
        if not get_result(download_result, result_type='download'):
            QMessageBox.warning(self, "Error", "Failed to download stormcloud. Please try again.")

        self.progress.setValue(60)

        configure_result = self.configure_yaml_settings(
            send_logs=1,
            backup_time=22,
            keepalive_freq=300,
            backup_paths=self.wizard().backup_paths,
            backup_paths_recursive=self.wizard().backup_paths_recursive,
            secret_key=register_result['secret_key'],
            agent_id=register_result['agent_id'],
            api_key=self.wizard().system_info['api_key'],
            target_folder=self.wizard().install_directory,
        )
        if not get_result(configure_result, result_type='configure'):
            QMessageBox.warning(self, "Error", "Failed to configure settings. Please try again.")

        self.progress.setValue(70)

        persist_result = self.configure_persistence(self.wizard().system_info['operating_system'], full_exe_path)
        if not get_result(persist_result, result_type='persist'):
            QMessageBox.warning(self, "Error", "Failed to add stormcloud to startup process. Please try again.")

        self.progress.setValue(100)

    def register_new_device(self):
        headers = {"Content-Type": "application/json"}

        post_data = self.wizard().system_info
        post_data['api_key'] = self.wizard().api_key
        print("register_new_device: %s" % post_data)

        try:
            response = requests.post(url=self.register_new_device_url, headers=headers, json=post_data)
            if response.status_code == 200:
                print("Response: %s" % response.json())
                return response.json()
            else:
                return None
        except:
            return None

    def configure_yaml_settings(self, send_logs, backup_time, keepalive_freq, backup_paths, backup_paths_recursive, secret_key, agent_id, api_key, target_folder):
        backup_time        = int(backup_time)
        keepalive_freq     = int(keepalive_freq)

        settings_file_path = target_folder + "settings.cfg"
        os.makedirs(os.path.dirname(settings_file_path), exist_ok=True)

        settings_dict = {
            'SEND_LOGS': int(send_logs),
            'BACKUP_TIME': backup_time,
            'KEEPALIVE_FREQ': keepalive_freq,
            'SECRET_KEY': secret_key,
            'AGENT_ID': agent_id,
            # API key my husband is so smart
            'API_KEY': api_key,
            'BACKUP_PATHS': backup_paths,
            'RECURSIVE_BACKUP_PATHS': backup_paths_recursive if backup_paths_recursive else []
        }

        with open(settings_file_path, "w") as settings_file:
            yaml.dump(settings_dict, settings_file)

        return True

    def download_to_folder(self, url, folder, file_name):
        try:
            response = requests.get(url)
        except SSLError as e:
            
            logging.log(logging.ERROR, "Caught SSL Error when trying to download from %s: %s" % (url,e))
        except Exception as e:
            logging.log(logging.ERROR, "Caught exception when trying to download from %s: %s" % (url,e))
            
        if response:
            try:
                full_path = folder + file_name
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                with open(full_path,'wb') as f:
                    for chunk in response.iter_content():
                        f.write(chunk)
                
                # Pass case
                return (1, full_path)
            except Exception as e:
                logging.log(logging.ERROR, "Caught exception when trying to write stormcloud to file: %s. Error: %s" % (full_path,e))

        # Fail case
        return (0, None)

    def configure_persistence(self, os_info, sc_client_installed_path):
        # TODO: need exception handling for if there is already a link there, this will break
        # Ideally need to check for artifacts to determine if its already installed
        sc_client_installed_path_obj = Path(sc_client_installed_path)
        try:
            shortcut_path = os.getenv('APPDATA') + "\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Stormcloud Backup Engine.lnk"
            target_path   = str(sc_client_installed_path_obj)
            working_dir   = str(sc_client_installed_path_obj.parent)

            shell = Dispatch('Wscript.Shell')
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.Targetpath = target_path
            shortcut.WorkingDirectory = working_dir
            shortcut.save()

            return (1, shortcut_path)
        except Exception as e:
            logging.log(logging.ERROR, "Failed to create shortcut: %s" % e)
            return (0, None)

class FinishPage(QWizardPage):
    def __init__(self):
        super().__init__()

        # TODO: have a checkbox to launch the installer
        self.checkbox = QCheckBox("Run Stormcloud")

        layout = QVBoxLayout()
        label = QLabel("Installation completed! Click 'Finish' to close the installer.")
        layout.addWidget(label)
        layout.addWidget(self.checkbox)
        self.setLayout(layout)

    def validatePage(self):
        if self.checkbox.isChecked():
            self.run_stormcloud_client()

        return True

    def run_stormcloud_client(self):
        path_to_exec = self.wizard().install_directory + "\\stormcloud.exe"
        logging.log(logging.INFO, "start %s" %path_to_exec)
        subprocess.Popen('start %s' %path_to_exec, cwd=self.wizard().install_directory, shell=True)

if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = Installer()
    window.show()

    sys.exit(app.exec_())