import csv
import os
import json
import psutil
import subprocess
import logging

import win32api
import win32gui
import win32con

from datetime import datetime

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QToolButton, QListWidget, QListWidgetItem,
                             QMessageBox, QFileDialog, QGridLayout, QFormLayout,
                             QScrollArea, QSizePolicy, QCheckBox, QComboBox, QFrame,
                             QCalendarWidget, QTimeEdit, QStackedWidget, QGroupBox, QSpinBox,
                             QTreeView, QHeaderView, QStyle, QStyledItemDelegate, QLineEdit,
                             QAbstractItemView, QSplitter, QTreeWidget, QTreeWidgetItem, QDialog, QTextEdit)
from PyQt5.QtCore import Qt, QUrl, QPoint, QDate, QTime, pyqtSignal, QRect, QSize, QModelIndex, QObject
from PyQt5.QtGui import (QDesktopServices, QFont, QIcon, QColor,
                         QPalette, QPainter, QPixmap, QTextCharFormat,
                         QStandardItemModel, QStandardItem)
from PyQt5.QtWinExtras import QtWin


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', 
                    filename='stormcloud_app.log', filemode='a')

def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

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
        self.backup_schedule = {'weekly': {}, 'monthly': {}}
        self.set_app_icon()
        self.create_spinbox_arrow_icons()
        self.init_ui()
        self.load_settings()
        self.update_status()
        self.load_backup_paths()
        self.load_properties()
        self.apply_backup_mode()

    def set_app_icon(self):
        appdata_path = os.getenv('APPDATA')
        stable_settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')
        
        if os.path.exists(stable_settings_path):
            with open(stable_settings_path, 'r') as f:
                stable_settings = json.load(f)
            
            install_path = stable_settings.get('install_path', '')
            exe_path = os.path.join(install_path, 'stormcloud.exe')
            
            if os.path.exists(exe_path):
                try:
                    # Extract icon
                    large, small = win32gui.ExtractIconEx(exe_path, 0)
                    if large:
                        win32gui.DestroyIcon(small[0])
                        
                        # Convert icon to HICON
                        hicon = large[0]
                        
                        # Use QtWin to convert HICON to QPixmap
                        pixmap = QtWin.fromHICON(hicon)
                        
                        # Create QIcon and set it
                        app_icon = QIcon(pixmap)
                        self.setWindowIcon(app_icon)
                        QApplication.setWindowIcon(app_icon)
                        
                        # Clean up
                        win32gui.DestroyIcon(hicon)
                    else:
                        print("No icon found in the executable.")
                except Exception as e:
                    print(f"Failed to set icon: {e}")
            else:
                print(f"Executable not found at {exe_path}")
        else:
            print(f"Settings file not found at {stable_settings_path}")

    def create_spinbox_arrow_icons(self):
        # Create up arrow icon
        up_arrow = QPixmap(8, 8)
        up_arrow.fill(Qt.transparent)
        painter = QPainter(up_arrow)
        painter.setBrush(QColor('#e8eaed'))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPoint(0, 6), QPoint(4, 2), QPoint(8, 6))
        painter.end()
        up_arrow.save('up-arrow.png')

        # Create down arrow icon
        down_arrow = QPixmap(8, 8)
        down_arrow.fill(Qt.transparent)
        painter = QPainter(down_arrow)
        painter.setBrush(QColor('#e8eaed'))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPoint(0, 2), QPoint(4, 6), QPoint(8, 2))
        painter.end()
        down_arrow.save('down-arrow.png')

    def init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Header with centered Start Backup Engine button
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.addStretch()
        self.start_button = QPushButton('Start Backup Engine')
        self.start_button.setFixedSize(200, 40)
        self.start_button.clicked.connect(self.toggle_backup_engine)
        self.start_button.setCursor(Qt.PointingHandCursor)
        header_layout.addWidget(self.start_button)
        header_layout.addStretch()
        main_layout.addWidget(header_widget)

        # Grid layout for panels
        grid_widget = QWidget()
        self.grid_layout = QGridLayout(grid_widget)
        self.setup_grid_layout()
        main_layout.addWidget(grid_widget)

        self.setStyleSheet(self.get_stylesheet())

    def on_backup_versions_changed(self, value):
        print(f"Number of backup versions changed to: {value}")

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
                background-color: #4285F4;
                border: none;
                font-size: 16px;
                padding: 5px 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #5294FF;
            }
            QPushButton#start_button {
                background-color: #4285F4;
                color: white;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton#start_button:hover {
                background-color: #5294FF;
            }
            QPushButton#start_button:pressed {
                background-color: #3275E4;
            }
            QPushButton#FolderBackupButton {
                font-size: 14px;
            }
            QLabel {
                font-size: 14px;
            }
            
            /* Updated styles for QListWidget and QTreeWidget */
            QListWidget, QTreeWidget {
                background-color: #333;
                border: none;
                border-radius: 5px;
                outline: 0;
                padding: 1px;
            }

            QListWidget::item, QTreeWidget::item {
                padding: 5px;
            }

            QListWidget::item:hover, QTreeWidget::item:hover {
                background-color: #3c4043;
            }

            QListWidget::item:selected, QTreeWidget::item:selected {
                background-color: #444;
                color: #8ab4f8;
            }
            
            /* Pseudo-element for rounded border */
            QListWidget::after, QTreeWidget::after {
                content: '';
                position: absolute;
                top: 0;
                right: 0;
                bottom: 0;
                left: 0;
                border: 1px solid #666;
                border-radius: 5px;
                pointer-events: none;
            }
            
            QListWidget::item:focus {
                border: none;
                outline: none;
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
                color: #e8eaed;
                border: 1px solid #666;
                border-radius: 5px;
                padding: 5px;
                min-width: 6em;
            }
            QComboBox:hover {
                border-color: #8ab4f8;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 20px;
                border-left: none;
                background: transparent;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #666;
                background-color: #333;
                selection-background-color: #4285F4;
            }
            QPushButton {
                background-color: #4285F4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 5px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #5294FF;
            }
            QPushButton:pressed {
                background-color: #3275E4;
            }
            QFrame[frameShape="4"],  /* HLine */
            QFrame[frameShape="5"] {  /* VLine */
                color: #666;
                width: 1px;
                height: 1px;
            }
            QWidget:disabled {
                color: #888;
            }
            QComboBox:disabled, QTimeEdit:disabled {
                background-color: #555;
                color: #888;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
            QCheckBox {
                spacing: 5px;
            }
            #FootnoteLabel {
                color: #999;
                font-size: 14px;
                font-style: italic;
                padding-top: 5px;
                padding-bottom: 5px;
            }
            QScrollBar:vertical {
                border: none;
                background: #2a2a2a;
                width: 10px;
                margin: 0px;
            }

            QScrollBar::handle:vertical {
                background: #5a5a5a;
                min-height: 30px;
                border-radius: 5px;
            }

            QScrollBar::handle:vertical:hover {
                background: #6a6a6a;
            }

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }

            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }

            QScrollBar:horizontal {
                border: none;
                background: #2a2a2a;
                height: 10px;
                margin: 0px;
            }

            QScrollBar::handle:horizontal {
                background: #5a5a5a;
                min-width: 30px;
                border-radius: 5px;
            }

            QScrollBar::handle:horizontal:hover {
                background: #6a6a6a;
            }

            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }

            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
        """

    def setup_grid_layout(self):
        # Top-left panel (Configuration Dashboard)
        config_dashboard = self.create_configuration_dashboard()
        self.grid_layout.addWidget(config_dashboard, 0, 0)

        # Top-right panel (Backup Schedule)
        backup_schedule = self.create_backup_schedule_panel()
        self.grid_layout.addWidget(backup_schedule, 0, 1)

        # Bottom-left panel (Blank for now)
        blank_panel = self.create_blank_panel()
        self.grid_layout.addWidget(blank_panel, 1, 0)

        # Bottom-right panel (Stormcloud Web and Backed Up Folders)
        bottom_right_panel = self.create_bottom_right_panel()
        self.grid_layout.addWidget(bottom_right_panel, 1, 1)

        # Set equal column and row stretches
        self.grid_layout.setColumnStretch(0, 1)
        self.grid_layout.setColumnStretch(1, 1)
        self.grid_layout.setRowStretch(0, 1)
        self.grid_layout.setRowStretch(1, 1)

    def create_web_links_subpanel(self):
        subpanel = QWidget()
        layout = QVBoxLayout(subpanel)

        # Subpanel header
        header = QLabel("Stormcloud Web")
        header.setStyleSheet("font-weight: bold; padding-bottom: 5px;")
        layout.addWidget(header)

        # Horizontal divider
        horizontal_line = QFrame()
        horizontal_line.setFrameShape(QFrame.HLine)
        horizontal_line.setStyleSheet("color: #666;")
        layout.addWidget(horizontal_line)

        # Web links
        self.add_web_link(layout, "https://apps.darkage.io", "Stormcloud Apps")
        self.add_web_link(layout, "https://darkage.io", "Darkage Homepage")
        self.add_web_link(layout, "https://darkage.io/support", "Support")

        layout.addStretch(1)
        return subpanel

    def create_bottom_right_panel(self):
        content = QWidget()
        content.setObjectName("ContentWidget")
        main_layout = QVBoxLayout(content)

        # Create two subpanels
        subpanel_layout = QHBoxLayout()
        left_subpanel = self.create_web_links_subpanel()
        right_subpanel = self.create_backed_up_folders_subpanel()

        # Add vertical divider
        vertical_line = QFrame()
        vertical_line.setFrameShape(QFrame.VLine)
        vertical_line.setStyleSheet("color: #666;")

        # Set width proportions
        subpanel_layout.addWidget(left_subpanel, 50)
        subpanel_layout.addWidget(vertical_line)
        subpanel_layout.addWidget(right_subpanel, 50)

        main_layout.addLayout(subpanel_layout)

        return self.create_panel('Web & Folders', content, '#3498DB')

    def create_blank_panel(self):
        appdata_path = os.getenv('APPDATA')
        json_directory = os.path.join(appdata_path, 'Stormcloud')
        
        if not os.path.exists(json_directory):
            os.makedirs(json_directory)
        
        file_explorer = FileExplorerPanel(json_directory)
        return self.create_panel('File Explorer', file_explorer, '#3498DB')

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
        content.setObjectName("BackupSchedulePanel")
        layout = QVBoxLayout(content)

        self.schedule_calendar = BackupScheduleCalendar()
        self.schedule_calendar.schedule_updated.connect(self.update_backup_schedule)
        layout.addWidget(self.schedule_calendar)

        return self.create_panel('Backup Schedule', content, '#3498DB')

    def format_backup_schedule(self):
        schedule_dict = {
            'weekly': {},
            'monthly': {}
        }
        
        for schedule_type in ['weekly', 'monthly']:
            for day, times in self.backup_schedule[schedule_type].items():
                schedule_dict[schedule_type][day] = [time.toString('HH:mm') for time in times]
        
        schedule_json = json.dumps(schedule_dict, indent=2)
        schedule_lines = ['BACKUP_SCHEDULE:'] + schedule_json.split('\n')
        
        return schedule_lines

    def save_backup_settings(self):
        if not hasattr(self, 'settings_cfg_path') or not os.path.exists(self.settings_cfg_path):
            StormcloudMessageBox.critical(self, 'Error', 'Settings file not found.')
            return

        try:
            with open(self.settings_cfg_path, 'r') as f:
                settings = f.read().splitlines()

            # Update or add BACKUP_MODE
            backup_mode_line = f"BACKUP_MODE: {self.backup_mode}"
            mode_index = next((i for i, line in enumerate(settings) if line.startswith("BACKUP_MODE:")), -1)
            if mode_index >= 0:
                settings[mode_index] = backup_mode_line
            else:
                settings.append(backup_mode_line)

            # Update BACKUP_SCHEDULE
            schedule_lines = self.format_backup_schedule()
            schedule_start = next((i for i, line in enumerate(settings) if line.startswith("BACKUP_SCHEDULE:")), -1)
            if schedule_start >= 0:
                # Remove old schedule
                schedule_end = next((i for i in range(schedule_start + 1, len(settings)) if not settings[i].strip()), len(settings))
                settings[schedule_start:schedule_end] = schedule_lines
            else:
                settings.extend(schedule_lines)

            # Write updated settings back to file
            with open(self.settings_cfg_path, 'w') as f:
                f.write('\n'.join(settings))

            logging.info('Backup mode and schedule settings updated successfully.')
        except Exception as e:
            logging.error('Failed to update backup mode and schedule settings: %s', e)
            StormcloudMessageBox.critical(self, 'Error', f'Failed to update backup mode and schedule settings: {e}')

    def update_backup_schedule(self, schedule):
        self.backup_schedule = schedule
        self.save_backup_settings()

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

            self.backup_mode_dropdown = QComboBox()
            self.backup_mode_dropdown.addItems(['Realtime', 'Scheduled'])
            self.backup_mode_dropdown.currentIndexChanged.connect(self.on_backup_mode_changed)
            self.backup_mode_dropdown.setCursor(Qt.PointingHandCursor)
            backup_mode_layout = QHBoxLayout()
            backup_mode_layout.addWidget(QLabel('Backup Mode:'))
            backup_mode_layout.addWidget(self.backup_mode_dropdown)
            layout.addLayout(backup_mode_layout)

            # Updated Number of Backup Versions setting
            self.backup_versions_spinbox = QSpinBox()
            self.backup_versions_spinbox.setMinimum(1)
            self.backup_versions_spinbox.setMaximum(100)
            self.backup_versions_spinbox.setValue(5)  # Default value
            self.backup_versions_spinbox.valueChanged.connect(self.on_backup_versions_changed)
            self.backup_versions_spinbox.setStyleSheet("""
                QSpinBox {
                    background-color: #333;
                    color: #e8eaed;
                    border: 1px solid #666;
                    border-radius: 5px;
                    padding: 5px;
                    min-width: 6em;
                }
                QSpinBox:hover {
                    border-color: #8ab4f8;
                }
            """)
            backup_versions_layout = QHBoxLayout()
            backup_versions_layout.addWidget(QLabel('Number of Backup Versions:'))
            backup_versions_layout.addWidget(self.backup_versions_spinbox)
            layout.addLayout(backup_versions_layout)

        elif title == "Properties":
            properties_layout = QFormLayout()
            self.agent_id_value = QLabel('Unknown')
            self.api_key_value = QLabel('Unknown')
            properties_layout.addRow('AGENT_ID:', self.agent_id_value)
            properties_layout.addRow('API_KEY:', self.api_key_value)
            layout.addLayout(properties_layout)

        layout.addStretch(1)  # Add stretch to push content to the top
        return subpanel

    def save_backup_mode(self):
        if not hasattr(self, 'settings_cfg_path') or not os.path.exists(self.settings_cfg_path):
            StormcloudMessageBox.critical(self, 'Error', 'Settings file not found.')
            return

        try:
            with open(self.settings_cfg_path, 'r') as f:
                settings = f.read().splitlines()

            # Update or add BACKUP_MODE
            backup_mode_line = f"BACKUP_MODE: {self.backup_mode}"
            mode_index = next((i for i, line in enumerate(settings) if line.startswith("BACKUP_MODE:")), -1)
            if mode_index >= 0:
                settings[mode_index] = backup_mode_line
            else:
                settings.append(backup_mode_line)

            # Update or add BACKUP_SCHEDULE if mode is Scheduled
            schedule_start = next((i for i, line in enumerate(settings) if line.startswith("BACKUP_SCHEDULE:")), -1)
            if schedule_start >= 0:
                # Remove old schedule
                while schedule_start + 1 < len(settings) and settings[schedule_start + 1].startswith("-"):
                    settings.pop(schedule_start + 1)
            else:
                schedule_start = len(settings)
                settings.append("BACKUP_SCHEDULE:")

            if self.backup_mode == 'Scheduled':
                for schedule_type in ['weekly', 'monthly']:
                    if self.backup_schedule[schedule_type]:
                        settings.insert(schedule_start + 1, f"- {schedule_type}:")
                        for day, times in self.backup_schedule[schedule_type].items():
                            time_strings = [time.toString('HH:mm') for time in times]
                            settings.insert(schedule_start + 2, f"  - {day}: {', '.join(time_strings)}")
                        schedule_start += 2

            # Write updated settings back to file
            with open(self.settings_cfg_path, 'w') as f:
                f.write("\n".join(settings))

            logging.info('Backup mode and schedule settings updated successfully.')
        except Exception as e:
            logging.error('Failed to update backup mode and schedule settings: %s', e)
            StormcloudMessageBox.critical(self, 'Error', f'Failed to update backup mode and schedule settings: {e}')

    def on_backup_mode_changed(self, index):
        mode = self.backup_mode_dropdown.currentText()
        self.backup_mode = mode
        self.toggle_backup_schedule_panel(mode == 'Scheduled')
        if mode == 'Scheduled':
            self.update_backup_schedule_widget()
        self.save_backup_settings()
        logging.info(f"Backup mode changed to: {mode}")

    def toggle_backup_schedule_panel(self, enabled):
        # Find the Backup Schedule panel and enable/disable it
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if isinstance(widget, QWidget) and widget.findChild(QLabel, "HeaderLabel").text() == 'Backup Schedule':
                content_widget = widget.findChild(QWidget, "ContentWidget")
                if content_widget:
                    content_widget.setEnabled(enabled)
                    content_widget.setStyleSheet(f"QWidget {{ background-color: {'#333' if enabled else '#555'}; }}")
                break

    def create_web_links_panel(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        
        self.add_web_link(layout, "https://apps.darkage.io", "Stormcloud Apps")
        self.add_web_link(layout, "https://darkage.io", "Darkage Homepage")
        self.add_web_link(layout, "https://darkage.io/support", "Support")

        layout.addStretch(1)
        
        return self.create_panel('Stormcloud Web', content, '#3498DB')

    def remove_backup_folder(self):
        current_item = self.backup_paths_list.currentItem()
        if current_item:
            folder = current_item.data(Qt.UserRole)
            row = self.backup_paths_list.row(current_item)
            self.backup_paths_list.takeItem(row)
            
            if folder in self.backup_paths:
                self.backup_paths.remove(folder)
            if folder in self.recursive_backup_paths:
                self.recursive_backup_paths.remove(folder)
            
            self.update_settings_file()

    def create_backed_up_folders_subpanel(self):
        subpanel = QWidget()
        layout = QVBoxLayout(subpanel)

        # Subpanel header
        header = QLabel("Backed Up Folders")
        header.setStyleSheet("font-weight: bold; padding-bottom: 5px;")
        layout.addWidget(header)

        # Horizontal divider
        horizontal_line = QFrame()
        horizontal_line.setFrameShape(QFrame.HLine)
        horizontal_line.setStyleSheet("color: #666;")
        layout.addWidget(horizontal_line)

        # Backed up folders content
        self.backup_paths_list = QListWidget()
        self.backup_paths_list.setSelectionMode(QListWidget.SingleSelection)
        layout.addWidget(self.backup_paths_list)

        footnote = QLabel("Check the box to include subfolders in the backup.")
        footnote.setObjectName("FootnoteLabel")
        footnote.setWordWrap(True)
        layout.addWidget(footnote)

        buttons_layout = QHBoxLayout()
        add_folder_button = QPushButton("Add Folder")
        add_folder_button.setObjectName("FolderBackupButton")
        add_folder_button.clicked.connect(self.add_backup_folder)
        add_folder_button.setCursor(Qt.PointingHandCursor)
        buttons_layout.addWidget(add_folder_button)

        remove_folder_button = QPushButton("Remove Selected")
        remove_folder_button.setObjectName("FolderBackupButton")
        remove_folder_button.clicked.connect(self.remove_backup_folder)
        remove_folder_button.setCursor(Qt.PointingHandCursor)
        buttons_layout.addWidget(remove_folder_button)

        layout.addLayout(buttons_layout)

        return subpanel

    def add_backup_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Backup")
        if folder:
            self.add_folder_to_backup(folder)
            
    def create_folder_item_widget(self, folder, recursive):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(5, 2, 5, 2)

        checkbox = QCheckBox()
        checkbox.setChecked(recursive)
        checkbox.stateChanged.connect(lambda state, f=folder: self.toggle_recursive(f, state == Qt.Checked))

        label = QLabel(folder)
        label.setWordWrap(True)

        layout.addWidget(checkbox)
        layout.addWidget(label, stretch=1)
        layout.setAlignment(Qt.AlignLeft)

        return widget
            
    def add_folder_to_backup(self, folder, recursive=False):
        # Check if the folder is already in the list
        for i in range(self.backup_paths_list.count()):
            item = self.backup_paths_list.item(i)
            if item.data(Qt.UserRole) == folder:
                return  # Folder already exists, don't add it again

        item = QListWidgetItem(self.backup_paths_list)
        widget = self.create_folder_item_widget(folder, recursive)
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.UserRole, folder)
        self.backup_paths_list.setItemWidget(item, widget)

        # Only add to the lists if not already present
        if recursive and folder not in self.recursive_backup_paths:
            self.recursive_backup_paths.append(folder)
        elif not recursive and folder not in self.backup_paths:
            self.backup_paths.append(folder)

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

    def update_schedule_list(self):
        if hasattr(self, 'schedule_list'):
            self.schedule_list.clear()
            for schedule_type in ['weekly', 'monthly']:
                for day, times in self.backup_schedule[schedule_type].items():
                    for time in times:
                        item_text = f"{schedule_type.capitalize()} - {day} - {time.toString('HH:mm')}"
                        self.schedule_list.addItem(item_text)

    def update_backup_schedule_widget(self):
        if hasattr(self, 'schedule_calendar'):
            self.schedule_calendar.set_schedule(self.backup_schedule)

    def load_backup_mode(self):
        with open(self.settings_cfg_path, 'r') as f:
            settings = f.read().splitlines()

        self.backup_mode = 'Realtime'  # Default value
        for line in settings:
            if line.startswith("BACKUP_MODE:"):
                self.backup_mode = line.split(":")[1].strip()
                break
        else:
            # If BACKUP_MODE is not found, add it with default value
            with open(self.settings_cfg_path, 'a') as f:
                f.write("\nBACKUP_MODE: Realtime")

    def apply_backup_mode(self):
        index = self.backup_mode_dropdown.findText(self.backup_mode)
        if index >= 0:
            self.backup_mode_dropdown.setCurrentIndex(index)
        
        is_scheduled = self.backup_mode == 'Scheduled'
        self.toggle_backup_schedule_panel(is_scheduled)
        
        if is_scheduled:
            self.update_backup_schedule_widget()

    def load_backup_schedule(self):
        with open(self.settings_cfg_path, 'r') as f:
            settings = f.read()

        self.backup_schedule = {'weekly': {}, 'monthly': {}}
        
        # Find the BACKUP_SCHEDULE section
        start_index = settings.find("BACKUP_SCHEDULE:")
        if start_index == -1:
            return  # No backup schedule found
        
        # Extract the JSON string
        json_start = settings.find("{", start_index)
        json_end = settings.rfind("}") + 1
        if json_start == -1 or json_end == -1:
            return  # Invalid format
        
        schedule_str = settings[json_start:json_end]
        
        # Parse the schedule
        try:
            schedule_dict = json.loads(schedule_str)
            for schedule_type in ['weekly', 'monthly']:
                if schedule_type in schedule_dict:
                    for day, times in schedule_dict[schedule_type].items():
                        self.backup_schedule[schedule_type][day] = [QTime.fromString(t, "HH:mm") for t in times]
            logging.info(f"Loaded backup schedule: {self.backup_schedule}")
        except json.JSONDecodeError:
            logging.error("Failed to parse backup schedule")
        
        self.update_backup_schedule_widget()

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
            return

        self.load_backup_mode()
        self.load_backup_schedule()

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

    def toggle_recursive(self, folder, recursive):
        if recursive and folder in self.backup_paths:
            self.backup_paths.remove(folder)
            self.recursive_backup_paths.append(folder)
        elif not recursive and folder in self.recursive_backup_paths:
            self.recursive_backup_paths.remove(folder)
            self.backup_paths.append(folder)
        
        self.update_settings_file()

    def add_folder_to_list(self, folder, recursive):
        item = QListWidgetItem(self.backup_paths_list)
        widget = self.create_folder_item_widget(folder, recursive)
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.UserRole, folder)
        self.backup_paths_list.setItemWidget(item, widget)

    def update_backup_paths(self):
        self.backup_paths_list.clear()
        for path in self.backup_paths:
            self.add_folder_to_list(path, False)
        for path in self.recursive_backup_paths:
            self.add_folder_to_list(path, True)

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

# Calendar Widget
# ---------------

class TimeSlot(QPushButton):
    clicked_with_time = pyqtSignal(QTime)

    def __init__(self, time):
        super().__init__()
        self.time = time
        self.setFixedSize(80, 30)
        self.setText(time.toString("hh:mm"))
        self.setCheckable(True)
        self.clicked.connect(self.emit_clicked_with_time)

    def emit_clicked_with_time(self):
        self.clicked_with_time.emit(self.time)
    schedule_updated = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.initUI()
        self.schedule = {day: [] for day in range(7)}

    def initUI(self):
        layout = QVBoxLayout(self)

        # Days of the week
        days_layout = QHBoxLayout()
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        for day in days:
            label = QLabel(day)
            label.setAlignment(Qt.AlignCenter)
            days_layout.addWidget(label)
        layout.addLayout(days_layout)

        # Time slots
        time_layout = QGridLayout()
        for col, day in enumerate(range(7)):
            for row, hour in enumerate(range(24)):
                for minute in [0, 30]:
                    time = QTime(hour, minute)
                    slot = TimeSlot(time)
                    slot.clicked_with_time.connect(lambda t, d=day: self.toggle_time_slot(d, t))
                    time_layout.addWidget(slot, row*2 + (minute//30), col)

        # Make the time layout scrollable
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_widget.setLayout(time_layout)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll_area)

    def toggle_time_slot(self, day, time):
        if time in self.schedule[day]:
            self.schedule[day].remove(time)
        else:
            self.schedule[day].append(time)
        self.schedule_updated.emit(self.schedule)

    def set_schedule(self, schedule):
        self.schedule = schedule

class BackupScheduleCalendar(QWidget):
    schedule_updated = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.schedule = {'weekly': {}, 'monthly': {}}
        self.initUI()
        self.apply_styles()

    def initUI(self):
        main_layout = QHBoxLayout(self)

        # Left side: Schedule setup
        schedule_setup = QWidget()
        schedule_layout = QVBoxLayout(schedule_setup)

        # Horizontal layout for Weekly and Monthly sections
        backup_types_layout = QHBoxLayout()

        # Weekly scheduling
        weekly_group = QGroupBox("Weekly Backup")
        weekly_layout = QVBoxLayout(weekly_group)

        self.day_combo = QComboBox()
        self.day_combo.addItems(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])
        self.day_combo.setCursor(Qt.PointingHandCursor)
        weekly_layout.addWidget(self.day_combo)

        self.weekly_time_edit = QTimeEdit()
        self.weekly_time_edit.setDisplayFormat("hh:mm AP")
        self.weekly_time_edit.setCursor(Qt.PointingHandCursor)
        weekly_layout.addWidget(self.weekly_time_edit)

        self.add_weekly_button = QPushButton("Add Weekly Backup")
        self.add_weekly_button.clicked.connect(self.add_weekly_backup)
        self.add_weekly_button.setCursor(Qt.PointingHandCursor)
        weekly_layout.addWidget(self.add_weekly_button)

        backup_types_layout.addWidget(weekly_group)

        # Monthly scheduling
        monthly_group = QGroupBox("Monthly Backup")
        monthly_layout = QVBoxLayout(monthly_group)

        self.day_of_month_combo = QComboBox()
        monthly_days = [ordinal(i) for i in range(1, 32)] + ["Last day"]
        self.day_of_month_combo.addItems(monthly_days)
        self.day_of_month_combo.setCursor(Qt.PointingHandCursor)
        monthly_layout.addWidget(self.day_of_month_combo)

        self.monthly_time_edit = QTimeEdit()
        self.monthly_time_edit.setDisplayFormat("hh:mm AP")
        self.monthly_time_edit.setCursor(Qt.PointingHandCursor)
        monthly_layout.addWidget(self.monthly_time_edit)

        self.add_monthly_button = QPushButton("Add Monthly Backup")
        self.add_monthly_button.clicked.connect(self.add_monthly_backup)
        self.add_monthly_button.setCursor(Qt.PointingHandCursor)
        monthly_layout.addWidget(self.add_monthly_button)

        backup_types_layout.addWidget(monthly_group)

        schedule_layout.addLayout(backup_types_layout)

        # Combined schedule list
        self.schedule_list = QListWidget()
        schedule_layout.addWidget(self.schedule_list, 1)  # Give it more vertical space

        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self.remove_backup)
        self.remove_button.setCursor(Qt.PointingHandCursor)
        schedule_layout.addWidget(self.remove_button)

        main_layout.addWidget(schedule_setup)

        # Right side: Calendar view
        calendar_widget = QWidget()
        calendar_layout = QVBoxLayout(calendar_widget)
        self.calendar_view = CustomCalendarWidget()
        self.calendar_view.setSelectionMode(QCalendarWidget.NoSelection)
        calendar_layout.addWidget(self.calendar_view)
        main_layout.addWidget(calendar_widget)

    def create_weekly_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        day_layout = QHBoxLayout()
        self.day_combo = QComboBox()
        self.day_combo.addItems(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])
        day_layout.addWidget(QLabel("Day of Week:"))
        day_layout.addWidget(self.day_combo)
        layout.addLayout(day_layout)

        time_layout = QHBoxLayout()
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("hh:mm AP")
        time_layout.addWidget(QLabel("Time:"))
        time_layout.addWidget(self.time_edit)
        layout.addLayout(time_layout)

        self.add_button = QPushButton("Add Weekly Backup")
        self.add_button.clicked.connect(self.add_weekly_backup)
        layout.addWidget(self.add_button)

        self.schedule_list = QListWidget()
        layout.addWidget(self.schedule_list)

        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self.remove_backup)
        layout.addWidget(self.remove_button)

        return widget

    def create_monthly_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        day_layout = QHBoxLayout()
        self.day_of_month_combo = QComboBox()
        monthly_days = [ordinal(i) for i in range(1, 32)] + ["Last day"]
        self.day_of_month_combo.addItems(monthly_days)
        day_layout.addWidget(QLabel("Day of Month:"))
        day_layout.addWidget(self.day_of_month_combo)
        layout.addLayout(day_layout)

        time_layout = QHBoxLayout()
        self.monthly_time_edit = QTimeEdit()
        self.monthly_time_edit.setDisplayFormat("hh:mm AP")
        time_layout.addWidget(QLabel("Time:"))
        time_layout.addWidget(self.monthly_time_edit)
        layout.addLayout(time_layout)

        self.add_monthly_button = QPushButton("Add Monthly Backup")
        self.add_monthly_button.clicked.connect(self.add_monthly_backup)
        layout.addWidget(self.add_monthly_button)

        self.monthly_schedule_list = QListWidget()
        layout.addWidget(self.monthly_schedule_list)

        self.remove_monthly_button = QPushButton("Remove Selected")
        self.remove_monthly_button.clicked.connect(self.remove_backup)
        layout.addWidget(self.remove_monthly_button)

        return widget

    def add_weekly_backup(self):
        day = self.day_combo.currentText()
        time = self.weekly_time_edit.time()
        if day not in self.schedule['weekly']:
            self.schedule['weekly'][day] = []
        if time not in self.schedule['weekly'][day]:
            self.schedule['weekly'][day].append(time)
            self.update_schedule_list()
            self.update_calendar_view()
            self.schedule_updated.emit(self.schedule)

    def add_monthly_backup(self):
        day = self.day_of_month_combo.currentText()
        time = self.monthly_time_edit.time()
        if day not in self.schedule['monthly']:
            self.schedule['monthly'][day] = []
        if time not in self.schedule['monthly'][day]:
            self.schedule['monthly'][day].append(time)
            self.update_schedule_list()
            self.update_calendar_view()
            self.schedule_updated.emit(self.schedule)

    def remove_backup(self):
        current_item = self.schedule_list.currentItem()
        if current_item:
            text = current_item.text()
            schedule_type, day, time_str = text.split(" - ")
            time = QTime.fromString(time_str, "hh:mm AP")
            self.schedule[schedule_type.lower()][day].remove(time)
            if not self.schedule[schedule_type.lower()][day]:
                del self.schedule[schedule_type.lower()][day]
            self.update_schedule_list()
            self.update_calendar_view()
            self.schedule_updated.emit(self.schedule)

    def update_schedule_list(self):
        self.schedule_list.clear()
        for schedule_type in ['weekly', 'monthly']:
            for day, times in self.schedule[schedule_type].items():
                for time in sorted(times):
                    item_text = f"{schedule_type.capitalize()} - {day} - {time.toString('hh:mm AP')}"
                    self.schedule_list.addItem(item_text)

    def update_calendar_view(self):
        self.calendar_view.update_schedule(self.schedule)

    def paintCell(self, painter, rect, date):
        super().paintCell(painter, rect, date)
        if self.is_backup_scheduled(date):
            painter.save()
            painter.setBrush(QColor(66, 133, 244, 100))  # Google Blue with transparency
            painter.setPen(Qt.NoPen)
            painter.drawRect(rect)
            painter.restore()

    def is_backup_scheduled(self, date):
        # Check weekly schedule
        day_name = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][date.dayOfWeek() - 1]
        if day_name in self.schedule['weekly'] and self.schedule['weekly'][day_name]:
            return True

        # Check monthly schedule
        day_of_month = ordinal(date.day())
        if day_of_month in self.schedule['monthly'] and self.schedule['monthly'][day_of_month]:
            return True

        # Check for last day of month
        if date.day() == date.daysInMonth() and "Last day" in self.schedule['monthly'] and self.schedule['monthly']["Last day"]:
            return True

        return False

    def update_ui_from_schedule(self):
        self.schedule_list.clear()
        for schedule_type in ['weekly', 'monthly']:
            for day, times in self.schedule[schedule_type].items():
                for time in times:
                    item_text = f"{schedule_type.capitalize()} - {day} - {time.toString('hh:mm AP')}"
                    self.schedule_list.addItem(item_text)
        logging.info(f"Updated UI from schedule: {self.schedule}")

    def set_schedule(self, schedule):
        self.schedule = schedule
        logging.info(f"Setting schedule in BackupScheduleCalendar: {self.schedule}")
        self.update_ui_from_schedule()
        self.update_calendar_view()

    def apply_styles(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #202124;
                color: #e8eaed;
                font-family: Arial, sans-serif;
            }
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                border: 1px solid #666;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }
            QComboBox, QTimeEdit {
                background-color: #333;
                border: 1px solid #666;
                border-radius: 5px;
                padding: 5px;
                min-width: 8em;
            }
            QPushButton {
                background-color: #4285F4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 5px;
                font-size: 14px;
            }
            QComboBox {
                background-color: #333;
                color: #e8eaed;
                border: 1px solid #666;
                border-radius: 5px;
                padding: 5px;
                min-width: 8em;
            }
            QComboBox:hover {
                border-color: #8ab4f8;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 20px;
                border-left: none;
                background: transparent;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #666;
                background-color: #333;
                selection-background-color: #4285F4;
            }
            QPushButton {
                background-color: #4285F4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 5px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #5294FF;
            }
            QPushButton:pressed {
                background-color: #3275E4;
            }
            QListWidget {
                background-color: #333;
                border: 1px solid #666;
                border-radius: 5px;
                outline: 0;
            }
            QListWidget::item {
                padding: 5px;
            }
            QListWidget::item:hover {
                background-color: #3c4043;
            }
            QListWidget::item:selected {
                background-color: #444;
                color: #8ab4f8;
                border: none;
            }
            QListWidget::item:focus {
                border: none;
                outline: none;
            }
            QWidget:disabled {
                color: #888;
            }
            QComboBox:disabled, QTimeEdit:disabled {
                background-color: #555;
                color: #888;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
            QListWidget:disabled {
                background-color: #555;
                color: #888;
            }
            QTimeEdit:hover {
                border-color: #8ab4f8;
            }
        """)

class CustomCalendarWidget(QCalendarWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.schedule = {'weekly': {}, 'monthly': {}}
        self.initUI()

    def initUI(self):
        # Set the color for weekends to be the same as weekdays
        weekday_color = QColor('#e8eaed')
        weekend_format = QTextCharFormat()
        weekend_format.setForeground(weekday_color)
        self.setWeekdayTextFormat(Qt.Saturday, weekend_format)
        self.setWeekdayTextFormat(Qt.Sunday, weekend_format)

        # Create custom navigation bar
        navigation_bar = QWidget(self)
        nav_layout = QHBoxLayout(navigation_bar)

        self.prev_button = CustomArrowButton('left')
        self.next_button = CustomArrowButton('right')
        self.month_year_label = QLabel()

        nav_layout.addWidget(self.prev_button)
        nav_layout.addStretch()
        nav_layout.addWidget(self.month_year_label)
        nav_layout.addStretch()
        nav_layout.addWidget(self.next_button)

        # Replace the default navigation bar
        old_nav_bar = self.findChild(QWidget, "qt_calendar_navigationbar")
        if old_nav_bar:
            layout = self.layout()
            layout.replaceWidget(old_nav_bar, navigation_bar)

        # Connect signals
        self.prev_button.clicked.connect(self.showPreviousMonth)
        self.next_button.clicked.connect(self.showNextMonth)

        # Update month/year label
        self.updateMonthYearLabel()

        # Set stylesheet
        self.setStyleSheet("""
            QCalendarWidget {
                background-color: #333;
                color: #e8eaed;
            }
            QCalendarWidget QTableView {
                alternate-background-color: #3a3a3a;
                background-color: #333;
            }
            QCalendarWidget QAbstractItemView:enabled {
                color: #e8eaed;
            }
            QCalendarWidget QAbstractItemView:disabled {
                color: #666;
            }
            QLabel {
                color: #e8eaed;
                font-size: 14px;
            }
        """)

    def updateMonthYearLabel(self):
        date = self.selectedDate()
        self.month_year_label.setText(date.toString("MMMM yyyy"))

    def showPreviousMonth(self):
        self.setSelectedDate(self.selectedDate().addMonths(-1))
        self.updateMonthYearLabel()

    def showNextMonth(self):
        self.setSelectedDate(self.selectedDate().addMonths(1))
        self.updateMonthYearLabel()

    def paintCell(self, painter, rect, date):
        super().paintCell(painter, rect, date)
        if self.is_backup_scheduled(date):
            painter.save()
            painter.setBrush(QColor(66, 133, 244, 100))  # Google Blue with transparency
            painter.setPen(Qt.NoPen)
            painter.drawRect(rect)
            painter.restore()

    def is_backup_scheduled(self, date):
        # Check weekly schedule
        day_name = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][date.dayOfWeek() - 1]
        if day_name in self.schedule['weekly'] and self.schedule['weekly'][day_name]:
            return True

        # Check monthly schedule
        day_of_month = ordinal(date.day())
        if day_of_month in self.schedule['monthly'] and self.schedule['monthly'][day_of_month]:
            return True

        # Check for last day of month
        if date.day() == date.daysInMonth() and "Last day" in self.schedule['monthly'] and self.schedule['monthly']["Last day"]:
            return True

        return False

    def update_schedule(self, schedule):
        self.schedule = schedule
        self.updateCells()

class CustomArrowButton(QToolButton):
    def __init__(self, direction, parent=None):
        super().__init__(parent)
        self.direction = direction
        self.setFixedSize(24, 24)
        self.normal_color = QColor('#4285F4')  # Google Blue
        self.hover_color = QColor('#5294FF')   # Lighter Blue for hover
        self.current_color = self.normal_color
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, event):
        self.current_color = self.hover_color
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.current_color = self.normal_color
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw circle with current color
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.current_color)
        painter.drawEllipse(QRect(2, 2, 20, 20))

        # Draw white arrow
        painter.setPen(Qt.white)
        painter.setBrush(Qt.white)
        if self.direction == 'left':
            points = [QPoint(14, 6), QPoint(14, 18), QPoint(8, 12)]
        else:
            points = [QPoint(10, 6), QPoint(10, 18), QPoint(16, 12)]
        painter.drawPolygon(*points)
# ---------------

class FileItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if option.state & QStyle.State_Selected:
            option.palette.setColor(QPalette.Highlight, QColor("#4285F4"))
            option.palette.setColor(QPalette.HighlightedText, QColor("#e8eaed"))
        super().paint(painter, option, index)

class FileExplorerPanel(QWidget):
    def __init__(self, json_directory):
        super().__init__()
        self.json_directory = json_directory
        self.create_arrow_icons()
        self.search_history = []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)  # Add some spacing between widgets

        # Add search box
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search for file or folder...")
        self.search_box.returnPressed.connect(self.search_item)
        layout.addWidget(self.search_box)

        # Main splitter
        self.main_splitter = QSplitter(Qt.Vertical)
        layout.addWidget(self.main_splitter)

        # Tree view
        self.tree_view = QTreeView()
        self.main_splitter.addWidget(self.tree_view)

        # Results panel
        self.results_panel = QTreeWidget()
        self.results_panel.setHeaderHidden(True)
        self.results_panel.itemClicked.connect(self.navigate_to_result)
        self.results_panel.setVisible(False)
        self.main_splitter.addWidget(self.results_panel)

        self.model = FileSystemModel()
        self.tree_view.setModel(self.model)

        # Hide all columns except the file/directory names
        for i in range(1, self.model.columnCount()):
            self.tree_view.hideColumn(i)

        self.tree_view.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree_view.setAnimated(True)
        self.tree_view.setIndentation(20)
        self.tree_view.setSortingEnabled(True)

        # Set custom item delegate
        self.tree_view.setItemDelegate(FileItemDelegate())

        # Update TreeView to be read-only
        self.tree_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree_view.doubleClicked.connect(self.show_metadata)

        self.set_styles()

        self.load_data()

    def set_styles(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #333;  /* Match the background color of other panels */
                color: #e8eaed;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QLineEdit {
                background-color: #303134;
                border: 1px solid #5f6368;
                border-radius: 4px;
                padding: 8px;
                font-size: 14px;
                color: #e8eaed;
            }
            QLineEdit:focus {
                border-color: #8ab4f8;
            }
            QTreeView, QTreeWidget {
                background-color: #333;  /* Match the background color */
                border: none;
                font-size: 13px;
                outline: 0;
            }
            QTreeView::item, QTreeWidget::item {
                padding: 6px 0;
            }
            QTreeView::item:hover, QTreeWidget::item:hover {
                background-color: #3c4043;
            }
            QTreeView::item:selected, QTreeWidget::item:selected {
                background-color: #444;  /* Slightly lighter gray for highlighted items */
                color: #8ab4f8;
            }
            QTreeView::item:selected:active, QTreeWidget::item:selected:active,
            QTreeView::item:selected:!active, QTreeWidget::item:selected:!active {
                background-color: #444;  /* Consistent highlight color */
                color: #8ab4f8;
            }
            QTreeView::branch:has-siblings:!adjoins-item {
                border-image: url(vline.png) 0;
            }
            QTreeView::branch:has-siblings:adjoins-item {
                border-image: url(branch-more.png) 0;
            }
            QTreeView::branch:!has-children:!has-siblings:adjoins-item {
                border-image: url(branch-end.png) 0;
            }
            QTreeView::branch:has-children:!has-siblings:closed,
            QTreeView::branch:closed:has-children:has-siblings {
                border-image: none;
                image: url(branch-closed.png);
            }
            QTreeView::branch:open:has-children:!has-siblings,
            QTreeView::branch:open:has-children:has-siblings {
                border-image: none;
                image: url(branch-open.png);
            }
            QHeaderView::section {
                background-color: #303134;
                color: #e8eaed;
                padding: 8px;
                border: none;
                font-weight: bold;
            }
            QScrollBar:vertical {
                border: none;
                background: #202124;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #5f6368;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                border: none;
                background: #202124;
                height: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:horizontal {
                background: #5f6368;
                min-width: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            QSplitter::handle {
                background-color: #666;
            }
            QFrame[frameShape="4"] {  /* HLine */
                color: #666;
                height: 1px;
            }
            QSplitter::handle {
                background-color: #666;
                height: 1px;
            }
        """)

        # Additional style to remove focus border and add panel border
        self.setStyleSheet(self.styleSheet() + """
            FileExplorerPanel {
                border: 1px solid #666;
                border-radius: 5px;
            }
            QTreeView::item:focus, QTreeWidget::item:focus {
                border: none;
                outline: none;
            }
        """)

    def show_metadata(self, index):
        item = self.model.itemFromIndex(index)
        metadata = item.data(Qt.UserRole)
        if metadata:
            dialog = MetadataDialog(metadata, self)
            dialog.exec_()

    def search_item(self):
        search_text = self.search_box.text()
        if not search_text:
            return

        # Attempt exact match first
        exact_match = self.find_exact_match(search_text)
        if exact_match.isValid():
            self.navigate_to_index(exact_match)
            self.add_to_search_history(search_text, [self.get_full_path(self.model.itemFromIndex(exact_match))], 1, 1)
            return

        # If no exact match, perform partial match
        partial_matches = self.find_partial_matches(search_text)
        if partial_matches:
            self.show_partial_matches(search_text, partial_matches)
        else:
            self.add_to_search_history(search_text, [], 0, 0)
            self.results_panel.clear()
            self.results_panel.addTopLevelItem(QTreeWidgetItem(["No matching items found."]))
            self.results_panel.setVisible(True)

    def find_exact_match(self, search_text):
        def search_recursive(parent):
            for row in range(parent.rowCount()):
                item = parent.child(row)
                full_path = self.get_full_path(item)
                if full_path.lower() == search_text.lower():
                    return self.model.indexFromItem(item)
                if item.hasChildren():
                    result = search_recursive(item)
                    if result.isValid():
                        return result
            return QModelIndex()

        return search_recursive(self.model.invisibleRootItem())

    def find_partial_matches(self, search_text):
        matches = []
        folders_searched = set()
        files_searched = 0

        def search_recursive(parent):
            nonlocal files_searched
            for row in range(parent.rowCount()):
                item = parent.child(row)
                full_path = self.get_full_path(item)
                if item.hasChildren():
                    folders_searched.add(full_path)
                else:
                    files_searched += 1
                if search_text.lower() in full_path.lower():
                    matches.append((full_path, self.model.indexFromItem(item)))
                if item.hasChildren():
                    search_recursive(item)

        search_recursive(self.model.invisibleRootItem())
        return matches, len(folders_searched), files_searched

    def get_full_path(self, item):
        path = []
        while item:
            path.insert(0, item.text())
            item = item.parent()
        return '/'.join(path)

    def show_partial_matches(self, search_text, match_data):
        matches, folders_searched, files_searched = match_data
        self.add_to_search_history(search_text, [m[0] for m in matches], folders_searched, files_searched)
        self.update_results_panel()

    def add_to_search_history(self, search_text, matches, folders_searched, files_searched):
        result = {
            'search_text': search_text,
            'matches': matches,
            'folders_searched': folders_searched,
            'files_searched': files_searched,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.search_history.insert(0, result)  # Add new result to the beginning of the list

    def update_results_panel(self):
        self.results_panel.clear()
        for result in self.search_history:
            summary = f"Showing {len(result['matches'])} results found in {result['folders_searched']} folders searched ({result['files_searched']} files)"
            root_item = QTreeWidgetItem([f"{result['search_text']} - {summary}"])
            root_item.setData(0, Qt.UserRole, result)
            root_item.setForeground(0, QColor('#8ab4f8'))  # Highlight color for search summaries
            for match in result['matches']:
                child_item = QTreeWidgetItem([match])
                root_item.addChild(child_item)
            self.results_panel.addTopLevelItem(root_item)
        self.results_panel.setVisible(True)

    def navigate_to_result(self, item, column):
        if item.parent() is None:  # This is a root item (search summary)
            item.setExpanded(not item.isExpanded())
        else:  # This is a child item (actual result)
            full_path = item.text(0)
            for _, index in self.find_partial_matches(full_path)[0]:
                if self.get_full_path(self.model.itemFromIndex(index)) == full_path:
                    self.navigate_to_index(index)
                    break

    def navigate_to_index(self, index):
        self.tree_view.setCurrentIndex(index)
        self.tree_view.scrollTo(index, QAbstractItemView.PositionAtCenter)
        self.expand_to_index(index)

    def expand_to_index(self, index):
        parent = index.parent()
        if parent.isValid():
            self.expand_to_index(parent)
        self.tree_view.expand(index)

    def create_arrow_icons(self):
        # Create branch-closed icon
        branch_closed = QPixmap(16, 16)
        branch_closed.fill(Qt.transparent)
        painter = QPainter(branch_closed)
        painter.setBrush(QColor('#e8eaed'))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPoint(4, 4), QPoint(12, 8), QPoint(4, 12))
        painter.end()
        branch_closed.save('branch-closed.png')

        # Create branch-open icon
        branch_open = QPixmap(16, 16)
        branch_open.fill(Qt.transparent)
        painter = QPainter(branch_open)
        painter.setBrush(QColor('#e8eaed'))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPoint(4, 4), QPoint(12, 4), QPoint(8, 12))
        painter.end()
        branch_open.save('branch-open.png')

        # Create vline icon
        vline = QPixmap(16, 16)
        vline.fill(Qt.transparent)
        painter = QPainter(vline)
        painter.setPen(QColor('#5f6368'))
        painter.drawLine(8, 0, 8, 16)
        painter.end()
        vline.save('vline.png')

        # Create branch-more icon
        branch_more = QPixmap(16, 16)
        branch_more.fill(Qt.transparent)
        painter = QPainter(branch_more)
        painter.setPen(QColor('#5f6368'))
        painter.drawLine(8, 0, 8, 8)
        painter.drawLine(8, 8, 16, 8)
        painter.end()
        branch_more.save('branch-more.png')

        # Create branch-end icon
        branch_end = QPixmap(16, 16)
        branch_end.fill(Qt.transparent)
        painter = QPainter(branch_end)
        painter.setPen(QColor('#5f6368'))
        painter.drawLine(8, 0, 8, 8)
        painter.drawLine(8, 8, 16, 8)
        painter.end()
        branch_end.save('branch-end.png')

    def add_file(self, path, metadata):
        parts = path.strip('/').split('/')
        parent = self.model.invisibleRootItem()

        for i, part in enumerate(parts):
            if i == len(parts) - 1:  # This is a file
                item = QStandardItem(part)
                item.setData(metadata, Qt.UserRole)
                item.setIcon(self.get_file_icon(part))
                parent.appendRow(item)
            else:  # This is a directory
                found = False
                for row in range(parent.rowCount()):
                    if parent.child(row).text() == part:
                        parent = parent.child(row)
                        found = True
                        break
                if not found:
                    new_dir = QStandardItem(part)
                    new_dir.setIcon(self.get_folder_icon())
                    parent.appendRow(new_dir)
                    parent = new_dir

    def load_data(self):
        # Find the most recent JSON file
        json_files = [f for f in os.listdir(self.json_directory) if f.startswith('file_metadata_') and f.endswith('.json')]
        if not json_files:
            print("No file metadata JSON files found.")
            return

        latest_file = max(json_files, key=lambda f: datetime.strptime(f, 'file_metadata_%Y%m%d_%H%M%S.json'))
        json_path = os.path.join(self.json_directory, latest_file)

        with open(json_path, 'r') as file:
            data = json.load(file)
            for item in data:
                self.model.add_file(item['ClientFullNameAndPathAsPosix'], item)

class FileSystemModel(QStandardItemModel):
    def __init__(self):
        super().__init__()
        self.setHorizontalHeaderLabels(['Name'])
        self.root = self.invisibleRootItem()

    def add_file(self, path, metadata):
        parts = path.strip('/').split('/')
        parent = self.root

        for i, part in enumerate(parts):
            if i == len(parts) - 1:  # This is a file
                item = QStandardItem(part)
                item.setData(metadata, Qt.UserRole)
                item.setIcon(self.get_file_icon(part))
                parent.appendRow(item)
            else:  # This is a directory
                found = False
                for row in range(parent.rowCount()):
                    if parent.child(row).text() == part:
                        parent = parent.child(row)
                        found = True
                        break
                if not found:
                    new_dir = QStandardItem(part)
                    new_dir.setIcon(self.get_folder_icon())
                    parent.appendRow(new_dir)
                    parent = new_dir

    def get_file_icon(self, filename):
        # Implement logic to return appropriate file icon based on file type
        # You can use QIcon.fromTheme() or create custom icons
        return QIcon.fromTheme("text-x-generic")

    def get_folder_icon(self):
        # Return a folder icon
        return QIcon.fromTheme("folder")

class MetadataDialog(QDialog):
    def __init__(self, metadata, parent=None):
        super().__init__(parent)
        self.setWindowTitle("File Metadata")
        self.setMinimumSize(500, 400)
        self.setup_ui(metadata)

    def setup_ui(self, metadata):
        layout = QVBoxLayout(self)

        # Metadata display
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #303134;
                color: #e8eaed;
                border: 1px solid #5f6368;
                border-radius: 4px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }
        """)
        formatted_json = json.dumps(metadata, indent=2)
        self.text_edit.setText(formatted_json)
        layout.addWidget(self.text_edit)

        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #4285F4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #5294FF;
            }
            QPushButton:pressed {
                background-color: #3275E4;
            }
        """)
        layout.addWidget(close_button, alignment=Qt.AlignRight)

        self.setStyleSheet("""
            QDialog {
                background-color: #202124;
                color: #e8eaed;
            }
        """)

class ThemeManager(QObject):
    theme_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.themes = {
            "Dark": self.dark_theme(),
            "Light": self.light_theme(),
            "Cyberpunk": self.cyberpunk_theme(),
            "Forest": self.forest_theme()
        }
        self.current_theme = "Dark"

    def get_theme(self, theme_name):
        return self.themes.get(theme_name, self.themes["Dark"])

    def set_theme(self, theme_name):
        if theme_name in self.themes:
            self.current_theme = theme_name
            self.theme_changed.emit(theme_name)

    def dark_theme(self):
        return {
            "app_background": "#202124",
            "text_primary": "#e8eaed",
            "text_secondary": "#9aa0a6",
            "accent_color": "#4285F4",
            "accent_color_hover": "#5294FF",
            "accent_color_pressed": "#3275E4",
            "panel_background": "#333",
            "panel_border": "#666",
            "input_background": "#303134",
            "input_border": "#5f6368",
            "input_border_focus": "#8ab4f8",
            "button_text": "white",
            "list_item_hover": "#3c4043",
            "list_item_selected": "#444",
            "scroll_background": "#202124",
            "scroll_handle": "#5f6368",
            "scroll_handle_hover": "#6a6a6a",
            "header_background": "#171717",
            "divider_color": "#666",
            "stylesheet": """
                QWidget {
                    background-color: #202124;
                    color: #e8eaed;
                    font-family: 'Segoe UI', Arial, sans-serif;
                }
                QPushButton {
                    background-color: #4285F4;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 5px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #5294FF;
                }
                QPushButton:pressed {
                    background-color: #3275E4;
                }
                QLineEdit, QTextEdit, QPlainTextEdit {
                    background-color: #303134;
                    border: 1px solid #5f6368;
                    border-radius: 4px;
                    padding: 8px;
                    color: #e8eaed;
                }
                QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
                    border-color: #8ab4f8;
                }
                QListWidget, QTreeWidget, QTreeView {
                    background-color: #333;
                    border: 1px solid #666;
                    border-radius: 5px;
                }
                QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover {
                    background-color: #3c4043;
                }
                QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {
                    background-color: #444;
                    color: #8ab4f8;
                }
                QScrollBar:vertical {
                    border: none;
                    background: #202124;
                    width: 10px;
                    margin: 0px;
                }
                QScrollBar::handle:vertical {
                    background: #5f6368;
                    min-height: 30px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #6a6a6a;
                }
                QComboBox {
                    background-color: #303134;
                    border: 1px solid #5f6368;
                    border-radius: 4px;
                    padding: 5px;
                    color: #e8eaed;
                }
                QComboBox:hover {
                    border-color: #8ab4f8;
                }
                QComboBox::drop-down {
                    subcontrol-origin: padding;
                    subcontrol-position: top right;
                    width: 30px;
                    border-left: 1px solid #5f6368;
                    border-top-right-radius: 4px;
                    border-bottom-right-radius: 4px;
                }
                QComboBox::down-arrow {
                    image: url(down_arrow_dark.png);
                }
            """
        }

    def light_theme(self):
        return {
            "app_background": "#f8f9fa",
            "text_primary": "#202124",
            "text_secondary": "#5f6368",
            "accent_color": "#1a73e8",
            "accent_color_hover": "#1967d2",
            "accent_color_pressed": "#185abc",
            "panel_background": "#ffffff",
            "panel_border": "#dadce0",
            "input_background": "#ffffff",
            "input_border": "#dadce0",
            "input_border_focus": "#1a73e8",
            "button_text": "white",
            "list_item_hover": "#f1f3f4",
            "list_item_selected": "#e8f0fe",
            "scroll_background": "#f1f3f4",
            "scroll_handle": "#dadce0",
            "scroll_handle_hover": "#bdc1c6",
            "header_background": "#f1f3f4",
            "divider_color": "#dadce0",
            "stylesheet": """
                QWidget {
                    background-color: #f8f9fa;
                    color: #202124;
                    font-family: 'Segoe UI', Arial, sans-serif;
                }
                QPushButton {
                    background-color: #1a73e8;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 5px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #1967d2;
                }
                QPushButton:pressed {
                    background-color: #185abc;
                }
                QLineEdit, QTextEdit, QPlainTextEdit {
                    background-color: #ffffff;
                    border: 1px solid #dadce0;
                    border-radius: 4px;
                    padding: 8px;
                    color: #202124;
                }
                QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
                    border-color: #1a73e8;
                }
                QListWidget, QTreeWidget, QTreeView {
                    background-color: #ffffff;
                    border: 1px solid #dadce0;
                    border-radius: 5px;
                }
                QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover {
                    background-color: #f1f3f4;
                }
                QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {
                    background-color: #e8f0fe;
                    color: #1a73e8;
                }
                QScrollBar:vertical {
                    border: none;
                    background: #f1f3f4;
                    width: 10px;
                    margin: 0px;
                }
                QScrollBar::handle:vertical {
                    background: #dadce0;
                    min-height: 30px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #bdc1c6;
                }
                QComboBox {
                    background-color: #ffffff;
                    border: 1px solid #dadce0;
                    border-radius: 4px;
                    padding: 5px;
                    color: #202124;
                }
                QComboBox:hover {
                    border-color: #1a73e8;
                }
                QComboBox::drop-down {
                    subcontrol-origin: padding;
                    subcontrol-position: top right;
                    width: 30px;
                    border-left: 1px solid #dadce0;
                    border-top-right-radius: 4px;
                    border-bottom-right-radius: 4px;
                }
                QComboBox::down-arrow {
                    image: url(down_arrow_light.png);
                }
            """
        }

    def cyberpunk_theme(self):
        return {
            "app_background": "#0a0a1e",
            "text_primary": "#00ff00",
            "text_secondary": "#00cccc",
            "accent_color": "#ff00ff",
            "accent_color_hover": "#ff33ff",
            "accent_color_pressed": "#cc00cc",
            "panel_background": "#1a1a3e",
            "panel_border": "#00ffff",
            "input_background": "#0f0f2f",
            "input_border": "#00ffff",
            "input_border_focus": "#ff00ff",
            "button_text": "#0a0a1e",
            "list_item_hover": "#2a2a5e",
            "list_item_selected": "#3a3a7e",
            "scroll_background": "#1a1a3e",
            "scroll_handle": "#00ffff",
            "scroll_handle_hover": "#ff00ff",
            "header_background": "#2a2a5e",
            "divider_color": "#00ffff",
            "stylesheet": """
                QWidget {
                    background-color: #0a0a1e;
                    color: #00ff00;
                    font-family: 'Blade Runner', 'Orbitron', sans-serif;
                }
                QPushButton {
                    background-color: #ff00ff;
                    color: #0a0a1e;
                    border: 2px solid #00ffff;
                    padding: 8px 16px;
                    border-radius: 0px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #ff33ff;
                    border-color: #33ffff;
                }
                QPushButton:pressed {
                    background-color: #cc00cc;
                    border-color: #00cccc;
                }
                QLineEdit, QTextEdit, QPlainTextEdit {
                    background-color: #0f0f2f;
                    border: 2px solid #00ffff;
                    border-radius: 0px;
                    padding: 8px;
                    color: #00ff00;
                    font-family: 'Courier New', monospace;
                }
                QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
                    border-color: #ff00ff;
                }
                QListWidget, QTreeWidget, QTreeView {
                    background-color: #1a1a3e;
                    border: 2px solid #00ffff;
                    border-radius: 0px;
                }
                QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover {
                    background-color: #2a2a5e;
                }
                QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {
                    background-color: #3a3a7e;
                    color: #ff00ff;
                }
                QScrollBar:vertical {
                    border: none;
                    background: #1a1a3e;
                    width: 10px;
                    margin: 0px;
                }
                QScrollBar::handle:vertical {
                    background: #00ffff;
                    min-height: 30px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #ff00ff;
                }
                QComboBox {
                    background-color: #0f0f2f;
                    border: 2px solid #00ffff;
                    border-radius: 0px;
                    padding: 5px;
                    color: #00ff00;
                }
                QComboBox:hover {
                    border-color: #ff00ff;
                }
                QComboBox::drop-down {
                    subcontrol-origin: padding;
                    subcontrol-position: top right;
                    width: 30px;
                    border-left: 2px solid #00ffff;
                }
                QComboBox::down-arrow {
                    image: url(down_arrow_cyberpunk.png);
                }
            """
        }
        
    def forest_theme(self):
        return {
            "app_background": "#2c4f35",
            "text_primary": "#e0e8d5",
            "text_secondary": "#b8c5a6",
            "accent_color": "#8ab06a",
            "accent_color_hover": "#9ac57a",
            "accent_color_pressed": "#7a9f5a",
            "panel_background": "#3a5a40",
            "panel_border": "#6b8e4e",
            "input_background": "#2c4f35",
            "input_border": "#6b8e4e",
            "input_border_focus": "#8ab06a",
            "button_text": "#2c4f35",
            "list_item_hover": "#4a6a50",
            "list_item_selected": "#5a7a60",
            "scroll_background": "#2c4f35",
            "scroll_handle": "#6b8e4e",
            "scroll_handle_hover": "#8ab06a",
            "header_background": "#4a6a50",
            "divider_color": "#6b8e4e",
            "stylesheet": """
                QWidget {
                    background-color: #2c4f35;
                    color: #e0e8d5;
                    font-family: 'Verdana', sans-serif;
                }
                QPushButton {
                    background-color: #8ab06a;
                    color: #2c4f35;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 5px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #9ac57a;
                }
                QPushButton:pressed {
                    background-color: #7a9f5a;
                }
                QLineEdit, QTextEdit, QPlainTextEdit {
                    background-color: #2c4f35;
                    border: 1px solid #6b8e4e;
                    border-radius: 4px;
                    padding: 8px;
                    color: #e0e8d5;
                }
                QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
                    border-color: #8ab06a;
                }
                QListWidget, QTreeWidget, QTreeView {
                    background-color: #3a5a40;
                    border: 1px solid #6b8e4e;
                    border-radius: 5px;
                }
                QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover {
                    background-color: #4a6a50;
                }
                QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {
                    background-color: #5a7a60;
                    color: #e0e8d5;
                }
                QScrollBar:vertical {
                    border: none;
                    background: #2c4f35;
                    width: 10px;
                    margin: 0px;
                }
                QScrollBar::handle:vertical {
                    background: #6b8e4e;
                    min-height: 30px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #8ab06a;
                }
                QComboBox {
                    background-color: #3a5a40;
                    border: 1px solid #6b8e4e;
                    border-radius: 4px;
                    padding: 5px;
                    color: #e0e8d5;
                }
                QComboBox:hover {
                    border-color: #8ab06a;
                }
                QComboBox::drop-down {
                    subcontrol-origin: padding;
                    subcontrol-position: top right;
                    width: 30px;
                    border-left: 1px solid #6b8e4e;
                    border-top-right-radius: 4px;
                    border-bottom-right-radius: 4px;
                }
                QComboBox::down-arrow {
                    image: url(down_arrow_forest.png);
                }
            """
        }

if __name__ == '__main__':
    app = QApplication([])
    window = StormcloudApp()
    window.show()
    app.exec_()