import calendar
import time
from time import sleep
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Set
import argparse
import pathlib
import os
import json
import traceback

import win32file
import win32gui
import win32con
import win32api

import sqlite3
import yaml

import threading
import logging

# import sslkeylog

import keepalive_utils
import backup_utils
import logging_utils
import reconfigure_utils
import network_utils

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                           QPushButton, QCheckBox, QApplication)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon, QPixmap

from infi.systray import SysTrayIcon   # pip install infi.systray

from client_db_utils import get_or_create_hash_db

# App Device History tracking using SQLite
from history_db import (
    init_db, Operation, FileRecord, 
    InitiationSource, OperationStatus
)

ACTION_TIMER = 90

class BackupState:
    """Track backup state to prevent overlaps and handle concurrent schedules"""
    def __init__(self):
        self.backup_in_progress = False
        self.backup_start_time = None
        self.last_successful_backup = None
        self.current_backup_source = None  # 'weekly', 'monthly', or None
        self._lock = threading.Lock()
        logging.info("Initialized new BackupState instance")

    def start_backup(self, source):
        """
        Attempt to start a new backup process.
        Returns True if backup can start, False if another backup is in progress.
        """
        with self._lock:
            if self.backup_in_progress:
                logging.warning(
                    f"Cannot start {source} backup - another backup is already in progress "
                    f"(started at {self.backup_start_time}, "
                    f"running for {self.get_backup_duration():.1f} seconds)"
                )
                return False

            self.backup_in_progress = True
            self.backup_start_time = datetime.now()
            self.current_backup_source = source
            logging.info(
                f"Starting {source} backup at {self.backup_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return True

    def complete_backup(self, success=True):
        """
        Mark the current backup as complete.
        Updates last_successful_backup if the backup was successful.
        """
        with self._lock:
            duration = self.get_backup_duration()
            if success:
                self.last_successful_backup = self.backup_start_time
                logging.info(
                    f"Successfully completed {self.current_backup_source} backup. "
                    f"Duration: {duration:.1f} seconds. "
                    f"Started at: {self.backup_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
                )
            else:
                logging.error(
                    f"Backup failed for {self.current_backup_source}. "
                    f"Duration: {duration:.1f} seconds. "
                    f"Started at: {self.backup_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
                )

            self.backup_in_progress = False
            self.backup_start_time = None
            old_source = self.current_backup_source
            self.current_backup_source = None
            
            logging.debug(
                f"Reset backup state after {old_source} backup. "
                f"Last successful backup: {self.last_successful_backup.strftime('%Y-%m-%d %H:%M:%S') if self.last_successful_backup else 'None'}"
            )

    def get_backup_duration(self):
        """
        Calculate the duration of the current backup in seconds.
        Returns 0 if no backup is in progress.
        """
        if self.backup_in_progress and self.backup_start_time:
            duration = (datetime.now() - self.backup_start_time).total_seconds()
            logging.debug(
                f"Current {self.current_backup_source} backup running for {duration:.1f} seconds"
            )
            return duration
        return 0

    def get_state_summary(self):
        """
        Get a human-readable summary of the current backup state.
        Useful for debugging and monitoring.
        """
        state = {
            "backup_in_progress": self.backup_in_progress,
            "current_source": self.current_backup_source,
            "start_time": self.backup_start_time.strftime('%Y-%m-%d %H:%M:%S') if self.backup_start_time else None,
            "duration": f"{self.get_backup_duration():.1f}s" if self.backup_in_progress else "0s",
            "last_successful": self.last_successful_backup.strftime('%Y-%m-%d %H:%M:%S') if self.last_successful_backup else None
        }
        logging.debug(f"Backup state summary: {json.dumps(state, indent=2)}")
        return state

    def check_timeout(self, timeout_seconds=3600):
        """
        Check if the current backup has exceeded the timeout threshold.
        Returns True if backup has timed out, False otherwise.
        """
        if not self.backup_in_progress:
            return False

        duration = self.get_backup_duration()
        if duration > timeout_seconds:
            logging.error(
                f"Backup timeout detected for {self.current_backup_source} backup. "
                f"Duration: {duration:.1f} seconds exceeds timeout of {timeout_seconds} seconds. "
                f"Started at: {self.backup_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return True
            
        return False

class BackupResult:
    """Represent the detailed result of a backup operation"""
    BACKED_UP = "backed_up"  # File was backed up successfully
    UNCHANGED = "unchanged"  # File was unchanged, no backup needed
    FAILED = "failed"    # Backup attempt failed
    
class InitiationSource(Enum):
    REALTIME = "Realtime"
    SCHEDULED = "Scheduled"
    USER = "User-Initiated"

class OperationStatus(Enum):
    SUCCESS = "Success"
    FAILED = "Failed"
    IN_PROGRESS = "In Progress"

@dataclass
class FileOperationRecord:
    filepath: str
    timestamp: datetime
    status: OperationStatus
    error_message: Optional[str] = None

@dataclass
class HistoryEvent:
    timestamp: datetime
    source: InitiationSource
    status: OperationStatus
    operation_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    files: List[FileOperationRecord] = field(default_factory=list)
    error_message: Optional[str] = None

class CoreHistoryManager:
    def __init__(self, install_path):
        self.db_path = f"{install_path}/history/history.db"
        init_db(self.db_path)
        self.active_operations = {}

    def start_operation(self, source: InitiationSource) -> str:
        # Create operation with standardized type
        operation = Operation(
            operation_id=datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
            timestamp=datetime.now(),
            source=source,
            status=OperationStatus.IN_PROGRESS,
            operation_type='backup',  # Standardized operation type
            user_email='System'  # Explicitly set system attribution
        )
        self.active_operations[operation.operation_id] = operation
        self._save_operation(operation)
        return operation.operation_id
    
    def add_file_record(self, operation_id: str, filepath: str,
                       status: OperationStatus, error_message: Optional[str] = None):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO file_records 
                    (operation_id, filepath, timestamp, status, error_message)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    operation_id,
                    filepath,
                    datetime.now().isoformat(),
                    status.value,
                    error_message
                ))
                conn.execute("""
                    UPDATE operations SET last_modified = ? 
                    WHERE operation_id = ?
                """, (datetime.now().isoformat(), operation_id))
        except sqlite3.Error as e:
            logging.error(f"Failed to add file record: {e}")

    def complete_operation(self, operation_id: str, final_status: OperationStatus,
                         error_message: Optional[str] = None):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE operations 
                    SET status = ?, error_message = ?, last_modified = ?
                    WHERE operation_id = ?
                """, (
                    final_status.value, 
                    error_message,
                    datetime.now().isoformat(),
                    operation_id
                ))

            if operation_id in self.active_operations:
                del self.active_operations[operation_id]

        except sqlite3.Error as e:
            logging.error(f"Failed to complete operation: {e}")

    def _save_operation(self, operation: Operation):
        """Save operation with all required fields"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO operations
                    (operation_id, timestamp, source, status, operation_type, 
                     user_email, error_message, last_modified)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    operation.operation_id,
                    operation.timestamp.isoformat(),
                    operation.source.value,
                    operation.status.value,
                    operation.operation_type,
                    operation.user_email,
                    operation.error_message,
                    datetime.now().isoformat()
                ))
        except sqlite3.Error as e:
            logging.error(f"Database error saving operation: {e}")

class RestoreChunkManager:
    """Manages chunked downloads with resume capability"""
    
    def __init__(self, file_path: str, api_key: str, agent_id: str,
                 chunk_size: int = 16 * 1024 * 1024):  # 16MB default
        self.file_path = file_path
        self.api_key = api_key
        self.agent_id = agent_id
        self.chunk_size = chunk_size
        self.temp_dir = os.path.join(
            os.path.dirname(file_path), 
            f'.temp_{os.path.basename(file_path)}'
        )
        self.progress_file = f"{self.temp_dir}.progress"
        self.downloaded_chunks = set()
        self.total_size = None
        self._load_progress()
        
    def _load_progress(self):
        """Load existing progress if any"""
        if os.path.exists(self.progress_file):
            with open(self.progress_file, 'r') as f:
                data = json.load(f)
                self.downloaded_chunks = set(data['chunks'])
                self.total_size = data['total_size']
                
    def _save_progress(self):
        """Save download progress"""
        with open(self.progress_file, 'w') as f:
            json.dump({
                'chunks': list(self.downloaded_chunks),
                'total_size': self.total_size
            }, f)

    def download_chunk(self, offset: int, length: int) -> bytes:
        """Download a specific byte range"""
        request_data = json.dumps({
            'request_type': 'restore_file',
            'file_path': base64.b64encode(
                str(self.file_path).encode("utf-8")
            ).decode('utf-8'),
            'api_key': self.api_key,
            'agent_id': self.agent_id,
            'range': f'bytes={offset}-{offset+length-1}'
        })
        
        status_code, response = scnet.tls_send_json_data_get(
            request_data, 
            206,  # Partial Content
            show_json=False
        )
        
        if status_code != 206 or 'file_content' not in response:
            raise Exception(f"Failed to download chunk: {status_code}")
            
        return base64.b64decode(response['file_content'])

    def restore_file(self, progress_callback=None) -> bool:
        """
        Restore file with resume capability
        
        Args:
            progress_callback: Optional callback(percent, downloaded, total)
        """
        try:
            # Create temp directory
            os.makedirs(self.temp_dir, exist_ok=True)
            
            # Get file size if we don't have it
            if not self.total_size:
                info_request = json.dumps({
                    'request_type': 'restore_file_info',
                    'file_path': base64.b64encode(str(self.file_path).encode("utf-8")).decode('utf-8'),
                    'api_key': self.api_key,
                    'agent_id': self.agent_id
                })
                
                status_code, response = scnet.tls_send_json_data_get(info_request, 200)
                
                if status_code != 200 or 'size' not in response:
                    raise Exception("Failed to get file size")
                    
                self.total_size = response['size']
                self._save_progress()

            # Calculate chunks
            total_chunks = (self.total_size + self.chunk_size - 1) // self.chunk_size
                          
            # Download missing chunks
            for chunk_num in range(total_chunks):
                if chunk_num in self.downloaded_chunks:
                    continue
                    
                offset = chunk_num * self.chunk_size
                length = min(self.chunk_size, self.total_size - offset)
                           
                chunk_data = self.download_chunk(offset, length)
                chunk_path = os.path.join(self.temp_dir, f"chunk_{chunk_num:08d}")
                
                with open(chunk_path, 'wb') as f:
                    f.write(chunk_data)
                    
                self.downloaded_chunks.add(chunk_num)
                self._save_progress()
                
                if progress_callback:
                    downloaded = len(self.downloaded_chunks) * self.chunk_size
                    progress_callback(
                        (downloaded / self.total_size) * 100,
                        downloaded,
                        self.total_size
                    )

            # Reassemble file
            with open(f"{self.file_path}.tmp", 'wb') as outfile:
                for chunk_num in range(total_chunks):
                    chunk_path = os.path.join(self.temp_dir, f"chunk_{chunk_num:08d}")
                    with open(chunk_path, 'rb') as chunk:
                        outfile.write(chunk.read())
                        
            # Atomic rename
            os.replace(f"{self.file_path}.tmp", self.file_path)
            
            # Cleanup
            shutil.rmtree(self.temp_dir)
            os.remove(self.progress_file)
            
            return True
            
        except Exception as e:
            logging.error(f"Restore failed: {e}")
            return False

class DriveMonitor:
    """Monitors for new drive connections and prompts for backup registration."""
    
    def __init__(self, settings_path: str, systray=None):
        self.settings_path = settings_path
        self.systray = systray
        self._known_drives: Set[str] = set()
        self._lock = threading.Lock()
        self._running = False
        self._monitor_thread = None
        
        # Initialize known drives
        self._scan_existing_drives()
        
        # Initialize notification preference
        self._ensure_notification_setting()
        
    def _scan_existing_drives(self):
        """Scan and record currently connected drives."""
        with self._lock:
            bitmask = win32api.GetLogicalDrives()
            self._known_drives = {
                f"{chr(letter)}:\\" for letter in range(65, 91)
                if bitmask & (1 << (letter - 65))
                and win32file.GetDriveType(f"{chr(letter)}:\\") in (
                    win32file.DRIVE_FIXED,
                    win32file.DRIVE_REMOVABLE
                )
            }
            logging.info(f"Initial drive scan found: {self._known_drives}")

    def _ensure_notification_setting(self):
        """Ensure the notification preference exists in settings."""
        try:
            with open(self.settings_path, 'r') as f:
                settings = yaml.safe_load(f)
                
            if 'drive_monitor_notifications' not in settings:
                settings['drive_monitor_notifications'] = True
                with open(self.settings_path, 'w') as f:
                    yaml.safe_dump(settings, f, default_flow_style=False)
                logging.info("Added drive_monitor_notifications setting")
        except Exception as e:
            logging.error(f"Error ensuring notification setting: {e}")

    def _get_notification_preference(self) -> bool:
        """Get current notification preference."""
        try:
            with open(self.settings_path, 'r') as f:
                settings = yaml.safe_load(f)
            return settings.get('drive_monitor_notifications', True)
        except Exception as e:
            logging.error(f"Error reading notification preference: {e}")
            return True  # Default to showing notifications on error

    def _set_notification_preference(self, enabled: bool):
        """Update notification preference."""
        try:
            with open(self.settings_path, 'r') as f:
                settings = yaml.safe_load(f)
            
            settings['drive_monitor_notifications'] = enabled
            
            with open(self.settings_path, 'w') as f:
                yaml.safe_dump(settings, f, default_flow_style=False)
                
            logging.info(f"Updated drive_monitor_notifications to {enabled}")
        except Exception as e:
            logging.error(f"Error updating notification preference: {e}")

    def start(self):
        """Start drive monitoring."""
        if self._running:
            return
            
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop)
        self._monitor_thread.daemon = True
        self._monitor_thread.start()
        logging.info("Drive monitor started")

    def stop(self):
        """Stop drive monitoring."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join()
        logging.info("Drive monitor stopped")

    def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                # Get current drives
                bitmask = win32api.GetLogicalDrives()
                current_drives = {
                    f"{chr(letter)}:\\" for letter in range(65, 91)
                    if bitmask & (1 << (letter - 65))
                    and win32file.GetDriveType(f"{chr(letter)}:\\") in (
                        win32file.DRIVE_FIXED,
                        win32file.DRIVE_REMOVABLE
                    )
                }
                
                # Check for new drives
                with self._lock:
                    new_drives = current_drives - self._known_drives
                    for drive in new_drives:
                        self._handle_new_drive(drive)
                    self._known_drives = current_drives

                # Sleep between checks
                win32api.Sleep(1000)  # Check every second

            except Exception as e:
                logging.error(f"Error in drive monitor loop: {e}")
                win32api.Sleep(5000)  # Wait longer on error

    def _handle_new_drive(self, drive: str):
        """Handle detection of a new drive."""
        # Check if drive is already in backup paths
        try:
            with open(self.settings_path, 'r') as f:
                settings = yaml.safe_load(f)
            
            backup_paths = settings.get('BACKUP_PATHS', [])
            recursive_paths = settings.get('RECURSIVE_BACKUP_PATHS', [])
            
            # Convert paths to consistent format for comparison
            drive = drive.replace('\\', '/')
            if drive in backup_paths or drive in recursive_paths:
                logging.info(f"Drive {drive} already in backup paths, skipping prompt")
                return
                
        except Exception as e:
            logging.error(f"Error checking existing backup paths: {e}")
            return
            
        # Check notification preference
        if not self._get_notification_preference():
            logging.info("Drive notifications disabled, skipping prompt")
            return
            
        try:
            # Get drive label for better user display
            try:
                vol_name = win32api.GetVolumeInformation(drive)[0]
                display_name = f"{vol_name} ({drive})" if vol_name else drive
            except:
                display_name = drive
                
            logging.info(f"New drive detected: {display_name}")
            
            # Show system tray notification with buttons
            if self.systray:
                icon = None  # Use default icon
                title = "New Drive Detected"
                message = f"Would you like to back up {display_name}?"
                
                # Use hover balloon tip first
                if hasattr(self.systray, "show_balloon_tip"):
                    self.systray.show_balloon_tip(
                        title,
                        message,
                        icon,
                        win32gui.NIIF_INFO
                    )
                
                # Show custom dialog
                app = QApplication.instance()
                if not app:
                    app = QApplication([])
                
                dialog = DriveDetectionDialog(display_name, theme_manager=None, parent=None)
                result = dialog.exec_()
                
                # Check dialog results
                if dialog.dont_ask_again:
                    self._set_notification_preference(False)
                    logging.info("User disabled drive notifications")
                
                if result == QDialog.Accepted:
                    self._add_drive_to_backup(drive)

        except Exception as e:
            logging.error(f"Error handling new drive {drive}: {e}")

    def _add_drive_to_backup(self, drive: str):
        """Add drive to backup paths in settings."""
        try:
            # Read current settings
            with open(self.settings_path, 'r') as f:
                settings = yaml.safe_load(f)
            
            # Add to recursive backup paths if not already present
            if 'RECURSIVE_BACKUP_PATHS' not in settings:
                settings['RECURSIVE_BACKUP_PATHS'] = []
            
            if drive not in settings['RECURSIVE_BACKUP_PATHS']:
                settings['RECURSIVE_BACKUP_PATHS'].append(drive)
                
                # Write updated settings
                with open(self.settings_path, 'w') as f:
                    yaml.safe_dump(settings, f, default_flow_style=False)
                    
                logging.info(f"Added {drive} to backup paths")
            else:
                logging.info(f"Drive {drive} already in backup paths")

        except Exception as e:
            logging.error(f"Error adding drive to backup paths: {e}")
            # Show error to user
            if self.systray:
                self.systray.show_balloon_tip(
                    "Error",
                    f"Failed to add {drive} to backup paths",
                    None,
                    win32gui.NIIF_ERROR
                )

class DriveDetectionDialog(QDialog):
    def __init__(self, drive_name, theme_manager=None, parent=None):
        super().__init__(parent)
        self.drive_name = drive_name
        self.theme_manager = theme_manager
        self.dont_ask_again = False
        self.result = False
        self.setup_ui()
        self.apply_theme()
        
        # Set up auto-close timer (10 seconds)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.close)
        self.timer.start(10000)  # 10 seconds
        
    def setup_ui(self):
        self.setWindowTitle("Stormcloud Backup")
        self.setFixedWidth(450)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        
        # Header with icon and title
        header_layout = QHBoxLayout()
        
        # Get application icon
        icon = self.get_app_icon()
        if icon:
            icon_label = QLabel()
            pixmap = icon.pixmap(48, 48)
            icon_label.setPixmap(pixmap)
            header_layout.addWidget(icon_label)
        
        title_label = QLabel("New Drive Detected")
        title_font = title_label.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        # Message
        message = QLabel(
            f"Would you like to automatically backup {self.drive_name}?\n\n"
            "If you choose Yes, all files on this drive will be backed up."
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        
        # Don't ask again checkbox
        self.dont_ask_checkbox = QCheckBox("Don't ask me again for new drives")
        layout.addWidget(self.dont_ask_checkbox)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.yes_button = QPushButton("Yes, Back Up")
        self.yes_button.setFixedWidth(120)
        self.yes_button.clicked.connect(self.accept_backup)
        
        self.no_button = QPushButton("No, Skip")
        self.no_button.setFixedWidth(120)
        self.no_button.clicked.connect(self.reject_backup)
        
        button_layout.addWidget(self.yes_button)
        button_layout.addWidget(self.no_button)
        
        layout.addLayout(button_layout)
        
    def accept_backup(self):
        self.result = True
        self.dont_ask_again = self.dont_ask_checkbox.isChecked()
        self.timer.stop()
        self.accept()
        
    def reject_backup(self):
        self.result = False
        self.dont_ask_again = self.dont_ask_checkbox.isChecked()
        self.timer.stop()
        self.reject()
        
    def apply_theme(self):
        if not self.theme_manager:
            return
            
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        
        # Apply background and text colors
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {theme['panel_background']};
                color: {theme['text_primary']};
            }}
            QLabel {{
                color: {theme['text_primary']};
            }}
            QCheckBox {{
                color: {theme['text_primary']};
            }}
            QPushButton {{
                background-color: {theme['button_background']};
                color: {theme['button_text']};
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
            QPushButton:pressed {{
                background-color: {theme['button_pressed']};
            }}
            QPushButton#yes-button {{
                background-color: {theme['accent_color']};
            }}
            QPushButton#yes-button:hover {{
                background-color: {theme['accent_color_hover']};
            }}
        """)
        
    def get_app_icon(self):
        """Extract icon from stormcloud.exe"""
        try:
            appdata_path = os.getenv('APPDATA')
            settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')
            
            if os.path.exists(settings_path):
                import json
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                
                install_path = settings.get('install_path', '')
                exe_path = os.path.join(install_path, 'stormcloud.exe')
                
                if os.path.exists(exe_path):
                    # Extract icon from exe
                    import win32gui
                    import win32api
                    from PyQt5.QtWinExtras import QtWin
                    
                    large, small = win32gui.ExtractIconEx(exe_path, 0)
                    if large:
                        win32gui.DestroyIcon(small[0])
                        
                        # Convert icon to HICON
                        hicon = large[0]
                        
                        # Convert to QPixmap using QtWin
                        pixmap = QtWin.fromHICON(hicon)
                        
                        # Create and return QIcon
                        icon = QIcon(pixmap)
                        
                        # Clean up
                        win32gui.DestroyIcon(hicon)
                        return icon
                        
        except Exception as e:
            logging.error(f"Failed to get application icon: {e}")
        
        return None


def should_backup(schedule, last_check_time, backup_state):
    """Check if backup should run based on schedule"""
    logging.info("\n=== Starting backup check ===")
    logging.info(f"Input schedule: {schedule} (type: {type(schedule)})")
    logging.info(f"Last check time: {last_check_time} (type: {type(last_check_time)})")
    
    # Initialize flags
    should_run = False
    trigger_source = None
    
    # Get current time info
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    last_check_str = last_check_time.strftime("%H:%M")
    day_changed = now.date() != last_check_time.date()
    
    logging.info(f"Current time: {current_time}")
    logging.info(f"Last check string: {last_check_str}")
    logging.info(f"Day changed: {day_changed}")
    
    # Time jump check
    time_jump = abs((now - last_check_time).total_seconds()) > 300
    logging.info(f"Time jump detected: {time_jump}")
    if time_jump:
        logging.warning(f"Significant time change: {last_check_time} -> {now}")
    
    # Backup in progress check
    logging.info(f"Backup in progress: {backup_state.backup_in_progress}")
    if backup_state.backup_in_progress:
        duration = backup_state.get_backup_duration()
        logging.info(f"Current backup duration: {duration} seconds")
        if duration > 3600:
            logging.error(f"Backup timeout after {duration} seconds")
            backup_state.complete_backup(success=False)
        else:
            logging.info("Skipping schedule check - backup in progress")
            return False, None

    # Weekly schedule check
    weekday = calendar.day_name[now.weekday()]
    logging.info(f"Checking weekly schedule for {weekday}")
    logging.info(f"Weekly schedule data: {schedule.get('weekly', {})}")
    
    if weekday in schedule.get('weekly', {}):
        times = schedule['weekly'][weekday]
        logging.info(f"Found times for {weekday}: {times} (type: {type(times)})")
        
        if times is not None and isinstance(times, list):
            logging.info(f"Checking if {current_time} in {times}")
            if current_time in times:
                if last_check_str <= current_time or day_changed or time_jump:
                    logging.info(f"Weekly backup triggered for {weekday} at {current_time}")
                    should_run = True
                    trigger_source = 'weekly'
        else:
            logging.warning(f"Times for {weekday} is not a list or is None: {times}")

    # Monthly schedule check
    if not should_run:
        logging.info("Checking monthly schedule")
        logging.info(f"Monthly schedule data: {schedule.get('monthly', {})}")
        
        day_of_month = str(now.day)
        monthly_schedule = schedule.get('monthly', {})
        
        if monthly_schedule:
            # Last day check
            if "Last day" in monthly_schedule:
                last_day = calendar.monthrange(now.year, now.month)[1]
                logging.info(f"Checking last day ({last_day}) of month")
                
                if now.day == last_day:
                    times = monthly_schedule["Last day"]
                    logging.info(f"Found times for last day: {times} (type: {type(times)})")
                    
                    if times is not None and isinstance(times, list):
                        logging.info(f"Checking if {current_time} in {times}")
                        if current_time in times:
                            if last_check_str <= current_time or day_changed or time_jump:
                                logging.info(f"Monthly backup triggered for last day at {current_time}")
                                should_run = True
                                trigger_source = 'monthly'
                    else:
                        logging.warning(f"Times for last day is not a list or is None: {times}")

            # Regular day check
            if not should_run and day_of_month in monthly_schedule:
                times = monthly_schedule[day_of_month]
                logging.info(f"Found times for day {day_of_month}: {times} (type: {type(times)})")
                
                if times is not None and isinstance(times, list):
                    logging.info(f"Checking if {current_time} in {times}")
                    if current_time in times:
                        if last_check_str <= current_time or day_changed or time_jump:
                            logging.info(f"Monthly backup triggered for day {day_of_month} at {current_time}")
                            should_run = True
                            trigger_source = 'monthly'
                else:
                    logging.warning(f"Times for day {day_of_month} is not a list or is None: {times}")

    logging.info(f"Final decision - should_run: {should_run}, trigger_source: {trigger_source}")
    logging.info("=== Backup check complete ===\n")
    return should_run, trigger_source

def main(settings_file_path,hash_db_file_path,ignore_hash_db):

    # install directory from stable_settings.cfg
    install_directory = _get_install_directory()

    if not install_directory:
        logging.log(logging.ERROR, "Unable to locate install. Exiting!")
        exit()        

    # This path may or may not exist,
    # depending if this is the first run of the application
    if hash_db_file_path == 'use_app_data':
        hash_db_file_path = os.path.join(install_directory, 'schash.db')

    # This path should exist by the time the application
    # is running, as it should be written by the installer.
    if settings_file_path == 'use_app_data':
        settings_file_path = os.path.join(install_directory, 'settings.cfg')

    settings = read_yaml_settings_file(settings_file_path)

    logging_utils.send_logs_to_server(settings['API_KEY'],settings['AGENT_ID'])
    logging_utils.initialize_logging(cwd=install_directory,uuid=settings['AGENT_ID'])

    hash_db_conn = get_or_create_hash_db(hash_db_file_path)

    systray_menu_options = (
        (
            "Backup now",
            None,
            lambda x: logging.log(logging.INFO, "User clicked 'Backup now', but backup is always running.")
        )
    ,)
    systray = SysTrayIcon("stormcloud.ico", "Stormcloud Backup Engine", systray_menu_options)
    systray.start()

    # Initialize and start drive monitor
    drive_monitor = DriveMonitor(settings_file_path, systray)
    drive_monitor.start()
    
    try:
        action_loop_and_sleep(
            settings=settings,
            settings_file_path=settings_file_path,
            dbconn=hash_db_conn,
            ignore_hash=ignore_hash_db,
            systray=systray
        )
    finally:
        # Ensure drive monitor is stopped on exit
        drive_monitor.stop()

def save_file_metadata(settings):
    """Save file metadata to the manifest directory"""
    api_key = settings['API_KEY']
    agent_id = settings['AGENT_ID']
    
    metadata = network_utils.fetch_file_metadata(api_key, agent_id)
    
    if metadata:
        # Get installation path from settings
        appdata_path = os.getenv('APPDATA')
        settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')
        
        try:
            with open(settings_path, 'r') as f:
                stable_settings = json.load(f)
            install_path = stable_settings.get('install_path', '')
            
            # Create manifest directory
            manifest_dir = os.path.join(install_path, 'file_explorer', 'manifest')
            os.makedirs(manifest_dir, exist_ok=True)
            
            # Save new metadata file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"file_metadata_{timestamp}.json"
            file_path = os.path.join(manifest_dir, filename)
            
            with open(file_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            logging.info(f"File metadata saved to {file_path}")
            
            # Cleanup old files
            cleanup_old_metadata(manifest_dir)
            
        except Exception as e:
            logging.error(f"Failed to save metadata: {e}")
    else:
        logging.error("Failed to fetch file metadata")

def cleanup_old_metadata(manifest_dir, max_files=10):
    """Remove old metadata files keeping only the most recent ones"""
    try:
        # Get list of metadata files
        files = [f for f in os.listdir(manifest_dir) 
                if f.startswith('file_metadata_') and f.endswith('.json')]
        
        # Sort by timestamp in filename
        files.sort(key=lambda x: datetime.strptime(
            x, 'file_metadata_%Y%m%d_%H%M%S.json'), reverse=True)
        
        # Remove old files
        if len(files) > max_files:
            for old_file in files[max_files:]:
                file_path = os.path.join(manifest_dir, old_file)
                try:
                    os.remove(file_path)
                    logging.info(f"Removed old metadata file: {old_file}")
                except Exception as e:
                    logging.error(f"Failed to remove old metadata file {old_file}: {e}")
                    
    except Exception as e:
        logging.error(f"Error during metadata cleanup: {e}")

def action_loop_and_sleep(settings, settings_file_path, dbconn, ignore_hash, systray):
    active_thread = None
    last_check_time = datetime.now()
    backup_state = BackupState()
    
    # Initialize history manager
    appdata_path = os.getenv('APPDATA')
    settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')
    with open(settings_path, 'r') as f:
        stable_settings = json.load(f)
    install_path = stable_settings.get('install_path', '')
    history_manager = CoreHistoryManager(install_path)

    while True:
        try:
            settings = read_yaml_settings_file(settings_file_path)
            network_utils.sync_backup_folders(settings)

            # Handle keepalive thread
            cur_keepalive_freq = int(settings['KEEPALIVE_FREQ'])
            if active_thread is None or not active_thread.is_alive():
                active_thread = start_keepalive_thread(
                    cur_keepalive_freq,
                    settings['API_KEY'],
                    settings['AGENT_ID']
                )

            backup_mode = settings.get('BACKUP_MODE', 'Realtime')
            current_time = datetime.now()

            if backup_mode == 'Realtime':
                if not backup_state.backup_in_progress:
                    # Start backup operation in history
                    operation_id = history_manager.start_operation(InitiationSource.REALTIME)
                    backup_state.start_backup('realtime')
                    
                    try:
                        success = perform_backup_with_history(
                            settings['BACKUP_PATHS'],
                            settings['RECURSIVE_BACKUP_PATHS'],
                            settings,
                            dbconn,
                            ignore_hash,
                            systray,
                            history_manager,
                            operation_id
                        )
                        save_file_metadata(settings)
                        backup_state.complete_backup(success=success)
                        
                        final_status = OperationStatus.SUCCESS if success else OperationStatus.FAILED
                        history_manager.complete_operation(operation_id, final_status)
                        
                    except Exception as e:
                        logging.error(f"Backup failed: {str(e)}")
                        backup_state.complete_backup(success=False)
                        history_manager.complete_operation(
                            operation_id,
                            OperationStatus.FAILED,
                            str(e)
                        )
                    
                last_check_time = current_time
                sleep(ACTION_TIMER)
                
            else:  # Scheduled mode
                logging.info("Attempting scheduled mode backup...")
                schedule = parse_schedule(settings)
                logging.info("Checking if backup should run...")
                should_run, source = should_backup(schedule, last_check_time, backup_state)
                
                if should_run and source:
                    if backup_state.start_backup(source):
                        logging.info("Determined backup should run. Initiating scheduled backup...")
                        # Start backup operation in history
                        operation_id = history_manager.start_operation(InitiationSource.SCHEDULED)
                        
                        try:
                            success = perform_backup_with_history(
                                settings['BACKUP_PATHS'],
                                settings['RECURSIVE_BACKUP_PATHS'],
                                settings,
                                dbconn,
                                ignore_hash,
                                systray,
                                history_manager,
                                operation_id
                            )
                            save_file_metadata(settings)
                            backup_state.complete_backup(success=success)
                            
                            final_status = OperationStatus.SUCCESS if success else OperationStatus.FAILED
                            history_manager.complete_operation(operation_id, final_status)
                            
                        except Exception as e:
                            logging.error(f"Scheduled backup failed: {str(e)}")
                            backup_state.complete_backup(success=False)
                            history_manager.complete_operation(
                                operation_id,
                                OperationStatus.FAILED,
                                str(e)
                            )
                
                last_check_time = current_time
                sleep(ACTION_TIMER)
            
        except Exception as e:
            logging.error(f"Error in backup loop: {str(e)}")
            sleep(ACTION_TIMER)

def perform_backup_with_history(backup_paths, recursive_paths, settings, dbconn, 
                              ignore_hash, systray, history_manager, operation_id):
    """Perform backup with history tracking"""
    success = True
    files_processed = False  # Track if we actually processed any files
    
    def normalize_path(path):
        """Normalize path to use forward slashes"""
        return str(path).replace('\\', '/')
    
    def process_path(path, is_recursive=False):
        nonlocal success, files_processed
        path = normalize_path(path)
        
        try:
            if os.path.isfile(path):
                try:
                    backup_result = backup_utils.process_file(
                        pathlib.Path(path),
                        settings['API_KEY'],
                        settings['AGENT_ID'],
                        dbconn,
                        ignore_hash
                    )
                    
                    if backup_result == BackupResult.BACKED_UP:
                        files_processed = True
                        history_manager.add_file_record(
                            operation_id,
                            path,
                            OperationStatus.SUCCESS,
                            None
                        )
                    elif backup_result == BackupResult.FAILED:
                        files_processed = True
                        success = False
                        history_manager.add_file_record(
                            operation_id,
                            path,
                            OperationStatus.FAILED,
                            "Backup operation failed"
                        )
                    # Skip recording UNCHANGED files
                    
                except Exception as e:
                    files_processed = True
                    success = False
                    error_msg = str(e)
                    logging.error(f"Error backing up file {path}: {error_msg}")
                    history_manager.add_file_record(
                        operation_id,
                        path,
                        OperationStatus.FAILED,
                        error_msg
                    )
                    
            elif is_recursive:  # Directory with recursive backup
                for root, _, files in os.walk(path):
                    for file in files:
                        file_path = normalize_path(os.path.join(root, file))
                        try:
                            file_success = backup_utils.process_file(
                                pathlib.Path(file_path),
                                settings['API_KEY'],
                                settings['AGENT_ID'],
                                dbconn,
                                ignore_hash
                            )
                            status = OperationStatus.SUCCESS if file_success else OperationStatus.FAILED
                            history_manager.add_file_record(
                                operation_id, 
                                file_path, 
                                status,
                                None if file_success else "File backup failed"
                            )
                            if not file_success:
                                success = False
                                logging.error(f"Failed to backup file: {file_path}")
                        except Exception as e:
                            success = False
                            error_msg = str(e)
                            logging.error(f"Error backing up file {file_path}: {error_msg}")
                            history_manager.add_file_record(
                                operation_id,
                                file_path,
                                OperationStatus.FAILED,
                                error_msg
                            )
            
            elif os.path.isdir(path):  # Directory without recursive backup
                # Only process files in the immediate directory
                for entry in os.scandir(path):
                    if entry.is_file():
                        file_path = normalize_path(entry.path)
                        try:
                            file_success = backup_utils.process_file(
                                pathlib.Path(file_path),
                                settings['API_KEY'],
                                settings['AGENT_ID'],
                                dbconn,
                                ignore_hash
                            )
                            status = OperationStatus.SUCCESS if file_success else OperationStatus.FAILED
                            history_manager.add_file_record(
                                operation_id, 
                                file_path, 
                                status,
                                None if file_success else "File backup failed"
                            )
                            if not file_success:
                                success = False
                                logging.error(f"Failed to backup file: {file_path}")
                        except Exception as e:
                            success = False
                            error_msg = str(e)
                            logging.error(f"Error backing up file {file_path}: {error_msg}")
                            history_manager.add_file_record(
                                operation_id,
                                file_path,
                                OperationStatus.FAILED,
                                error_msg
                            )

        except Exception as e:
            files_processed = True
            success = False
            error_msg = f"Error processing path {path}: {str(e)}"
            logging.error(error_msg)
            history_manager.add_file_record(
                operation_id,
                path,
                OperationStatus.FAILED,
                error_msg
            )

    # Process backup paths
    logging.info("Processing regular backup paths: %s", backup_paths)
    for path in backup_paths:
        process_path(path, False)

    # Process recursive backup paths
    logging.info("Processing recursive backup paths: %s", recursive_paths)
    for path in recursive_paths:
        process_path(path, True)

    # If no files needed processing, consider it a success
    if not files_processed:
        success = True

    return success

def parse_schedule(settings):
    """Parse the BACKUP_SCHEDULE from settings and return structured schedule data"""
    logging.info("=== Starting schedule parse ===")
    logging.info(f"Full settings object: {settings}")
    
    schedule_data = settings.get('BACKUP_SCHEDULE', {})
    logging.info(f"Raw BACKUP_SCHEDULE data: {schedule_data} (type: {type(schedule_data)})")
    
    if schedule_data is None:
        logging.warning("BACKUP_SCHEDULE is None, defaulting to empty structure")
        schedule_data = {}
        
    # Log raw weekly/monthly data before processing
    weekly_raw = schedule_data.get('weekly')
    monthly_raw = schedule_data.get('monthly')
    logging.info(f"Raw weekly data: {weekly_raw} (type: {type(weekly_raw)})")
    logging.info(f"Raw monthly data: {monthly_raw} (type: {type(monthly_raw)})")
    
    schedule = {
        'weekly': schedule_data.get('weekly', {}) or {},
        'monthly': schedule_data.get('monthly', {}) or {}
    }
    
    logging.info(f"Final processed schedule: {schedule}")
    logging.info("=== Schedule parse complete ===")
    return schedule

def read_yaml_settings_file(fn):
    if not os.path.exists(fn):
        logging.log(logging.ERROR, "Unable to locate settings file. Exiting!")
        exit()

    with open(fn, 'r') as settings_file:
        return yaml.safe_load(settings_file)

def _get_install_directory():
    """
        Parses stable_settings.cfg to get install directory.
    """
    success = False

    # Get installation path from settings
    appdata_path = os.getenv('APPDATA')
    stable_settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')

    try:
        with open(stable_settings_path, 'r') as f:
            stable_settings = json.load(f)
        install_path = stable_settings.get('install_path', '')
        success = True

    except Exception as e:
        print(traceback.format_exc())
        pass
    finally:
        if success:
            return install_path
        else:
            return None

def start_keepalive_thread(freq,api_key,agent_id):
    logging.log(logging.INFO,"starting new keepalive thread with freq %d" % freq)

    t = threading.Thread(target=keepalive_utils.execute_ping_loop,args=(freq,api_key,agent_id))
    t.start()

    logging.log(logging.INFO,"returning from start thread")
    return t

if __name__ == "__main__":
    description = r"""

        ______     ______   ______     ______     __    __                    
       /\  ___\   /\__  _\ /\  __ \   /\  == \   /\ "-./  \                   
       \ \___  \  \/_/\ \/ \ \ \/\ \  \ \  __<   \ \ \-./\ \                  
        \/\_____\    \ \_\  \ \_____\  \ \_\ \_\  \ \_\ \ \_\                 
         \/_____/     \/_/   \/_____/   \/_/ /_/   \/_/  \/_/                 
                                                                              
                    ______     __         ______     __  __     _____         
                   /\  ___\   /\ \       /\  __ \   /\ \/\ \   /\  __-.       
                   \ \ \____  \ \ \____  \ \ \/\ \  \ \ \_\ \  \ \ \/\ \      
                    \ \_____\  \ \_____\  \ \_____\  \ \_____\  \ \____-      
                     \/_____/   \/_____/   \/_____/   \/_____/   \/____/      
                                                                              
                                   ______     ______     ______     ______    
                                  /\  ___\   /\  __ \   /\  == \   /\  ___\   
                                  \ \ \____  \ \ \/\ \  \ \  __<   \ \  __\   
                                   \ \_____\  \ \_____\  \ \_\ \_\  \ \_____\ 
                                    \/_____/   \/_____/   \/_/ /_/   \/_____/ 
                                                                                                                                                                                                                                                                           

    """

    description += 'Welcome to Stormcloud, the best backup system!'
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-s", "--settings-file",type=str,default="use_app_data",help="Path to settings file (default=<install directory>/settings.cfg)")
    parser.add_argument("-d", "--hash-db", type=str, default="use_app_data", help="Path to hash db file (default=<install directory>/schash.db")
    parser.add_argument("-o", "--ignore-hash-db", action="store_true", help="override the hash db, to backup files even if they haven't changed")

    args = parser.parse_args()
    main(args.settings_file,args.hash_db,args.ignore_hash_db)