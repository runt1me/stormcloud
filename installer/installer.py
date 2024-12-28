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

        self.addPage(WelcomePage())
        self.addPage(ExistingInstallationPage())
        self.addPage(APIKeyPage())
        self.addPage(SystemInfoPage())
        self.addPage(BackupPage())
        self.addPage(InstallPage())
        self.addPage(FinishPage())

    def check_existing_installation(self):
        appdata_path = os.getenv('APPDATA')
        stable_settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')

        if not os.path.exists(stable_settings_path):
            return None

        with open(stable_settings_path, 'r') as f:
            settings = json.load(f)

        return settings

    def stop_stormcloud_processes(self):
        """Stop all running stormcloud processes"""
        try:
            # Find all stormcloud processes
            stormcloud_processes = [proc for proc in psutil.process_iter(['name', 'pid'])
                                  if proc.info['name'] == 'stormcloud.exe']
            
            if not stormcloud_processes:
                logging.info('No stormcloud processes found to stop')
                return True
                
            # Terminate all processes
            for proc in stormcloud_processes:
                try:
                    logging.info(f'Attempting to terminate stormcloud process {proc.info["pid"]}')
                    proc.terminate()
                    proc.wait(timeout=10)
                    if proc.is_running():
                        logging.info(f'Process {proc.info["pid"]} still running after terminate, attempting kill')
                        proc.kill()
                except psutil.NoSuchProcess:
                    logging.info(f'Process {proc.info["pid"]} already terminated')
                except Exception as e:
                    logging.error(f'Error terminating process {proc.info["pid"]}: {e}')
            
            # Double check all processes are stopped
            remaining_processes = [proc for proc in psutil.process_iter(['name'])
                                 if proc.info['name'] == 'stormcloud.exe']
            if remaining_processes:
                logging.warning(f'Found {len(remaining_processes)} remaining stormcloud processes')
                for proc in remaining_processes:
                    try:
                        proc.kill()
                    except:
                        pass
            
            logging.info('All stormcloud processes stopped successfully')
            return True
                    
        except Exception as e:
            logging.error(f'Failed to stop stormcloud processes: {e}')
            return False

    def uninstall_existing_version(self):
        # Successfully tested this version:
        # !python C:/Users/Tyler/Documents/Dark_Age/uninstaller.py

        # First stop any running stormcloud processes
        if not self.stop_stormcloud_processes():
            logging.error("Failed to stop running stormcloud processes")
            return False

        # TODO: Test code below once uninstall.exe compiled
        if not self.existing_installation:
            logging.error("No existing installation found to uninstall.")
            return False

        install_path = self.existing_installation.get('install_path')
        if not install_path:
            logging.error("Invalid installation path in existing installation settings.")
            return False

        uninstaller_path = os.path.join(install_path, "uninstall.exe")
        if not os.path.exists(uninstaller_path):
            logging.error(f"Uninstaller not found at {uninstaller_path}")
            return False

        try:
            # Run the uninstaller and wait for it to complete
            subprocess.run([uninstaller_path], check=True)
            logging.info("Uninstallation completed successfully.")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Uninstallation failed with error code {e.returncode}")
            return False
        except Exception as e:
            logging.error(f"An error occurred during uninstallation: {str(e)}")
            return False

    def initializePage(self, id):
        super().initializePage(id)
        if id == 0:  # WelcomePage
            self.existing_installation = self.check_existing_installation()

    def nextId(self):
        current_id = self.currentId()
        if current_id == 0:  # WelcomePage
            return 1 if self.existing_installation else 2  # Skip ExistingInstallationPage if no existing installation
        return super().nextId()

class ExistingInstallationPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Existing Installation")
        
        self.layout = QVBoxLayout()
        self.message_label = QLabel()
        self.layout.addWidget(self.message_label)
        
        self.uninstall_button = QPushButton("Uninstall and Reinstall")
        self.uninstall_button.clicked.connect(self.uninstall_and_reinstall)
        self.layout.addWidget(self.uninstall_button)
        
        self.cancel_button = QPushButton("Cancel Installation")
        self.cancel_button.clicked.connect(self.cancel_installation)
        self.layout.addWidget(self.cancel_button)
        
        self.setLayout(self.layout)

    def initializePage(self):
        wizard = self.wizard()
        if wizard.existing_installation:
            self.message_label.setText("Existing installation detected. Please choose an option:")
            self.uninstall_button.show()
            self.cancel_button.show()
        else:
            self.message_label.setText("No existing installation detected.")
            self.uninstall_button.hide()
            self.cancel_button.hide()
            QTimer.singleShot(0, self.wizard().next)  # Automatically move to the next page

    def uninstall_and_reinstall(self):
        self.wizard().uninstall_existing_version()
        self.wizard().next()

    def cancel_installation(self):
        self.wizard().reject()

    def initializePage(self):
        wizard = self.wizard()
        if wizard.existing_installation is None:
            self.wizard().next()
        else:
            self.message_label.setText("Existing installation detected. Please choose an option:")
            self.uninstall_button.show()
            self.cancel_button.show()

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
        
        # Set margins and spacing for consistent alignment
        self.layout = QFormLayout()
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.setSpacing(10)
        self.layout.setLabelAlignment(Qt.AlignLeft)  # Align labels to the left
        
        # Create device name label with same formatting as system info labels
        device_name_label = QLabel("Device Name:")
        device_name_label.setMinimumWidth(120)  # Set minimum width for label alignment
        
        self.device_name_edit = QLineEdit()
        self.device_name_edit.setPlaceholderText("Enter device name")
        self.device_name_edit.setMinimumWidth(300)
        
        # Add device name row with explicit label widget
        self.layout.addRow(device_name_label, self.device_name_edit)
        
        # Create a container for system info rows
        self.info_container = QWidget()
        self.info_layout = QFormLayout(self.info_container)
        self.info_layout.setSpacing(10)
        self.info_layout.setContentsMargins(0, 0, 0, 0)
        self.info_layout.setLabelAlignment(Qt.AlignLeft)  # Match label alignment
        self.layout.addRow(self.info_container)
        
        self.setLayout(self.layout)

    def initializePage(self):
        if not self.wizard().system_info:
            self.wizard().system_info = self.get_system_info()

        # Clear existing system info rows
        while self.info_layout.rowCount() > 0:
            self.info_layout.removeRow(0)

        # Add new system info rows with consistent label width
        for key, value in self.wizard().system_info.items():
            if key != "device_name":
                label = QLabel(key)
                label.setMinimumWidth(120)  # Match the device name label width
                self.info_layout.addRow(label, self.createReadOnlyText(str(value)))

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
        if not self.passes_sanitize(self.wizard().system_info["device_name"]):
            QMessageBox.warning(self, "Bad Device Name", "Your Device Name contains bad characters.")
            return False
        return True
        
    def passes_sanitize(self, input_string):
      # Function for validating input to the database.
      # 
      SANITIZE_LIST = ["'", '"', ";", "\\", "--", "*"]
      for expr in SANITIZE_LIST:
        if expr in input_string:
          return False
          
      return True
        
    def createReadOnlyText(self, text):
        readOnlyText = QTextEdit()
        readOnlyText.setPlainText(text)
        readOnlyText.setReadOnly(True)
        readOnlyText.setFixedHeight(25)
        readOnlyText.setMinimumWidth(300)
        readOnlyText.setStyleSheet("""
            QTextEdit {
                background-color: #F0F0F0;
                color: #333;
                border: none;
                padding: 2px;
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

    def configure_yaml_settings(self, send_logs, backup_time, keepalive_freq, backup_paths, backup_paths_recursive, agent_id, api_key, target_folder):
        backup_time        = int(backup_time)
        keepalive_freq     = int(keepalive_freq)

        settings_file_path = target_folder + "settings.cfg"
        os.makedirs(os.path.dirname(settings_file_path), exist_ok=True)

        settings_dict = {
            'SEND_LOGS': int(send_logs),
            'BACKUP_TIME': backup_time,
            'KEEPALIVE_FREQ': keepalive_freq,
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

    sys.exit(app.exec_()) # this line starts the application's event loop. It keeps the application running, waiting for events (like button clicks, key presses, etc.) until the application is closed. It also closes it after it wants to close. 