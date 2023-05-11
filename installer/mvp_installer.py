# Register device request
import socket
import sys
import json
import platform
import requests
import psutil
import netifaces
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QLabel, QPushButton, QProgressBar, QWizard, QWizardPage, QLineEdit, QTextEdit, QMessageBox, QFormLayout, QCheckBox, QFileDialog
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QCheckBox, QFileDialog, QScrollArea, QWidget, QGridLayout


def download_to_folder(url, folder, file_name):
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

class Installer(QWizard):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Stormcloud Installer")
        self.setFixedSize(640, 480)

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

    def validatePage(self):
        api_key = self.api_key_edit.text()
        if self.validate_api_key(api_key):
            self.wizard().api_key = api_key
            return True
        else:
            QMessageBox.warning(self, "Invalid API Key", "The entered API key is invalid or could not be verified. Please try again.")
            return False

    def validate_api_key(self, api_key):
        # Replace this URL with your actual API URL for validation
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
        self.system_info = self.get_system_info()

        layout = QFormLayout()
        for key, value in self.system_info.items():
            layout.addRow(QLabel(key), self.createReadOnlyText(str(value)))
        self.setLayout(layout)

    def initializePage(self):
        self.system_info = self.get_system_info()
        self.system_info_text.setPlainText(json.dumps(self.system_info, indent=2))

    def get_system_info(self):
        system_info = {
            "hostname": socket.gethostname(),
            "ip_address": self.get_ipv4_address_associated_with_default_gateway(),
            "available_ram": str(round(psutil.virtual_memory().available / 1073741824, 1)) + " GB",
            "total_ram": str(round(psutil.virtual_memory().total / 1073741824, 1)) + " GB",
            "operating_system": platform.platform(),
            "device_name": "foo"
            # Add any other diagnostic information here
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
        self.system_info["api_key"] = api_key
        self.system_info["request_type"] = "register_new_device"
        self.system_info["device_status"] = 1
        self.system_info["device_type"] = "bar"
        result = self.register_new_device(self.system_info)
        if result:
            return True
        else:
            QMessageBox.warning(self, "Error", "Failed to register the new device. Please try again.")
            return False

    def register_new_device(self, data):
        url = "https://www2.darkage.io:8443/api/register-new-device"
        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                return True
            else:
                return False
        except:
            return False
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

SERVER_NAME="www2.darkage.io"
SERVER_PORT=8443
STORMCLOUD_VERSION="1.0.0"

stormcloud_client_url = "https://%s/sc-dist/windows-x86_64-stormcloud-client-%s.exe" % (SERVER_NAME, STORMCLOUD_VERSION)

class BackupPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Backup and Installation Settings")
        self.backup_folders = []
        self.install_directory = ''

        layout = QVBoxLayout()
        self.backup_layout = QVBoxLayout()
        self.backup_widget = QWidget()
        self.backup_widget.setLayout(self.backup_layout)
        self.backup_scroll = QScrollArea()
        self.backup_scroll.setWidgetResizable(True)
        self.backup_scroll.setWidget(self.backup_widget)
        
        self.backup_button = QPushButton("Add Folder to Backup")
        self.backup_button.clicked.connect(self.add_backup_folder)
        self.install_label = QLabel("No installation directory selected")
        self.install_button = QPushButton("Select Installation Directory")
        self.install_button.clicked.connect(self.select_install_directory)

        layout.addWidget(QLabel("Backup folders:"))
        layout.addWidget(self.backup_scroll)
        layout.addWidget(self.backup_button)
        layout.addWidget(self.install_label)
        layout.addWidget(self.install_button)
        self.setLayout(layout)

    def add_backup_folder(self):
        folder = str(QFileDialog.getExistingDirectory(self, "Select Directory"))
        if folder:
            checkbox = QCheckBox(f"{folder} (include subfolders)")
            self.backup_layout.addWidget(checkbox)
            self.backup_folders.append(folder)

    def select_install_directory(self):
        directory = str(QFileDialog.getExistingDirectory(self, "Select Installation Directory"))
        if directory:
            self.install_directory = directory
            self.install_label.setText(f"Installation directory: {self.install_directory}")

    def validatePage(self):
        if not self.install_directory:
            QMessageBox.warning(self, "No Installation Directory", "Please select an installation directory.")
            return False
        return True

    def nextId(self):
        return self.wizard().pageIds()[self.wizard().currentPageIndex() + 1]

class InstallPage(QWizardPage):
    # TODO: Write code to do stormcloud installer stuff
    
    def __init__(self):
        super().__init__()

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
        if not target_folder.endswith('\\'):
            target_folder += "\\"
        return download_to_folder(WINDOWS_OS_SC_CLIENT_URL, target_folder, "stormcloud.exe")

class FinishPage(QWizardPage):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout()
        label = QLabel("Installation completed! Click 'Finish' to close the installer.")
        layout.addWidget(label)
        self.setLayout(layout)

if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = Installer()
    window.show()

    sys.exit(app.exec_())