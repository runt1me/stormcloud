import os
import json
import psutil
import subprocess
import logging
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QListWidget, QListWidgetItem, QMessageBox, QFileDialog, 
                             QGridLayout, QFormLayout, QSizePolicy, QCheckBox, QComboBox, QFrame)
from PyQt5.QtCore import Qt, QUrl, QPoint
from PyQt5.QtGui import QDesktopServices, QFont, QIcon, QColor, QPalette


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', 
                    filename='stormcloud_app.log', filemode='a')

class StormcloudMessageBox(QMessageBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stormcloud")
        self.setStyleSheet("""
            QMessageBox {
                background-color: #202124;
                color: #e8eaed;
            }
            QMessageBox QLabel {
                color: #e8eaed;
            }
            QPushButton {
                background-color: #333;
                color: #e8eaed;
                border: none;
                padding: 5px 15px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #444;
            }
        """)
        
    @staticmethod
    def information(parent, title, text):
        msg_box = StormcloudMessageBox(parent)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText(text)
        msg_box.setWindowTitle(title)
        msg_box.setStandardButtons(QMessageBox.Ok)
        return msg_box.exec_()

    @staticmethod
    def critical(parent, title, text):
        msg_box = StormcloudMessageBox(parent)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setText(text)
        msg_box.setWindowTitle(title)
        msg_box.setStandardButtons(QMessageBox.Ok)
        return msg_box.exec_()

class StormcloudApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Stormcloud Backup Manager')
        self.setGeometry(100, 100, 800, 600)
        self.init_ui()
        self.load_settings()
        self.update_status()
        self.load_backup_paths()
        self.load_properties()

    def init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Header
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        self.start_button = QPushButton('Start Backup Engine')
        self.start_button.clicked.connect(self.toggle_backup_engine)
        header_layout.addWidget(self.start_button)
        header_layout.addStretch()
        main_layout.addWidget(header_widget)

        # Grid layout for panels
        grid_widget = QWidget()
        self.grid_layout = QGridLayout(grid_widget)
        self.setup_grid_layout()
        main_layout.addWidget(grid_widget)

        self.setStyleSheet(self.get_stylesheet())

    def get_stylesheet(self):
        return """
            QMainWindow {
                background-color: #202124;
            }
            QWidget {
                color: #e8eaed;
                font-family: 'Arial', sans-serif;
            }
            QMenuBar {
                background-color: #333333;
                color: #e8eaed;
            }
            QMenuBar::item {
                background-color: transparent;
            }
            QMenuBar::item:selected {
                background-color: #444444;
            }
            QMainWindow::title {
                background-color: #333333;
                color: #4285F4;
                font-size: 16px;
                font-weight: bold;
                padding-left: 10px;
            }
            QPushButton {
                background-color: #333;
                border: none;
                padding: 5px 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #444;
            }
            QLabel {
                font-size: 14px;
            }
            QListWidget {
                background-color: #333;
                border: none;
                border-radius: 5px;
            }
            #PanelWidget {
                background-color: #333;
                border: 1px solid #666;
                border-radius: 5px;
            }
            #HeaderLabel {
                color: #8ab4f8;
                font-size: 16px;
                font-weight: bold;
                background-color: #171717;
                border: 1px solid #666;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                padding: 5px;
            }
            #ContentWidget {
                background-color: transparent;
                border-bottom-left-radius: 5px;
                border-bottom-right-radius: 5px;
            }
            #WebLink {
                background-color: transparent;
                color: #8ab4f8;
                text-align: left;
            }
            #WebLink:hover {
                text-decoration: underline;
            }
            QComboBox {
                background-color: #333;
                border: 1px solid #666;
                border-radius: 5px;
                padding: 5px;
                min-width: 6em;
            }
            QComboBox:hover {
                border: 1px solid #8ab4f8;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 15px;
                border-left-width: 1px;
                border-left-color: #666;
                border-left-style: solid;
            }
            QComboBox::down-arrow {
                image: url(down_arrow.png);
            }
            QComboBox QAbstractItemView {
                border: 1px solid #666;
                background-color: #333;
                selection-background-color: #444;
            }
            QFrame[frameShape="4"],  /* HLine */
            QFrame[frameShape="5"] {  /* VLine */
                color: #666;
                width: 1px;
                height: 1px;
            }
        """

    def setup_grid_layout(self):
        panels = [
            self.create_configuration_dashboard(),
            self.create_backup_schedule_panel(),
            self.create_web_links_panel(),
            self.create_backed_up_folders_panel()
        ]

        for i, panel in enumerate(panels):
            row = i // 2
            col = i % 2
            self.grid_layout.addWidget(panel, row, col)
            panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Set equal column and row stretches
        self.grid_layout.setColumnStretch(0, 1)
        self.grid_layout.setColumnStretch(1, 1)
        self.grid_layout.setRowStretch(0, 1)
        self.grid_layout.setRowStretch(1, 1)

    def create_panel(self, title, content_widget, header_color):
            panel = QWidget()
            panel.setObjectName("PanelWidget")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            
            header = QLabel(title)
            header.setObjectName("HeaderLabel")
            header.setAlignment(Qt.AlignCenter)
            header.setFixedHeight(30)
            header.setStyleSheet(f"color: {header_color};")  # Set inline color
            layout.addWidget(header)

            content_widget.setObjectName("ContentWidget")
            content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout.addWidget(content_widget)

            return panel

    def create_backup_schedule_panel(self):
        content = QWidget()
        content.setObjectName("ContentWidget")
        layout = QVBoxLayout(content)
        
        # You can add content here in the future
        layout.addStretch(1)  # This will push any future content to the top

        return self.create_panel('Backup Schedule', content, '#3498DB')  # You can change the color as needed

    def create_configuration_dashboard(self):
        content = QWidget()
        content.setObjectName("ContentWidget")
        main_layout = QVBoxLayout(content)

        # Create two subpanels
        subpanel_layout = QHBoxLayout()
        left_subpanel = self.create_subpanel("Settings")
        right_subpanel = self.create_subpanel("Properties")

        # Add vertical divider
        vertical_line = QFrame()
        vertical_line.setFrameShape(QFrame.VLine)
        vertical_line.setStyleSheet("color: #666;")

        subpanel_layout.addWidget(left_subpanel)
        subpanel_layout.addWidget(vertical_line)
        subpanel_layout.addWidget(right_subpanel)

        main_layout.addLayout(subpanel_layout)

        return self.create_panel('Configuration Dashboard', content, '#2ECC71')

    def create_subpanel(self, title):
        subpanel = QWidget()
        layout = QVBoxLayout(subpanel)

        # Subpanel header
        header = QLabel(title)
        header.setStyleSheet("font-weight: bold; padding-bottom: 5px;")
        layout.addWidget(header)

        # Horizontal divider
        horizontal_line = QFrame()
        horizontal_line.setFrameShape(QFrame.HLine)
        horizontal_line.setStyleSheet("color: #666;")
        layout.addWidget(horizontal_line)

        # Content
        if title == "Settings":
            self.status_value_text = QLabel('Unknown')
            status_layout = QHBoxLayout()
            status_layout.addWidget(QLabel('Backup Engine Status:'))
            status_layout.addWidget(self.status_value_text)
            layout.addLayout(status_layout)

            self.component2_dropdown = QComboBox()
            self.component2_dropdown.addItems(['Option 1', 'Option 2', 'Option 3'])
            self.component2_dropdown.currentIndexChanged.connect(self.on_component2_changed)
            component2_layout = QHBoxLayout()
            component2_layout.addWidget(QLabel('Component 2:'))
            component2_layout.addWidget(self.component2_dropdown)
            layout.addLayout(component2_layout)

        elif title == "Properties":
            properties_layout = QFormLayout()
            self.agent_id_value = QLabel('Unknown')
            self.api_key_value = QLabel('Unknown')
            properties_layout.addRow('AGENT_ID:', self.agent_id_value)
            properties_layout.addRow('API_KEY:', self.api_key_value)
            layout.addLayout(properties_layout)
        
            # agent_id_layout = QFormLayout()
            # agent_id_layout.addWidget(QLabel('AGENT_ID:'))
            # self.agent_id_value = QLabel('Unknown')
            # agent_id_layout.addRow('AGENT_ID:', self.agent_id_value)
            # layout.addLayout(agent_id_layout)

            # api_key_layout = QFormLayout()
            # api_key_layout.addWidget(QLabel('API_KEY:'))
            # self.api_key_value = QLabel('Unknown')
            # api_key_layout.addRow('API_KEY:', self.api_key_value)
            # layout.addLayout(api_key_layout)

        layout.addStretch(1)  # Add stretch to push content to the top
        return subpanel

    def on_component2_changed(self, index):
        selected_option = self.component2_dropdown.currentText()
        logging.info(f"Component 2 option changed to: {selected_option}")

    # def create_properties_panel(self):
        # content = QWidget()
        # content.setObjectName("ContentWidget")
        # layout = QFormLayout(content)
        
        # self.agent_id_value = QLabel('Unknown')
        # self.api_key_value = QLabel('Unknown')
        # layout.addRow('AGENT_ID:', self.agent_id_value)
        # layout.addRow('API_KEY:', self.api_key_value)

        # return self.create_panel('Properties', content, '#9B59B6')

    def create_web_links_panel(self):
        content = QWidget()
        content.setObjectName("ContentWidget")
        layout = QVBoxLayout(content)
        
        self.add_web_link(layout, "https://apps.darkage.io", "Stormcloud Apps")
        self.add_web_link(layout, "https://darkage.io", "Darkage Homepage")
        self.add_web_link(layout, "https://darkage.io/support", "Support")

        layout.addStretch(1)
        
        return self.create_panel('Stormcloud Web', content, '#3498DB')

    def create_backed_up_folders_panel(self):
        content = QWidget()
        content.setObjectName("ContentWidget")
        layout = QVBoxLayout(content)

        self.backup_paths_list = QListWidget()
        self.backup_paths_list.setSelectionMode(QListWidget.NoSelection)
        layout.addWidget(self.backup_paths_list)

        add_folder_button = QPushButton("Add Folder to Backup")
        add_folder_button.clicked.connect(self.add_backup_folder)
        layout.addWidget(add_folder_button)

        return self.create_panel('Backed Up Folders', content, '#F1C40F')

    def add_backup_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Backup")
        if folder:
            self.add_folder_to_backup(folder)
            
    def add_folder_to_backup(self, folder, recursive=False):
        if recursive:
            self.recursive_backup_paths.append(folder)
        else:
            self.backup_paths.append(folder)
        
        self.update_backup_paths()
        self.update_settings_file()

    def update_settings_file(self):
        if not hasattr(self, 'settings_cfg_path') or not os.path.exists(self.settings_cfg_path):
            StormcloudMessageBox.critical(self, 'Error', 'Settings file not found.')
            return

        try:
            with open(self.settings_cfg_path, 'r') as f:
                settings = f.read().splitlines()

            # Update BACKUP_PATHS section
            self.update_settings_section(settings, "BACKUP_PATHS:", self.backup_paths)

            # Update RECURSIVE_BACKUP_PATHS section
            self.update_settings_section(settings, "RECURSIVE_BACKUP_PATHS:", self.recursive_backup_paths)

            # Write the updated settings back to the file
            with open(self.settings_cfg_path, 'w') as f:
                f.write("\n".join(settings))

            logging.info('Settings file updated successfully.')
            self.update_backup_paths()  # Refresh the UI
        except Exception as e:
            logging.error('Failed to update settings file: %s', e)
            StormcloudMessageBox.critical(self, 'Error', f'Failed to update settings file: {e}')

    def update_settings_section(self, settings, section_name, paths):
        section_index = settings.index(section_name) if section_name in settings else -1
        if section_index != -1:
            # Remove existing paths
            while section_index + 1 < len(settings) and settings[section_index + 1].startswith("-"):
                settings.pop(section_index + 1)
            
            # Add updated paths
            for path in paths:
                settings.insert(section_index + 1, f"- {path}")
        else:
            # If section doesn't exist, add it
            settings.append(section_name)
            for path in paths:
                settings.append(f"- {path}")

    def add_web_link(self, layout, url, text):
        link_button = QPushButton(text)
        link_button.setObjectName("WebLink")
        link_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        link_button.setProperty('clickable', 'true')
        layout.addWidget(link_button)

    def load_settings(self):
        appdata_path = os.getenv('APPDATA')
        settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')
        
        if not os.path.exists(settings_path):
            logging.error('Settings file not found at %s', settings_path)
            StormcloudMessageBox.critical(self, 'Error', 'Settings file not found. Please reinstall the application.')
            return

        with open(settings_path, 'r') as f:
            stable_settings = json.load(f)

        install_path = stable_settings.get('install_path', '').replace('\\', '/')
        self.settings_cfg_path = os.path.join(install_path, 'settings.cfg').replace('\\', '/')

        if not os.path.exists(self.settings_cfg_path):
            logging.error('Configuration file not found at %s', self.settings_cfg_path)
            StormcloudMessageBox.critical(self, 'Error', 'Configuration file not found in the installation directory.')

    def load_backup_paths(self):
        if not hasattr(self, 'settings_cfg_path') or not os.path.exists(self.settings_cfg_path):
            return

        with open(self.settings_cfg_path, 'r') as f:
            settings = f.read().splitlines()

        self.backup_paths = []
        self.recursive_backup_paths = []
        current_key = None

        for line in settings:
            line = line.strip()
            if line == "BACKUP_PATHS:":
                current_key = "BACKUP_PATHS"
            elif line == "RECURSIVE_BACKUP_PATHS:":
                current_key = "RECURSIVE_BACKUP_PATHS"
            elif line.startswith("-") and current_key:
                path = line[1:].strip()
                if current_key == "BACKUP_PATHS":
                    self.backup_paths.append(path)
                elif current_key == "RECURSIVE_BACKUP_PATHS":
                    self.recursive_backup_paths.append(path)

        self.update_backup_paths()

    def load_properties(self):
        if not hasattr(self, 'settings_cfg_path') or not os.path.exists(self.settings_cfg_path):
            return

        with open(self.settings_cfg_path, 'r') as f:
            settings = f.read().splitlines()

        for line in settings:
            if line.startswith("AGENT_ID:"):
                self.agent_id_value.setText(line.split(":")[1].strip())
            elif line.startswith("API_KEY:"):
                self.api_key_value.setText(line.split(":")[1].strip())

    def toggle_recursive(self, path, recursive):
        if recursive and path in self.backup_paths:
            self.backup_paths.remove(path)
            self.recursive_backup_paths.append(path)
        elif not recursive and path in self.recursive_backup_paths:
            self.recursive_backup_paths.remove(path)
            self.backup_paths.append(path)
        
        self.update_settings_file()

    def update_backup_paths(self):
        self.backup_paths_list.clear()
        for path in self.backup_paths + self.recursive_backup_paths:
            item = QListWidgetItem(self.backup_paths_list)
            widget = QWidget()
            layout = QHBoxLayout(widget)
            
            checkbox = QCheckBox()
            checkbox.setChecked(path in self.recursive_backup_paths)
            checkbox.stateChanged.connect(lambda state, p=path: self.toggle_recursive(p, state == Qt.Checked))
            
            label = QLabel(path)
            label.setWordWrap(True)
            
            layout.addWidget(checkbox)
            layout.addWidget(label, stretch=1)
            layout.setContentsMargins(5, 2, 5, 2)
            layout.setAlignment(Qt.AlignLeft)
            widget.setLayout(layout)
            
            item.setSizeHint(widget.sizeHint())
            self.backup_paths_list.setItemWidget(item, widget)

    def update_status(self):
        running = self.is_backup_engine_running()
        self.status_value_text.setText('Running' if running else 'Not Running')
        self.status_value_text.setStyleSheet('color: #28A745;' if running else 'color: #DC3545;')
        self.start_button.setText('Stop Backup Engine' if running else 'Start Backup Engine')

    def toggle_backup_engine(self):
        if self.is_backup_engine_running():
            self.stop_backup_engine()
        else:
            self.start_backup_engine()

    def is_backup_engine_running(self):
        return any(proc.info['name'] == 'stormcloud.exe' for proc in psutil.process_iter(['name']))

    def start_backup_engine(self):
        if self.is_backup_engine_running():
            StormcloudMessageBox.information(self, 'Info', 'Backup engine is already running.')
            return

        try:
            exe_path = os.path.join(os.path.dirname(self.settings_cfg_path), 'stormcloud.exe').replace('\\', '/')
            subprocess.Popen([exe_path], shell=True)
            logging.info('Backup engine started successfully at %s', exe_path)
            StormcloudMessageBox.information(self, 'Info', 'Backup engine started successfully.')
        except Exception as e:
            logging.error('Failed to start backup engine: %s', e)
            StormcloudMessageBox.critical(self, 'Error', f'Failed to start backup engine: {e}')
        finally:
            self.update_status()

    def stop_backup_engine(self):
        if not self.is_backup_engine_running():
            StormcloudMessageBox.information(self, 'Info', 'Backup engine is not running.')
            return

        try:
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] == 'stormcloud.exe':
                    proc.terminate()
                    proc.wait(timeout=10)  # Wait for the process to terminate
                    if proc.is_running():
                        proc.kill()  # Force kill if it doesn't terminate
                    logging.info('Backup engine stopped successfully.')
                    StormcloudMessageBox.information(self, 'Info', 'Backup engine stopped successfully.')
                    break
        except Exception as e:
            logging.error('Failed to stop backup engine: %s', e)
            StormcloudMessageBox.critical(self, 'Error', f'Failed to stop backup engine: {e}')
        finally:
            self.update_status()

if __name__ == '__main__':
    app = QApplication([])
    window = StormcloudApp()
    window.show()
    app.exec_()