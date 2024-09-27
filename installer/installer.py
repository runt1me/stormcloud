import json
import logging
import netifaces   # pip install netifaces
import os
import platform
import psutil      # pip install psutil
import requests    # pip install requests
import socket
import subprocess
import sys
import winreg
import winshell    # pip install winshell
import yaml        # pip install pyyaml

from pathlib import Path
from requests.exceptions import SSLError
from win32com.client import Dispatch    # pip install pywin32

# pip install pyqt5
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QLabel, QPushButton, QProgressBar, QMainWindow
from PyQt5.QtWidgets import QWizard, QWizardPage, QLineEdit, QTextEdit, QMessageBox, QFormLayout
from PyQt5.QtWidgets import QCheckBox, QFileDialog, QScrollArea, QWidget, QHBoxLayout, QGridLayout
from PyQt5.QtCore import Qt

def setup_logging():
    log_path = os.path.join(os.getenv('TEMP'), 'stormcloud_install.log')
    logging.basicConfig(filename=log_path, level=logging.INFO, 
                        format='%(asctime)s - %(levelname)s - %(message)s')

class Installer(QWizard):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stormcloud Installer")
        self.setFixedSize(640, 480)

        self.system_info = None
        self.api_key = None
        self.target_folder = None
        self.install_directory = None
        self.backup_paths = None
        self.backup_paths_recursive = None
        self.existing_installation = None
        self.corrupted_installation = False

        self.addPage(WelcomePage())
        self.addPage(ExistingInstallationPage())
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

    def check_existing_installation(self):
        appdata_path = os.getenv('APPDATA')
        stable_settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')

        if not os.path.exists(stable_settings_path):
            return None

        with open(stable_settings_path, 'r') as f:
            settings = json.load(f)

        if 'install_path' not in settings or not os.path.exists(settings['install_path']):
            self.corrupted_installation = True
            return settings

        install_path = settings['install_path']
        settings_cfg_path = os.path.join(install_path, 'settings.cfg')
        stormcloud_exe_path = os.path.join(install_path, 'stormcloud.exe')

        if not os.path.exists(settings_cfg_path) or not os.path.exists(stormcloud_exe_path):
            self.corrupted_installation = True
            return settings

        with open(settings_cfg_path, 'r') as f:
            settings_cfg = yaml.safe_load(f)

        required_params = ['AGENT_ID', 'API_KEY', 'BACKUP_PATHS', 'BACKUP_TIME', 'KEEPALIVE_FREQ', 'RECURSIVE_BACKUP_PATHS', 'SECRET_KEY', 'SEND_LOGS']
        for param in required_params:
            if param not in settings_cfg:
                self.corrupted_installation = True
                break

        return settings

    def repair_installation(self):
        # Implementation of repair logic goes here
        # For now, we'll just delete corrupted files
        if self.existing_installation:
            install_path = self.existing_installation['install_path']
            settings_cfg_path = os.path.join(install_path, 'settings.cfg')
            stormcloud_exe_path = os.path.join(install_path, 'stormcloud.exe')

            if os.path.exists(settings_cfg_path):
                os.remove(settings_cfg_path)
            if os.path.exists(stormcloud_exe_path):
                os.remove(stormcloud_exe_path)

        self.corrupted_installation = False

    def uninstall_existing_version(self):
        # Implementation of uninstallation logic goes here
        # For now, we'll just delete the installation directory
        if self.existing_installation:
            install_path = self.existing_installation['install_path']
            if os.path.exists(install_path):
                shutil.rmtree(install_path)

        # Also remove the stable_settings.cfg file
        appdata_path = os.getenv('APPDATA')
        stable_settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')
        if os.path.exists(stable_settings_path):
            os.remove(stable_settings_path)

    def initializePage(self, id):
        super().initializePage(id)
        if id == 0:  # WelcomePage
            self.existing_installation = self.check_existing_installation()

class ExistingInstallationPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Existing Installation")
        
        self.layout = QVBoxLayout()
        self.message_label = QLabel()
        self.layout.addWidget(self.message_label)
        
        self.repair_button = QPushButton("Repair Installation")
        self.repair_button.clicked.connect(self.repair_installation)
        self.layout.addWidget(self.repair_button)
        
        self.reinstall_button = QPushButton("Reinstall from Scratch")
        self.reinstall_button.clicked.connect(self.reinstall_from_scratch)
        self.layout.addWidget(self.reinstall_button)
        
        self.replace_button = QPushButton("Replace Existing Version")
        self.replace_button.clicked.connect(self.replace_existing_version)
        self.layout.addWidget(self.replace_button)
        
        self.setLayout(self.layout)

    def initializePage(self):
        wizard = self.wizard()
        if wizard.existing_installation is None:
            self.message_label.setText("No existing installation detected.")
            self.repair_button.hide()
            self.reinstall_button.hide()
            self.replace_button.hide()
        elif wizard.corrupted_installation:
            self.message_label.setText("Corrupted installation detected. Please choose an option:")
            self.repair_button.show()
            self.reinstall_button.show()
            self.replace_button.hide()
        else:
            self.message_label.setText("Existing installation detected. Do you want to replace it?")
            self.repair_button.hide()
            self.reinstall_button.hide()
            self.replace_button.show()

    def repair_installation(self):
        self.wizard().repair_installation()
        self.wizard().next()

    def reinstall_from_scratch(self):
        self.wizard().uninstall_existing_version()
        self.wizard().next()

    def replace_existing_version(self):
        self.wizard().uninstall_existing_version()
        self.wizard().next()

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
        self.device_name_edit = QLineEdit()  # Add QLineEdit for device name
        self.device_name_edit.setPlaceholderText("Enter device name")  # Optional placeholder text
        layout.addRow("Device Name:", self.device_name_edit)  # Add QLineEdit to the form
        self.setLayout(layout)

    def initializePage(self):
        if not self.wizard().system_info:
            self.wizard().system_info = self.get_system_info()

        # Clear and repopulate the layout every time the page is shown
        self.layout().removeRow(1)  # Update the index to remove the correct row
        for key, value in self.wizard().system_info.items():
            if key != "device_name":  # Skip the device name as it's already in QLineEdit
                self.layout().addRow(QLabel(key), self.createReadOnlyText(str(value)))

    def get_system_info(self):
        BYTES_IN_A_GB = 1073741824
        system_info = {
            "hostname": socket.gethostname(),
            "ip_address": self.get_ipv4_address_associated_with_default_gateway(),
            "available_ram": str(round(psutil.virtual_memory().available / BYTES_IN_A_GB, 1)) + " GB",
            "total_ram": str(round(psutil.virtual_memory().total / BYTES_IN_A_GB, 1)) + " GB",
            "operating_system": platform.platform(),
            "device_name": ""  # Initialize as empty string
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
        self.wizard().system_info["device_type"] = "Windows"
        self.wizard().system_info["device_name"] = self.device_name_edit.text()

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

        self.SERVER_NAME = "www2.darkage.io"
        self.SERVER_PORT_API = 8443
        self.SERVER_PORT_DOWNLOAD = 443
        self.STORMCLOUD_VERSION = "1.0.0"

        self.stormcloud_client_url = "https://%s:%s/sc-dist/windows-x86_64-stormcloud-client-%s.exe" % (
            self.SERVER_NAME,
            self.SERVER_PORT_DOWNLOAD,
            self.STORMCLOUD_VERSION
        )
        self.register_new_device_url = "https://%s:%s/api/register-new-device" % (
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
        if self.wizard().corrupted_installation:
            self.repair_installation()

        if self.register_application():
            self.progress.setValue(90)
            logging.info("Successfully registered application with Windows")
        else:
            QMessageBox.warning(self, "Warning", "Failed to register application with Windows. Some features may not work correctly.")
            logging.error("Failed to register application with Windows")

        
        def get_result(result, result_type):
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

        folders = [
            {"path": folder, "recursive": 0} for folder in self.wizard().backup_paths
        ] + [
            {"path": folder, "recursive": 1} for folder in self.wizard().backup_paths_recursive
        ]

        if not self.register_initial_backup_folders(self.wizard().api_key, register_result['agent_id'], folders):
            QMessageBox.warning(self, "Error", "Failed to register backup folders. Please try again.")
            return

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

        # Create stable_settings.cfg
        if not self.create_stable_settings():
            QMessageBox.warning(self, "Error", "Failed to create stable settings file. Please try again.")

        self.register_application()
        
        self.progress.setValue(100)

    def repair_installation(self):
        # Delete corrupted files before creating new ones
        if os.path.exists(self.wizard().install_directory):
            for file in os.listdir(self.wizard().install_directory):
                file_path = os.path.join(self.wizard().install_directory, file)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    print(f"Failed to delete {file_path}. Reason: {e}")

    def register_application(self):
        try:
            # Ensure the install directory ends with 'Stormcloud'
            # if not self.wizard().install_directory.endswith('Stormcloud'):
            #     self.wizard().install_directory = os.path.join(self.wizard().install_directory, 'Stormcloud')

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Stormcloud"
            try:
                uninstall_key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            except WindowsError as create_error:
                logging.error(f"Failed to create registry key: {str(create_error)}")
                return False

            try:
                winreg.SetValueEx(uninstall_key, "DisplayName", 0, winreg.REG_SZ, "Stormcloud Backup")
                winreg.SetValueEx(uninstall_key, "UninstallString", 0, winreg.REG_SZ, os.path.join(self.wizard().install_directory, "uninstall.exe"))
                winreg.SetValueEx(uninstall_key, "DisplayVersion", 0, winreg.REG_SZ, self.STORMCLOUD_VERSION)
                winreg.SetValueEx(uninstall_key, "Publisher", 0, winreg.REG_SZ, "Your Company Name")
                winreg.SetValueEx(uninstall_key, "DisplayIcon", 0, winreg.REG_SZ, os.path.join(self.wizard().install_directory, "stormcloud.exe"))
                winreg.SetValueEx(uninstall_key, "InstallLocation", 0, winreg.REG_SZ, self.wizard().install_directory)
            except WindowsError as set_error:
                logging.error(f"Failed to set registry values: {str(set_error)}")
                return False
            finally:
                winreg.CloseKey(uninstall_key)

            logging.info("Successfully registered application in Windows registry")
            return True
        except Exception as e:
            logging.error(f"Unexpected error in register_application: {str(e)}")
            return False
    
    def create_stable_settings(self):
        try:
            appdata_path = os.getenv('APPDATA')
            stormcloud_folder = os.path.join(appdata_path, 'Stormcloud')
            os.makedirs(stormcloud_folder, exist_ok=True)

            stable_settings_path = os.path.join(stormcloud_folder, 'stable_settings.cfg')
            
            settings = {
                'install_path': self.wizard().install_directory
            }

            with open(stable_settings_path, 'w') as f:
                json.dump(settings, f, indent=4)

            return True
        except Exception as e:
            logging.error(f"Failed to create stable settings file: {e}")
            return False
    
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
            'BACKUP_PATHS': backup_paths if backup_paths else [],
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

    def download_and_install_uninstaller(self):
        # Download uninstaller
        uninstaller_url = "https://%s:%s/sc-dist/windows-x86_64-stormcloud-uninstaller.exe" % (
            self.SERVER_NAME,
            self.SERVER_PORT_DOWNLOAD
        )
        uninstaller_path = os.path.join(self.wizard().install_directory, "uninstall.exe")
        
        download_result, _ = self.download_to_folder(uninstaller_url, self.wizard().install_directory, "uninstall.exe")
        if not download_result:
            logging.error("Failed to download uninstaller")
            return False

        return True

    def configure_persistence(self, os_info, sc_client_installed_path):
        try:
            sc_client_installed_path_obj = Path(sc_client_installed_path)
            
            # Create Stormcloud folder in Start Menu
            start_menu_programs = os.path.join(os.environ['APPDATA'], 'Microsoft', 'Windows', 'Start Menu', 'Programs')
            stormcloud_folder = os.path.join(start_menu_programs, 'Stormcloud')
            os.makedirs(stormcloud_folder, exist_ok=True)

            shortcut_path = os.path.join(stormcloud_folder, 'Stormcloud Backup Engine.lnk')
            target_path = str(sc_client_installed_path_obj)
            working_dir = str(sc_client_installed_path_obj.parent)

            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.Targetpath = target_path
            shortcut.WorkingDirectory = working_dir
            shortcut.save()

            # Add to Windows startup using registry
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
                winreg.SetValueEx(key, "Stormcloud Backup Engine", 0, winreg.REG_SZ, target_path)
                winreg.CloseKey(key)
            except WindowsError as e:
                logging.error(f"Failed to add Stormcloud to startup: {str(e)}")
                return False

            logging.info(f"Successfully created shortcut and added to startup: {shortcut_path}")
            return True
        except Exception as e:
            logging.error(f"Failed to configure persistence: {str(e)}")
            return False

    def register_initial_backup_folders(self, api_key, agent_id, folders):
        url = "https://apps.darkage.io/darkage/api/register_backup_folders.cfm"
        headers = {"Content-Type": "application/json"}
        data = {
            "api_key": api_key,
            "agent_id": agent_id,
            "folders": folders
        }

        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                result = response.json()
                if result.get('SUCCESS'):
                    print("Folders registered successfully.")
                    return True
                else:
                    print(f"Error: {result.get('MESSAGE')}")
                    return False
            else:
                print(f"Failed to register folders. Status code: {response.status_code}")
                return False
        except Exception as e:
            print(f"Exception occurred: {e}")
            return False

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