# Register device request
import json
import logging
import netifaces
import os
import platform
import psutil
import requests
import socket
import sys

from PyQt5.QtWidgets import QApplication, QVBoxLayout, QLabel, QPushButton, QProgressBar#, QMainWindow
from PyQt5.QtWidgets import QWizard, QWizardPage, QLineEdit, QTextEdit, QMessageBox, QFormLayout
from PyQt5.QtWidgets import QCheckBox, QFileDialog, QScrollArea, QWidget, QHBoxLayout#, QGridLayout
from PyQt5.QtCore import Qt
from requests.exceptions import SSLError

class Installer(QWizard):
    def __init__(self):
        super().__init__()
        # TODO: logging

        self.setWindowTitle("Stormcloud Installer")
        self.setFixedSize(640, 480)

        # Scoping these variables to the installer so that I can use them later
        self.system_info   = None
        self.api_key       = None
        self.target_folder = None

        self.addPage(WelcomePage())
        self.addPage(APIKeyPage())
        self.addPage(SystemInfoPage())
        self.addPage(BackupPage())
        self.addPage(InstallPage())
        self.addPage(FinishPage())

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
        print("In APIKey page: %s" % self.wizard())

    def validatePage(self):
        api_key = self.api_key_edit.text()
        if self.validate_api_key(api_key):
            self.wizard().api_key = api_key
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
        print("In SystemInfo page: %s" % self.wizard())
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
        api_key = self.wizard().api_key
        self.wizard().system_info["api_key"] = api_key
        self.wizard().system_info["request_type"] = "register_new_device"
        self.wizard().system_info["device_status"] = 1
        self.wizard().system_info["device_type"] = "bar"

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
        self.install_directory = ''
        
        self.scrollArea = QScrollArea()
        self.scrollArea.setWidgetResizable(True)

        self.scrollContent = QWidget(self.scrollArea)
        self.scrollLayout = QFormLayout(self.scrollContent)
        self.scrollArea.setWidget(self.scrollContent)

        self.addButton = QPushButton("Add Folder", self)
        self.addButton.clicked.connect(self.addFolder)
        self.addButton.setMaximumWidth(80)
        
        self.install_label = QLineEdit()
        self.install_label.setText(r"C:/Program Files")
        self.install_label.setReadOnly(True)
        
        #self.install_label = QLabel("No installation directory selected")
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
            self.scrollLayout.addWidget(self.createFolderWidget(folder))

            self.folder_layouts.append((path_and_checkbox_layout, removeButton))

            # Update the clicked event connection to include the QVBoxLayout
            removeButton.clicked.connect(lambda: self.removeFolder(path_and_checkbox_layout, removeButton))

    def removeFolder(self, widget, button):
        # Disconnect the clicked signal from the remove button
        button.clicked.disconnect()

        # Directly delete the widget from the layout
        self.scrollLayout.removeWidget(widget)
        widget.deleteLater()

        self.folder_layouts.remove((widget, button))

    def createFolderWidget(self, folder):
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

        folderWidget = QWidget()
        folderWidget.setLayout(path_and_checkbox_layout)

        self.folder_layouts.append((folderWidget, removeButton))

        # Update the clicked event connection to include the QVBoxLayout
        removeButton.clicked.connect(lambda: self.removeFolder(folderWidget, removeButton))

        return folderWidget
        
    def select_install_directory(self):
        directory = str(QFileDialog.getExistingDirectory(self, "Select Installation Directory"))
        if directory:
            self.install_directory = directory
            self.install_label.setText(f"{self.install_directory}")

    def validatePage(self):
        if not self.install_directory:
            QMessageBox.warning(self, "No Installation Directory", "Please select an installation directory.")
            return False
        return True

#     def nextId(self):
#         return self.wizard().pageIds()[self.wizard().currentPageIndex() + 1]

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
        self.progress.setValue(0)
        self.install()

    def install(self):
        def get_result(result, result_type):
            # Input checks
            valid_result_types = ('register', 'download', 'configure')
            if result_type not in valid_result_types:
                QMessageBox.warning(self, "Error", 'Invalid result_type provided. Valid result types include: `{}`'.format("`, `".join(valid_result_types)))
            
            if result:
                return True
            elif result_type == 'register':
                return False
            elif result_type == 'download':
                return False
            elif result_type == 'configure':
                return False
        
        register_result = self.register_new_device(self.wizard().system_info)
        if not get_result(register_result, result_type='register'):
            QMessageBox.warning(self, "Error", "Failed to register the new device. Please try again.")
        
        download_result = self.download_to_folder(self.stormcloud_client_url, self.wizard().target_folder, "stormcloud.exe")
        if not get_result(download_result, result_type='download'):
            QMessageBox.warning(self, "Error", "Failed to download stormcloud. Please try again.")
        
        configure_result = self.configure_settings(
            send_logs=1, backup_time=22, keepalive_freq=300,
            backup_paths=self.wizard().system_info['backup_paths'],
            backup_paths_recursive=self.wizard().system_info['backup_paths_recursive'],
            secret_key=register_result['secret_key'],
            agent_id=register_result['agent_id'],
            api_key=self.wizard().system_info['api_key'],
            target_folder=self.wizard().target_folder,
        )
        if not get_result(configure_result, result_type='configure'):
            QMessageBox.warning(self, "Error", "Failed to configure settings. Please try again.")

        # TODO: configure_persistence()

    def register_new_device(self, data):
        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(url=self.register_new_device_url, headers=headers, json=data)
            if response.status_code == 200:
                return response.json
            else:
                return None
        except:
            return None

    def configure_settings(send_logs, backup_time, keepalive_freq, backup_paths, backup_paths_recursive, secret_key, agent_id, api_key, target_folder, os_info):
        backup_time        = int(backup_time)
        keepalive_freq     = int(keepalive_freq)

        if not target_folder.endswith("\\"):
            target_folder += "\\"

        settings_file_path = target_folder + "settings.cfg"
        os.makedirs(os.path.dirname(settings_file_path), exist_ok=True)
        with open(settings_file_path, "w") as settings_file:
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

    def download_to_folder(url, folder, file_name):
        if not folder.endswith('\\'):
            folder += "\\"
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
                return (0, full_path)
            except Exception as e:
                logging.log(logging.ERROR, "Caught exception when trying to write stormcloud to file: %s. Error: %s" % (full_path,e))

        # Fail case
        return (1, None)

class FinishPage(QWizardPage):
    def __init__(self):
        super().__init__()

        # TODO: have a checkbox to launch the installer

        layout = QVBoxLayout()
        label = QLabel("Installation completed! Click 'Finish' to close the installer.")
        layout.addWidget(label)
        self.setLayout(layout)

if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = Installer()
    window.show()

    sys.exit(app.exec_())