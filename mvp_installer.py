import json
import logging
import netifaces
import os
import platform
import psutil
import requests
import socket
import sys
import winreg # Used for uninstaller (create_uninstall_registry_key)
import winshell
import subprocess
import yaml
from win32com.client import Dispatch

from PyQt5.QtWidgets import QApplication, QVBoxLayout, QLabel, QPushButton, QProgressBar#, QMainWindow
from PyQt5.QtWidgets import QWizard, QWizardPage, QLineEdit, QTextEdit, QMessageBox, QFormLayout
from PyQt5.QtWidgets import QCheckBox, QFileDialog, QScrollArea, QWidget, QHBoxLayout#, QGridLayout
from PyQt5.QtCore import Qt
from requests.exceptions import SSLError

from pathlib import Path

class Installer(QWizard):
    def __init__(self):
        super().__init__()
        # TODO: logging - best practices for how to incorporate this?

        self.setWindowTitle("Stormcloud Installer")
        self.setFixedSize(640, 480)

        # Scoping these variables to the installer so that I can use them later
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
        self.label = QLabel("Initializing...")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.label)
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
        
        # TODO: Write code to fix this dumb assumption
        if not self.wizard().install_directory.endswith('\\Stormcloud'):
            self.wizard().install_directory += "\\Stormcloud\\Stormcloud\\"
        else:
            self.wizard().install_directory += "\\Stormcloud\\"

        self.label.setText("Registering device...")
        register_result = self.register_new_device()
        if not get_result(register_result, result_type='register'):
            QMessageBox.warning(self, "Error", "Failed to register the new device. Please try again.")
        self.progress.setValue(25)

        self.label.setText("Downloading stormcloud client...")
        download_result, full_exe_path = self.download_to_folder(self.stormcloud_client_url, self.wizard().install_directory, "stormcloud.exe")
        
        if not get_result(download_result, result_type='download'):
            QMessageBox.warning(self, "Error", "Failed to download stormcloud. Please try again.")
        self.progress.setValue(50)

        self.label.setText("Configuring settings...")
        configure_result = self.configure_settings(
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
        self.progress.setValue(75)

        self.label.setText("Configuring startup process...")
        persist_result = self.configure_persistence(self.wizard().system_info['operating_system'], full_exe_path)
        if not get_result(persist_result, result_type='persist'):
            QMessageBox.warning(self, "Error", "Failed to add stormcloud to startup process. Please try again.")
        self.progress.setValue(90)
        self.label.setText("Installation complete.")
        
        self.create_uninstall_registry_key('Stormcloud', 'Dark Age Technology Group', self.STORMCLOUD_VERSION, 'C:/Users/Tyler/AppData/Roaming/Stormcloud/Stormcloud', 'C:/Users/Tyler/AppData/Roaming/Stormcloud/Stormcloud/Uninstaller.exe')
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

    def configure_settings(self, send_logs, backup_time, keepalive_freq, backup_paths, backup_paths_recursive, secret_key, agent_id, api_key, target_folder):
        backup_time        = int(backup_time)
        keepalive_freq     = int(keepalive_freq)

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

        # Create a stable location for settings to ensure we can find the application later
        stable_app_location = os.path.dirname(os.getenv('APPDATA') + "\\Stormcloud\\Stormcloud\\")
        os.makedirs(stable_app_location, exist_ok=True)
        with open(stable_app_location + "\\stable_settings.yaml", "w") as stable_settings_file:
            stable_settings = {}
            stable_settings['application_path'] = self.wizard().install_directory
            yaml.dump(stable_settings, stable_settings_file)

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
        sc_client_installed_path_obj = Path(sc_client_installed_path)
        try:
            shortcut_path = os.getenv('APPDATA') + "\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Stormcloud.lnk"
            target_path   = str(sc_client_installed_path_obj)
            working_dir   = str(sc_client_installed_path_obj.parent)
    
            # Debug outputs:
            print(f"Shortcut path: {shortcut_path}")
            print(f"Target path: {target_path}")
            print(f"Working dir: {working_dir}")
    
            shell = Dispatch('Wscript.Shell')
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.Targetpath = target_path
            shortcut.WorkingDirectory = working_dir
            shortcut.save()
    
            return (1, shortcut_path)
        except Exception as e:
            logging.log(logging.ERROR, "Failed to create shortcut: %s" % e)
            return (0, None)

    def create_uninstall_registry_key(self, app_name, company_name, version, install_location, uninstall_string):
        # Open the uninstall registry key.
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                             'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall', 
                             0, winreg.KEY_ALL_ACCESS)
    
        # Create a new key for our application.
        app_key = winreg.CreateKey(key, app_name)
    
        # Set the values that will appear in the Add/Remove Programs entry.
        winreg.SetValueEx(app_key, 'DisplayName', 0, winreg.REG_SZ, app_name)
        winreg.SetValueEx(app_key, 'CompanyName', 0, winreg.REG_SZ, company_name)
        winreg.SetValueEx(app_key, 'Version', 0, winreg.REG_SZ, version)
        winreg.SetValueEx(app_key, 'InstallLocation', 0, winreg.REG_SZ, install_location)
        winreg.SetValueEx(app_key, 'UninstallString', 0, winreg.REG_SZ, uninstall_string)
    
        # Close the keys.
        winreg.CloseKey(app_key)
        winreg.CloseKey(key)

class FinishPage(QWizardPage):
    def __init__(self):
        super().__init__()

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