import csv
import json
import logging
import os
import pathlib
import psutil
import pytz
import signal
import smtplib
import stripe
import subprocess
import time
import win32api
import win32gui
import win32con
import yaml

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from enum import Enum
from infi.systray import SysTrayIcon
from multiprocessing import Process, Queue, Manager
from queue import Empty
from typing import Optional, List, Dict

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QMenu,
                             QLabel, QPushButton, QToolButton, QListWidget, QListWidgetItem,
                             QMessageBox, QFileDialog, QGridLayout, QFormLayout,
                             QScrollArea, QSizePolicy, QCheckBox, QComboBox, QFrame,
                             QCalendarWidget, QTimeEdit, QStackedWidget, QGroupBox, QSpinBox,
                             QTreeView, QHeaderView, QStyle, QStyledItemDelegate, QLineEdit,
                             QAbstractItemView, QSplitter, QTreeWidget, QTreeWidgetItem, QDialog,
                             QTextEdit, QProxyStyle, QTabWidget, QTableWidget, QTableWidgetItem, QToolBar,
                             QDialogButtonBox, QProgressBar)
from PyQt5.QtCore import Qt, QUrl, QPoint, QDate, QTime, pyqtSignal, QRect, QSize, QModelIndex, QObject, QTimer
from PyQt5.QtGui import (QDesktopServices, QFont, QIcon, QColor,
                         QPalette, QPainter, QPixmap, QTextCharFormat,
                         QStandardItemModel, QStandardItem, QPen, QPolygon)
from PyQt5.QtWinExtras import QtWin

# Stormcloud imports
#   Core imports
import restore_utils
import backup_utils

from client_db_utils import get_or_create_hash_db

#   Scheduler imports
from scheduler.models import Meeting, Participant, ParticipantRole, WorkingHours, TimeRange
from scheduler.costs import SchedulingCosts
from scheduler.engine import SchedulerBuilder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', 
                    filename='stormcloud_app.log', filemode='a')

def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

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
    
@dataclass
class OperationEvent:
    """Base class for any file operation (backup or restore)"""
    timestamp: datetime
    source: InitiationSource
    status: OperationStatus
    operation_type: str  # 'backup' or 'restore'
    operation_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    files: List[FileOperationRecord] = field(default_factory=list)
    error_message: Optional[str] = None

class HistoryManager:
    """Enhanced history manager with file-level tracking"""
    
    def __init__(self, install_path):
        self.history_dir = os.path.join(install_path, 'history')
        self.backup_history_file = os.path.join(self.history_dir, 'backup_history.json')
        self.restore_history_file = os.path.join(self.history_dir, 'restore_history.json')
        self.active_operations: Dict[str, OperationEvent] = {}
        self.last_modified_times = {
            'backup': 0,
            'restore': 0
        }
        
        # Create directory if it doesn't exist
        os.makedirs(self.history_dir, exist_ok=True)
        
        # Initialize history files if they don't exist
        for file in [self.backup_history_file, self.restore_history_file]:
            if not os.path.exists(file):
                self.write_history(file, [])

    def has_changes(self, event_type: str) -> bool:
        """Check if the history file has been modified since last read"""
        history_file = self.get_history_file(event_type)
        if not os.path.exists(history_file):
            return False
            
        current_mtime = os.path.getmtime(history_file)
        last_mtime = self.last_modified_times.get(event_type, 0)
        
        if current_mtime > last_mtime:
            self.last_modified_times[event_type] = current_mtime
            return True
            
        return False

    def get_history_file(self, operation_type: str) -> str:
        """Get the appropriate history file for the operation type"""
        return self.backup_history_file if operation_type == 'backup' else self.restore_history_file

    def get_history(self, event_type: str, limit: int = None, force_refresh: bool = False) -> List[HistoryEvent]:
        """Get history events, optionally checking for changes first"""
        if not force_refresh and not self.has_changes(event_type):
            return []  # No changes, signal to skip refresh
            
        file_path = self.backup_history_file if event_type == 'backup' else self.restore_history_file
        history = self.read_history(file_path)
        
        # Convert dictionaries back to HistoryEvent objects
        events = []
        for event_dict in history:
            try:
                event = self.dict_to_event(event_dict)
                events.append(event)
            except Exception as e:
                logging.error(f"Failed to convert history event: {e}")
                continue
            
        # Sort by timestamp (newest first) and apply limit
        events.sort(key=lambda x: x.timestamp, reverse=True)
        return events[:limit] if limit else events

    def read_history(self, file_path: str) -> list:
        """Read history from JSON file"""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
            
    def write_history(self, file_path: str, history: list):
        """Write history to JSON file"""
        with open(file_path, 'w') as f:
            json.dump(history, f, indent=2)

    def add_event(self, event_type: str, event: OperationEvent):
        """Add or update an event in history"""
        history_file = self.get_history_file(event_type)
        history = self.read_history(history_file)
        
        # Convert event to dictionary preserving original timestamp
        event_dict = self.event_to_dict(event)
        
        # Find and update existing entry if it exists
        updated = False
        for i, existing_event in enumerate(history):
            if existing_event.get('operation_id') == event.operation_id:
                # Preserve original timestamp when updating
                event_dict['timestamp'] = existing_event['timestamp']
                history[i] = event_dict
                updated = True
                break
                
        # Only add as new entry if it doesn't exist
        if not updated:
            history.append(event_dict)
        
        # Write back to file
        self.write_history(history_file, history)

    def event_to_dict(self, event: OperationEvent) -> dict:
        """Convert OperationEvent to dictionary for storage"""
        return {
            'timestamp': event.timestamp.isoformat(),  # Use original timestamp
            'source': event.source.value,
            'status': event.status.value,
            'operation_type': event.operation_type,
            'operation_id': event.operation_id,
            'error_message': event.error_message,
            'files': [
                {
                    'filepath': f.filepath,
                    'timestamp': f.timestamp.isoformat(),
                    'status': f.status.value,
                    'error_message': f.error_message
                }
                for f in event.files
            ]
        }

    def dict_to_event(self, event_dict: dict) -> HistoryEvent:
        """Convert dictionary to HistoryEvent"""
        files = [
            FileOperationRecord(
                filepath=f['filepath'],
                timestamp=datetime.fromisoformat(f['timestamp']),
                status=OperationStatus(f['status']),
                error_message=f.get('error_message')
            )
            for f in event_dict.get('files', [])
        ]
        
        return HistoryEvent(
            timestamp=datetime.fromisoformat(event_dict['timestamp']),
            source=InitiationSource(event_dict['source']),
            status=OperationStatus(event_dict['status']),
            operation_id=event_dict.get('operation_id', ''),
            files=files,
            error_message=event_dict.get('error_message')
        )

    def start_operation(self, operation_type: str, source: InitiationSource) -> str:
        """Start a new operation and return its ID"""
        event = OperationEvent(
            timestamp=datetime.now(),
            source=source,
            status=OperationStatus.IN_PROGRESS,
            operation_type=operation_type
        )
        self.active_operations[event.operation_id] = event
        self.add_event(operation_type, event)  # Fixed: Pass both operation_type and event
        return event.operation_id

    def add_file_to_operation(self, operation_id: str, filepath: str, 
                             status: OperationStatus, error_message: Optional[str] = None):
        """Add a file record to an operation and update history"""
        if operation_id in self.active_operations:
            event = self.active_operations[operation_id]
            
            # Check if file already exists in this operation
            file_exists = any(f.filepath == filepath for f in event.files)
            if not file_exists:
                file_record = FileOperationRecord(
                    filepath=filepath,
                    timestamp=datetime.now(),
                    status=status,
                    error_message=error_message
                )
                event.files.append(file_record)
            
            # Update operation status based on file statuses
            self.update_operation_status(operation_id)
            
            # Write the current state to history file immediately
            self.add_event(event.operation_type, event)

    def get_operation(self, operation_id: str) -> Optional[OperationEvent]:
        """Get an operation by ID, either active or from history"""
        # First check active operations
        if operation_id in self.active_operations:
            return self.active_operations[operation_id]
            
        # If not active, check history
        history_file = self.get_history_file('backup')  # Check backup first
        history = self.read_history(history_file)
        for event_dict in history:
            if event_dict.get('operation_id') == operation_id:
                return self.dict_to_event(event_dict)
                
        # Try restore history if not found in backup
        history_file = self.get_history_file('restore')
        history = self.read_history(history_file)
        for event_dict in history:
            if event_dict.get('operation_id') == operation_id:
                return self.dict_to_event(event_dict)
                
        return None

    def complete_operation(self, operation_id: str, final_status: OperationStatus, error_message: Optional[str] = None):
        """Complete an operation by updating its status"""
        if operation_id in self.active_operations:
            event = self.active_operations[operation_id]
            
            # Update status and error message while preserving original timestamp
            event.status = final_status
            event.error_message = error_message
            
            # Update existing event in history
            self.add_event(event.operation_type, event)
            
            # Remove from active operations
            del self.active_operations[operation_id]

    def cleanup_in_progress_operations(self, completed_operation_id: str):
        """Clean up any stale IN_PROGRESS operations from history"""
        for file_type in ['backup', 'restore']:
            history_file = self.get_history_file(file_type)
            try:
                history = self.read_history(history_file)
                updated_history = []
                
                for event in history:
                    # Skip if this is a stale IN_PROGRESS version of our completed operation
                    if (event.get('operation_id') == completed_operation_id and 
                        event.get('status') == OperationStatus.IN_PROGRESS.value):
                        continue
                    updated_history.append(event)
                
                self.write_history(history_file, updated_history)
                
            except Exception as e:
                logging.error(f"Failed to cleanup IN_PROGRESS operations: {e}")

    def update_operation_status(self, operation_id: str):
        """Update operation status based on file statuses"""
        if operation_id in self.active_operations:
            event = self.active_operations[operation_id]
            
            # Get all file statuses
            file_statuses = [f.status for f in event.files]
            
            # For multi-file operations, stay in IN_PROGRESS until completion
            # is explicitly called by complete_operation()
            if event.status == OperationStatus.IN_PROGRESS:
                new_status = OperationStatus.IN_PROGRESS
            # Only set final status when operation is complete
            elif file_statuses:
                if OperationStatus.FAILED in file_statuses:
                    new_status = OperationStatus.FAILED
                elif all(status == OperationStatus.SUCCESS for status in file_statuses):
                    new_status = OperationStatus.SUCCESS
                else:
                    new_status = OperationStatus.IN_PROGRESS
            else:
                new_status = event.status
            
            # Update status if changed
            if new_status != event.status:
                event.status = new_status
                self.add_event(event.operation_type, event)

    def update_event(self, event: OperationEvent):
        """Update an existing event in history"""
        history_file = self.get_history_file(event.operation_type)
        history = self.read_history(history_file)
        
        # Find and update the event
        updated = False
        for i, event_dict in enumerate(history):
            if event_dict.get('operation_id') == event.operation_id:
                history[i] = self.event_to_dict(event)
                updated = True
                break
                
        if not updated:
            history.append(self.event_to_dict(event))
                
        self.write_history(history_file, history)

class OperationHistoryPanel(QWidget):
    """Panel for displaying hierarchical backup/restore history"""
    
    def __init__(self, event_type: str, history_manager: HistoryManager, theme_manager, parent=None):
        super().__init__(parent)
        self.event_type = event_type
        self.history_manager = history_manager
        self.theme_manager = theme_manager
        self.user_expanded_states = {}  # Track user preferences for expansion
        self.scroll_position = 0  # Track scroll position
        self.init_ui()
        
        # Set up refresh timer
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.check_and_refresh_history)
        self.refresh_timer.start(2000)  # Check every 2 seconds

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Header section with title and dropdown
        header_layout = QHBoxLayout()
        
        self.history_type_combo = QComboBox()
        self.history_type_combo.addItems(["Backup History", "Restore History"])
        self.history_type_combo.currentTextChanged.connect(self.on_history_type_changed)
        self.history_type_combo.setFixedWidth(150)
        header_layout.addWidget(self.history_type_combo)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setObjectName("HorizontalDivider")
        layout.addWidget(divider)

        # Create tree widget for history display
        self.tree = QTreeWidget()
        self.tree.setObjectName("HistoryTree")
        
        # Use the CustomTreeCarrot from FileExplorer
        self.custom_style = CustomTreeCarrot(self.theme_manager)
        self.tree.setStyle(self.custom_style)
        
        self.tree.setHeaderLabels([
            "Time",
            "Source",
            "Status",
            "Details"
        ])
        self.tree.setAlternatingRowColors(False)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree.itemExpanded.connect(self.on_item_expanded)
        self.tree.itemCollapsed.connect(self.on_item_collapsed)
        
        # Enable column sorting
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.DescendingOrder)
        
        for i in range(4):
            self.tree.header().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        
        layout.addWidget(self.tree)
       
    def on_item_expanded(self, item):
        """Track when user expands an item"""
        op_id = item.data(0, Qt.UserRole)
        if op_id:
            self.user_expanded_states[op_id] = True  # Update user preference

    def on_item_collapsed(self, item):
        """Track when user collapses an item"""
        op_id = item.data(0, Qt.UserRole)
        if op_id:
            self.user_expanded_states[op_id] = False
            # Force this to persist through next refresh
            self.tree.setUpdatesEnabled(False)
            item.setExpanded(False)
            self.tree.setUpdatesEnabled(True)
            
    def refresh_history(self):
        """Refresh history while preserving user expansion preferences"""
        # Store current expansion states before refresh
        expanded_states = {}
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            op_id = item.data(0, Qt.UserRole)
            if op_id:
                # If item is expanded OR user has previously set it to be expanded
                expanded_states[op_id] = (
                    item.isExpanded() or 
                    self.user_expanded_states.get(op_id, False)
                )

        # Clear and rebuild tree
        self.tree.clear()
        events = self.history_manager.get_history(self.event_type)
        current_ops = set()

        for event in events:
            current_ops.add(event.operation_id)
            
            # Create operation summary item
            summary_item = self.create_operation_summary_item(event)
            
            # Add file details as child items
            for file_record in sorted(event.files, key=lambda x: x.timestamp, reverse=True):
                file_item = self.create_file_item(file_record)
                summary_item.addChild(file_item)
            
            self.tree.addTopLevelItem(summary_item)
            
            # Determine if item should be expanded
            should_expand = False
            
            # First check if we have a stored state
            if event.operation_id in expanded_states:
                should_expand = expanded_states[event.operation_id]
            # For new in-progress operations, expand by default
            elif event.status == OperationStatus.IN_PROGRESS:
                should_expand = True
                self.user_expanded_states[event.operation_id] = True
            
            summary_item.setExpanded(should_expand)
            
            # Store the state for future refreshes
            if should_expand:
                self.user_expanded_states[event.operation_id] = True

        # Clean up tracking for operations that no longer exist
        self.user_expanded_states = {
            op_id: state 
            for op_id, state in self.user_expanded_states.items() 
            if op_id in current_ops
        }

        # Resize columns to content
        for i in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(i)

    def refresh_history_with_events(self, events):
        """Refresh history with provided events while preserving user preferences"""
        # Store current expansion states before refresh
        expanded_states = {}
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            op_id = item.data(0, Qt.UserRole)
            if op_id:
                expanded_states[op_id] = item.isExpanded()

        # Clear and rebuild tree
        self.tree.clear()
        current_ops = set()

        for event in events:
            current_ops.add(event.operation_id)
            
            # Create operation summary item
            summary_item = self.create_operation_summary_item(event)
            
            # Add file details as child items
            for file_record in sorted(event.files, key=lambda x: x.timestamp, reverse=True):
                file_item = self.create_file_item(file_record, event.source.value)  # Pass the source
                summary_item.addChild(file_item)
            
            self.tree.addTopLevelItem(summary_item)
            
            # Set expansion state
            should_expand = expanded_states.get(event.operation_id, False)
            summary_item.setExpanded(should_expand)
            
            # Store the state for future refreshes
            if should_expand:
                self.user_expanded_states[event.operation_id] = True

        # Resize columns to content
        for i in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(i)

    def check_and_refresh_history(self):
        """Check for changes before refreshing"""
        # Save current scroll position
        self.save_scroll_position()
        
        # Get history and check if there are changes
        events = self.history_manager.get_history(self.event_type)
        
        if events:  # Only refresh if there are changes
            self.refresh_history_with_events(events)
            
        # Restore scroll position
        self.restore_scroll_position()

    def create_operation_summary_item(self, event: OperationEvent) -> QTreeWidgetItem:
        """Create a tree item for an operation summary with proper timestamp"""
        # Count files by status
        status_counts = {
            OperationStatus.SUCCESS: 0,
            OperationStatus.FAILED: 0,
            OperationStatus.IN_PROGRESS: 0
        }
        
        for file_record in event.files:
            status_counts[file_record.status] = status_counts.get(file_record.status, 0) + 1
        
        # Create summary text
        if status_counts[OperationStatus.IN_PROGRESS] > 0:
            details = f"In Progress... ({len(event.files)} files so far)"
        else:
            total_files = sum(status_counts.values())
            if total_files == 0:
                if event.status == OperationStatus.SUCCESS:
                    details = "Total: 1 (Success: 1)"
                elif event.status == OperationStatus.FAILED:
                    details = "Total: 1 (Failed: 1)"
                else:
                    details = "Total: 1 (In Progress)"
            else:
                details = (f"Total: {total_files} (Success: {status_counts[OperationStatus.SUCCESS]}, "
                         f"Failed: {status_counts[OperationStatus.FAILED]})")

        # Create the item using operation timestamp with 12-hour format
        item = QTreeWidgetItem([
            event.timestamp.strftime("%Y-%m-%d %I:%M:%S %p"),  # Changed to 12-hour format
            event.source.value,
            event.status.value,
            details
        ])
        
        # Store operation ID
        item.setData(0, Qt.UserRole, event.operation_id)
        
        # Set colors and styling
        self.set_item_status_color(item, event.status)
        font = item.font(0)
        font.setBold(True)
        for i in range(4):
            item.setFont(i, font)
        
        return item

    def create_file_item(self, file_record: FileOperationRecord, parent_source: str) -> QTreeWidgetItem:
        """Create a tree item for a file record with its individual timestamp"""
        item = QTreeWidgetItem([
            file_record.timestamp.strftime("%I:%M:%S %p"),
            parent_source,  # Use the parent operation's source
            file_record.status.value,
            file_record.filepath
        ])
        
        # Store file data
        item.setData(0, Qt.UserRole, file_record.filepath)
        
        # Set colors based on status
        self.set_item_status_color(item, file_record.status)
        
        # Add error message if present
        if file_record.error_message:
            error_item = QTreeWidgetItem([
                "",
                parent_source,  # Keep consistent with parent
                "",
                file_record.error_message
            ])
            error_item.setForeground(3, QColor("#DC3545"))  # Red for errors
            item.addChild(error_item)
        
        return item

    def apply_filters(self):
        """Apply all filters to the history tree"""
        status_filter = self.status_filter.currentText()
        source_filter = self.source_filter.currentText()
        search_text = self.search_box.text().lower()
        
        for i in range(self.tree.topLevelItemCount()):
            top_item = self.tree.topLevelItem(i)
            show_item = True
            
            # Check source filter
            if source_filter != "All Sources":
                if top_item.text(1) != source_filter:
                    show_item = False
            
            # Check status filter
            if status_filter != "All Statuses":
                if top_item.text(2) != status_filter:
                    show_item = False
            
            # Check file name search
            if search_text:
                # Search in child items (files)
                has_matching_file = False
                for j in range(top_item.childCount()):
                    child = top_item.child(j)
                    if search_text in child.text(1).lower() or search_text in child.text(3).lower():
                        has_matching_file = True
                        child.setHidden(False)
                    else:
                        child.setHidden(True)
                show_item = has_matching_file
            else:
                # Show all child items if no search
                for j in range(top_item.childCount()):
                    top_item.child(j).setHidden(False)
            
            top_item.setHidden(not show_item)

    def on_item_expanded(self, item: QTreeWidgetItem):
        """Handle item expansion"""
        # Resize columns to content when expanded
        for i in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(i)

    def on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle double-click on items"""
        # If this is a file item (has filepath in details column)
        filepath = item.text(3)
        if os.path.exists(filepath):
            if os.path.isfile(filepath):
                # Open containing folder and select file
                os.system(f'explorer /select,"{filepath}"')
            else:
                # Open directory
                os.startfile(filepath)

    def on_history_type_changed(self, history_type: str):
        """Handle history type selection change"""
        history_type_map = {
            "Backup History": "backup",
            "Restore History": "restore"
        }
        self.event_type = history_type_map[history_type]
        # Force a refresh when switching history types
        events = self.history_manager.get_history(self.event_type, force_refresh=True)
        if events:
            self.refresh_history_with_events(events)

    def set_item_status_color(self, item: QTreeWidgetItem, status: OperationStatus):
        """Set the color of an item based on its status"""
        status_colors = {
            OperationStatus.SUCCESS: "#28A745",    # Green
            OperationStatus.FAILED: "#DC3545",     # Red
            OperationStatus.IN_PROGRESS: "#FFC107" # Yellow
        }
        item.setForeground(2, QColor(status_colors[status]))

    def save_scroll_position(self):
        """Save the current scroll position"""
        scrollbar = self.tree.verticalScrollBar()
        if scrollbar:
            self.scroll_position = scrollbar.value()

    def restore_scroll_position(self):
        """Restore the previously saved scroll position"""
        scrollbar = self.tree.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(self.scroll_position)

class BackgroundOperation:
    """Handles background processing for backup/restore operations"""
    def __init__(self, operation_type, paths, settings):
        self.operation_type = operation_type
        self.paths = paths if isinstance(paths, list) else [paths]
        self.settings = settings.copy()  # Make a copy to avoid modifying original
        self.queue = Queue()
        self.process = None
        self.total_files = 0
        self.processed_files = 0
        self.manager = Manager()
        self.should_stop = self.manager.Value('b', False)

        # Generate operation ID ONCE at initialization
        self.operation_id = self.settings.get('operation_id') or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.settings['operation_id'] = self.operation_id  # Ensure settings has our operation_id
        
        # Set the operation start time
        self.start_time = datetime.now()
        self.settings['operation_start_time'] = self.start_time

    def start(self):
        """Start the background operation"""
        if self.operation_type == 'backup':
            self.process = Process(target=self._backup_worker, 
                                 args=(self.paths, self.settings, self.queue, self.should_stop))
        else:
            self.process = Process(target=self._restore_worker, 
                                 args=(self.paths, self.settings, self.queue, self.should_stop))
        
        self.process.start()
        return self.process.pid

    def stop(self):
        """Stop the background operation"""
        if self.process and self.process.is_alive():
            self.should_stop.value = True
            self.process.join(timeout=5)
            if self.process.is_alive():
                self.process.terminate()

    def get_progress(self):
        """Get progress updates from the queue without blocking"""
        try:
            while True:
                update = self.queue.get_nowait()
                if update.get('type') == 'total_files':
                    self.total_files = update['value']
                elif update.get('type') == 'file_progress':
                    self.processed_files += 1
                    # Calculate percentage
                    if self.total_files > 0:
                        percentage = (self.processed_files / self.total_files) * 100
                        update['progress'] = percentage
                yield update
        except Empty:
            return

    def update_progress(self):
        """Process progress updates from the background operation"""
        if not hasattr(self, 'history_manager'):
            return
            
        for update in self.get_progress():
            update_type = update.get('type')
            
            if update_type == 'file_progress':
                file_path = update.get('filepath', '')
                success = update.get('success', False)
                error_msg = update.get('error')
                
                # Update file status in history
                if self.operation_id:
                    status = OperationStatus.SUCCESS if success else OperationStatus.FAILED
                    self.history_manager.add_file_to_operation(
                        self.operation_id,
                        file_path,
                        status,
                        error_msg
                    )
                    
                # Calculate progress percentage
                if self.total_files > 0:
                    percentage = (self.processed_files / self.total_files) * 100
                    yield {
                        'type': 'progress',
                        'value': percentage,
                        'current_file': file_path,
                        'status': status,
                        'error': error_msg
                    }

    @staticmethod
    def _backup_worker(paths, settings, queue, should_stop):
        """Worker process for backup operations"""
        try:
            # Use operation_id from settings consistently
            operation_id = settings['operation_id']  # This is now guaranteed to exist
            total_files = 0
            success_count = 0
            fail_count = 0
            
            # First count total files
            for path in paths:
                if os.path.isfile(path):
                    total_files += 1
                else:
                    for _, _, files in os.walk(path):
                        total_files += len(files)
            
            queue.put({'type': 'total_files', 'value': total_files})
            
            # Connect to hash database
            hash_db_path = os.path.join(os.path.dirname(settings['settings_path']), 'schash.db')
            dbconn = get_or_create_hash_db(hash_db_path)
            
            try:
                processed = 0
                for path in paths:
                    if should_stop.value:
                        break
                        
                    if os.path.isfile(path):
                        try:
                            success = backup_utils.process_file(
                                pathlib.Path(path),
                                settings['API_KEY'],
                                settings['AGENT_ID'],
                                settings['SECRET_KEY'],
                                dbconn,
                                True
                            )
                            success_count += 1 if success else 0
                            fail_count += 0 if success else 1
                            processed += 1
                            
                            # Use consistent operation_id
                            queue.put({
                                'type': 'file_progress',
                                'filepath': path,
                                'success': success,
                                'total_files': total_files,
                                'processed_files': processed,
                                'operation_id': operation_id,  # From settings
                                'record_file': True
                            })
                            
                        except Exception as e:
                            logging.error(f"Failed to backup file {path}: {e}")
                            fail_count += 1
                            queue.put({
                                'type': 'file_progress',
                                'filepath': path,
                                'success': False,
                                'error': str(e),
                                'total_files': total_files,
                                'processed_files': processed,
                                'operation_id': operation_id,  # From settings
                                'record_file': True
                            })
                    else:  # Directory
                        for root, _, files in os.walk(path):
                            if should_stop.value:
                                break
                            for file in files:
                                if should_stop.value:
                                    break
                                    
                                file_path = os.path.join(root, file)
                                try:
                                    normalized_path = file_path.replace('\\', '/')
                                    
                                    success = backup_utils.process_file(
                                        pathlib.Path(normalized_path),
                                        settings['API_KEY'],
                                        settings['AGENT_ID'],
                                        settings['SECRET_KEY'],
                                        dbconn,
                                        True
                                    )
                                    success_count += 1 if success else 0
                                    fail_count += 0 if success else 1
                                    processed += 1
                                    
                                    # Use consistent operation_id
                                    queue.put({
                                        'type': 'file_progress',
                                        'filepath': normalized_path,
                                        'success': success,
                                        'total_files': total_files,
                                        'processed_files': processed,
                                        'operation_id': operation_id,  # From settings
                                        'record_file': True,
                                        'parent_folder': path
                                    })
                                    
                                except Exception as e:
                                    logging.error(f"Failed to backup file {file_path}: {e}")
                                    fail_count += 1
                                    queue.put({
                                        'type': 'file_progress',
                                        'filepath': normalized_path,
                                        'success': False,
                                        'error': str(e),
                                        'total_files': total_files,
                                        'processed_files': processed,
                                        'operation_id': operation_id,  # From settings
                                        'record_file': True,
                                        'parent_folder': path
                                    })
                                    
            finally:
                if dbconn:
                    dbconn.close()
                    
            # Use consistent operation_id for completion
            queue.put({
                'type': 'operation_complete',
                'success_count': success_count,
                'fail_count': fail_count,
                'total': total_files,
                'operation_id': operation_id  # From settings
            })
            
        except Exception as e:
            logging.error(f"Backup worker failed: {e}")
            # Use consistent operation_id for failure
            queue.put({
                'type': 'operation_failed',
                'error': str(e),
                'operation_id': operation_id  # From settings
            })

    @staticmethod
    def _restore_worker(paths, settings, queue, should_stop):
        """Worker process for restore operations"""
        try:
            # Use operation_id from settings consistently
            operation_id = settings['operation_id']  # This is now guaranteed to exist
            total_files = 0
            success_count = 0
            fail_count = 0
            
            # First count total files
            for path in paths:
                if os.path.isfile(path):
                    total_files += 1
                else:
                    for _, _, files in os.walk(path):
                        total_files += len(files)
            
            queue.put({'type': 'total_files', 'value': total_files})
            
            processed = 0
            for path in paths:
                if should_stop.value:
                    break
                    
                if os.path.isfile(path):
                    try:
                        success = restore_utils.restore_file(
                            path,
                            settings['API_KEY'],
                            settings['AGENT_ID'],
                            settings['SECRET_KEY']
                        )
                        success_count += 1 if success else 0
                        fail_count += 0 if success else 1
                        processed += 1
                        
                        queue.put({
                            'type': 'file_progress',
                            'filepath': path,
                            'success': success,
                            'total_files': total_files,
                            'processed_files': processed,
                            'operation_id': operation_id,
                            'record_file': True,  # Added this flag
                            'parent_folder': os.path.dirname(path)  # Added parent folder
                        })
                        
                    except Exception as e:
                        logging.error(f"Failed to restore file {path}: {e}")
                        fail_count += 1
                        queue.put({
                            'type': 'file_progress',
                            'filepath': path,
                            'success': False,
                            'error': str(e),
                            'total_files': total_files,
                            'processed_files': processed,
                            'operation_id': operation_id,
                            'record_file': True,  # Added this flag
                            'parent_folder': os.path.dirname(path)  # Added parent folder
                        })
                        
                else:  # Directory
                    for root, _, files in os.walk(path):
                        if should_stop.value:
                            break
                        for file in files:
                            if should_stop.value:
                                break
                            file_path = os.path.join(root, file)
                            try:
                                normalized_path = file_path.replace('\\', '/')
                                success = restore_utils.restore_file(
                                    normalized_path,
                                    settings['API_KEY'],
                                    settings['AGENT_ID'],
                                    settings['SECRET_KEY']
                                )
                                success_count += 1 if success else 0
                                fail_count += 0 if success else 1
                                processed += 1
                                
                                queue.put({
                                    'type': 'file_progress',
                                    'filepath': normalized_path,
                                    'success': success,
                                    'total_files': total_files,
                                    'processed_files': processed,
                                    'operation_id': operation_id,
                                    'record_file': True,  # Added this flag
                                    'parent_folder': path  # Using original path as parent folder
                                })
                                
                            except Exception as e:
                                logging.error(f"Failed to restore file {file_path}: {e}")
                                fail_count += 1
                                queue.put({
                                    'type': 'file_progress',
                                    'filepath': normalized_path,
                                    'success': False,
                                    'error': str(e),
                                    'total_files': total_files,
                                    'processed_files': processed,
                                    'operation_id': operation_id,
                                    'record_file': True,  # Added this flag
                                    'parent_folder': path  # Using original path as parent folder
                                })
            
            queue.put({
                'type': 'operation_complete',
                'success_count': success_count,
                'fail_count': fail_count,
                'total': total_files,
                'operation_id': operation_id
            })
            
        except Exception as e:
            logging.error(f"Restore worker failed: {e}")
            queue.put({
                'type': 'operation_failed',
                'error': str(e),
                'operation_id': operation_id
            })

class OperationProgressWidget(QWidget):
    """Widget to display backup/restore operation progress"""
    operation_completed = pyqtSignal(dict)  # Emits final status when complete
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_manager = parent.theme_manager if parent else None
        self.history_manager = None  # Will be set by FileExplorerPanel
        self.init_ui()
        self.background_op = None
        self.timer = None

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Progress information
        info_layout = QHBoxLayout()
        self.operation_label = QLabel("Operation: None")
        self.file_count_label = QLabel("Files: 0/0")
        info_layout.addWidget(self.operation_label)
        info_layout.addWidget(self.file_count_label)
        info_layout.addStretch()
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_operation)
        self.cancel_button.setFixedWidth(70)
        info_layout.addWidget(self.cancel_button)
        
        layout.addLayout(info_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        # Current file label
        self.current_file_label = QLabel()
        self.current_file_label.setWordWrap(True)
        layout.addWidget(self.current_file_label)

        self.setVisible(False)
        self.apply_theme()

    def apply_theme(self):
        if not self.theme_manager:
            return
            
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        self.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_primary']};
            }}
            QProgressBar {{
                border: 1px solid {theme['input_border']};
                border-radius: 3px;
                text-align: center;
                background-color: {theme['panel_background']};
            }}
            QProgressBar::chunk {{
                background-color: {theme['accent_color']};
            }}
        """)

    def start_operation(self, operation_type, paths, settings):
        """Start a new backup/restore operation"""
        self.background_op = BackgroundOperation(operation_type, paths, settings)
        self.background_op.start()
        
        self.operation_label.setText(f"Operation: {operation_type.capitalize()}")
        self.progress_bar.setValue(0)
        self.current_file_label.setText("Preparing...")
        self.setVisible(True)
        
        # Start progress update timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_progress)
        self.timer.start(100)  # Update every 100ms

    def update_progress(self):
        """Update progress display from background operation"""
        if not self.background_op:
            return
        
        try:
            for progress in self.background_op.get_progress():
                progress_type = progress.get('type')
                operation_id = progress.get('operation_id')
                
                if not operation_id:
                    continue

                # Handle file progress updates
                if progress_type == 'file_progress':
                    if progress.get('record_file', False) and self.history_manager:
                        filepath = progress['filepath'].replace('\\', '/')
                        status = OperationStatus.SUCCESS if progress.get('success', False) else OperationStatus.FAILED
                        
                        self.history_manager.add_file_to_operation(
                            operation_id,
                            filepath,
                            status,
                            progress.get('error')
                        )
                    
                    # Update progress bar if we have total files
                    if progress.get('total_files') and progress.get('processed_files'):
                        percentage = (progress['processed_files'] / progress['total_files']) * 100
                        self.progress_bar.setValue(int(percentage))
                    
                    # Update current file label
                    if 'filepath' in progress:
                        if progress.get('parent_folder'):
                            parent_folder = os.path.basename(progress['parent_folder'])
                            filename = os.path.basename(progress['filepath'])
                            self.current_file_label.setText(
                                f"Processing: {parent_folder}/{filename}"
                            )
                        else:
                            self.current_file_label.setText(
                                f"Processing: {os.path.basename(progress['filepath'])}"
                            )
                        
                    # Update file count label
                    if progress.get('total_files'):
                        self.file_count_label.setText(
                            f"Files: {progress.get('processed_files', 0)}/{progress['total_files']}"
                        )

                # Handle operation completion
                elif progress_type == 'operation_complete' and self.history_manager:
                    # The operation's status has already been updated by the file processing
                    # We just need to emit completion signal - don't create a new history entry
                    self.operation_completed.emit({
                        'success_count': progress.get('success_count', 0),
                        'fail_count': progress.get('fail_count', 0),
                        'total': progress.get('total', 0),
                        'operation_type': self.background_op.operation_type
                    })
                    self.cleanup()
                    
                # Handle operation failure
                elif progress_type == 'operation_failed' and self.history_manager:
                    self.history_manager.complete_operation(
                        operation_id,
                        OperationStatus.FAILED,
                        progress.get('error')
                    )
                    
                    self.operation_completed.emit({
                        'error': progress.get('error', 'Operation failed'),
                        'operation_type': self.background_op.operation_type
                    })
                    self.cleanup()
                    
        except Exception as e:
            logging.error(f"Error updating progress: {e}", exc_info=True)
            self.cleanup()

    def cancel_operation(self):
        """Cancel the current operation"""
        if self.background_op:
            operation_type = self.background_op.operation_type
            operation_id = self.background_op.operation_id
            
            # Stop the background operation
            self.background_op.stop()
            
            # Recalculate final status based on completed files
            if self.history_manager:
                event = self.history_manager.get_operation(operation_id)
                if event:
                    completed_files = [f for f in event.files 
                                     if f.status != OperationStatus.IN_PROGRESS]
                    if completed_files:
                        # Determine final status based on completed files
                        final_status = (OperationStatus.FAILED 
                                      if any(f.status == OperationStatus.FAILED for f in completed_files)
                                      else OperationStatus.SUCCESS)
                        
                        # Update the operation's status
                        self.history_manager.complete_operation(
                            operation_id,
                            final_status,
                            "Operation cancelled by user"
                        )
                    else:
                        # No files completed, mark as failed
                        self.history_manager.complete_operation(
                            operation_id,
                            OperationStatus.FAILED,
                            "Operation cancelled by user before any files were processed"
                        )
            
            self.operation_completed.emit({
                'error': 'Operation cancelled by user',
                'operation_type': operation_type
            })
            self.cleanup()

    def cleanup(self):
        """Clean up after operation completes"""
        if self.timer:
            self.timer.stop()
            self.timer = None
            
        if self.background_op:
            self.background_op.stop()
            self.background_op = None
            
        self.setVisible(False)

class OutlookStyleEmailPreview(QWidget):
    def __init__(self, theme_manager, settings_path=None):
        super().__init__()
        self.theme_manager = theme_manager
        self.settings_path = settings_path
        self.init_ui()
        self.load_email_template()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Header section
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        title_label = QLabel("Reminder Email")
        title_label.setObjectName("email-header-title")
        
        save_button = QPushButton("Save Template")
        save_button.setObjectName("email-save-button")
        save_button.clicked.connect(self.save_email_template)
        
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(save_button)
        
        layout.addWidget(header)
        
        # Email header section
        email_section = QWidget()
        email_section.setObjectName("email-header")
        email_layout = QVBoxLayout(email_section)
        email_layout.setSpacing(8)
        
        # Subject field with label
        subject_container = QWidget()
        subject_layout = QHBoxLayout(subject_container)
        subject_layout.setContentsMargins(0, 0, 0, 0)
        subject_layout.setSpacing(10)  # Add spacing between label and field
        
        subject_label = QLabel("Subject:")
        subject_label.setObjectName("email-field-label")
        subject_label.setFixedWidth(80)  # Increased width for labels
        subject_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # Right-align the text
        
        self.subject_field = QLineEdit()
        self.subject_field.setObjectName("email-field")
        
        subject_layout.addWidget(subject_label)
        subject_layout.addWidget(self.subject_field)
        email_layout.addWidget(subject_container)
        
        # Add separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setObjectName("email-separator")
        email_layout.addWidget(separator)
        
        layout.addWidget(email_section)
        
        # Message section
        message_container = QWidget()
        message_layout = QHBoxLayout(message_container)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(10)  # Add spacing between label and field
        
        message_label = QLabel("Message:")
        message_label.setObjectName("email-field-label")
        message_label.setFixedWidth(80)  # Increased width for labels
        message_label.setAlignment(Qt.AlignRight | Qt.AlignTop)  # Right-align and top-align the text
        
        self.body = QTextEdit()
        self.body.setObjectName("email-field")
        
        message_layout.addWidget(message_label)
        message_layout.addWidget(self.body)
        layout.addWidget(message_container)
        
        self.apply_styles()
        
    def apply_styles(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #333333;
            }
            
            QLabel#email-header-title {
                color: #e8eaed;
                font-size: 16px;
                font-weight: bold;
                padding: 5px 0;
            }
            
            QPushButton#email-save-button {
                background-color: #4285F4;
                color: white;
                border: none;
                padding: 5px 15px;
                border-radius: 3px;
                min-width: 100px;
            }
            
            QPushButton#email-save-button:hover {
                background-color: #5294FF;
            }
            
            QPushButton#email-save-button:pressed {
                background-color: #3275E4;
            }
            
            QLabel#email-field-label {
                color: #e8eaed;
                font-weight: bold;
                padding-right: 5px;
            }
            
            QLineEdit#email-field, QTextEdit#email-field {
                background-color: #424242;
                border: 1px solid #666666;
                border-radius: 3px;
                color: #e8eaed;
                padding: 5px;
                margin: 10px;
            }
            
            QLineEdit#email-field:focus, QTextEdit#email-field:focus {
                border: 1px solid #4285F4;
                background-color: #484848;
            }
            
            QFrame#email-separator {
                color: #666666;
                margin-top: 5px;
                margin-bottom: 5px;
            }
        """)
        
    def save_email_template(self):
        if not self.settings_path or not os.path.exists(self.settings_path):
            StormcloudMessageBox.critical(self, "Error", "Settings file not found.")
            return
            
        try:
            with open(self.settings_path, 'r') as f:
                settings = f.read().splitlines()
            
            # Find Email section or find where to insert it
            email_index = -1
            backup_schedule_index = -1
            
            for i, line in enumerate(settings):
                if line.strip() == "Email:":
                    email_index = i
                elif line.strip() == "BACKUP_SCHEDULE:":
                    backup_schedule_index = i
            
            # Format subject and message with double quotes
            subject_str = f'"{self.subject_field.text()}"'
            message_lines = self.body.toPlainText().splitlines()
            message_list_str = str(message_lines).replace("'", '"')  # Use double quotes for consistency
            
            new_email_settings = [
                "Email:",
                f"  Subject: {subject_str}",
                f"  Message: {message_list_str}"
            ]
            
            if email_index >= 0:
                # Remove old email settings
                while email_index + 1 < len(settings) and settings[email_index + 1].startswith("  "):
                    settings.pop(email_index + 1)
                # Insert new settings
                for i, line in enumerate(new_email_settings[1:], 1):
                    settings.insert(email_index + i, line)
            else:
                # Insert before BACKUP_SCHEDULE if it exists, otherwise append
                if backup_schedule_index >= 0:
                    for i, line in enumerate(new_email_settings):
                        settings.insert(backup_schedule_index + i, line)
                    settings.insert(backup_schedule_index + len(new_email_settings), "")  # Add blank line
                else:
                    settings.extend([""] + new_email_settings)  # Add blank line before section
            
            # Write updated settings back to file
            with open(self.settings_path, 'w') as f:
                f.write('\n'.join(settings))
                
            StormcloudMessageBox.information(self, "Success", "Email template saved successfully!")
            
        except Exception as e:
            logging.error('Failed to save email template: %s', e)
            StormcloudMessageBox.critical(self, "Error", f"Failed to save email template: {str(e)}")

    def load_email_template(self):
        if not self.settings_path or not os.path.exists(self.settings_path):
            return
            
        try:
            with open(self.settings_path, 'r') as f:
                settings = f.read().splitlines()
            
            in_email_section = False
            for line in settings:
                stripped_line = line.strip()
                if stripped_line == "Email:":
                    in_email_section = True
                elif in_email_section and stripped_line.startswith("Subject:"):
                    # Parse the quoted subject string
                    try:
                        subject_str = stripped_line[8:].strip()
                        subject = eval(subject_str)  # This will handle the quoted string
                        self.subject_field.setText(subject)
                    except Exception as e:
                        logging.error(f"Failed to parse subject string: {str(e)}")
                elif in_email_section and stripped_line.startswith("Message:"):
                    # Extract the list string and convert it back to a list
                    try:
                        message_list_str = stripped_line[8:].strip()
                        message_list = eval(message_list_str)
                        self.body.setPlainText('\n'.join(message_list))
                    except Exception as e:
                        logging.error(f"Failed to parse message list: {str(e)}")
                elif in_email_section and not stripped_line.startswith(" "):
                    break
                    
        except Exception as e:
            logging.error(f"Failed to load email template: {str(e)}")

class EmailPreviewWidget(QWidget):
    def __init__(self, theme_manager):
        super().__init__()
        self.theme_manager = theme_manager
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Email preview using QTextEdit with HTML
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet("""
            QTextEdit {
                background-color: #FFFFFF;
                border: 1px solid #dadce0;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.preview)
        
    def update_preview(self, customer_name, amount, due_date, days_overdue):
        email_html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <!-- Email Header -->
            <div style="background-color: #1a73e8; color: white; padding: 20px; border-radius: 4px 4px 0 0;">
                <h2 style="margin: 0;">Dark Age Medical</h2>
                <p style="margin: 5px 0 0 0;">Payment Reminder</p>
            </div>
            
            <!-- Email Body -->
            <div style="padding: 20px; background-color: white; border: 1px solid #dadce0; border-top: none; border-radius: 0 0 4px 4px;">
                <p>Dear {customer_name},</p>
                
                <p>This is a friendly reminder that payment of {amount} was due on {due_date} ({days_overdue} days ago).</p>
                
                <div style="background-color: #f8f9fa; border-left: 4px solid #1a73e8; padding: 15px; margin: 20px 0;">
                    <table style="width: 100%;">
                        <tr>
                            <td style="padding: 5px;"><strong>Amount Due:</strong></td>
                            <td style="padding: 5px;">{amount}</td>
                        </tr>
                        <tr>
                            <td style="padding: 5px;"><strong>Due Date:</strong></td>
                            <td style="padding: 5px;">{due_date}</td>
                        </tr>
                        <tr>
                            <td style="padding: 5px;"><strong>Days Overdue:</strong></td>
                            <td style="padding: 5px; color: #DC3545;">{days_overdue}</td>
                        </tr>
                    </table>
                </div>
                
                <p>Please process this payment at your earliest convenience. If you have already sent this payment, please disregard this reminder.</p>
                
                <p>If you have any questions or concerns, please don't hesitate to contact us.</p>
                
                <div style="margin-top: 30px;">
                    <p style="margin: 0;">Best regards,</p>
                    <p style="margin: 0;"><strong>Dark Age Medical</strong></p>
                </div>
            </div>
            
            <!-- Footer -->
            <div style="padding: 20px; text-align: center; color: #5f6368; font-size: 12px;">
                <p>This is an automated reminder from Dark Age Medical.</p>
                <p>Please do not reply to this email.</p>
            </div>
        </div>
        """
        self.preview.setHtml(email_html)

class EmailConfig:
    def __init__(self):
        self.smtp_server = "smtp.office365.com"  # Default to Office 365
        self.smtp_port = 587  # Default TLS port
        self.from_email = ""
        self.smtp_password = ""
        
    def is_configured(self):
        return bool(self.from_email and self.smtp_password)

class EmailSetupDialog(QDialog):
    def __init__(self, parent=None, email_config=None):
        super().__init__(parent)
        self.email_config = email_config
        self.setWindowTitle("Email Configuration")
        self.setup_ui()
        
    def setup_ui(self):
        layout = QFormLayout(self)
        
        # From Email
        self.from_email = QLineEdit()
        if self.email_config and self.email_config.from_email:
            self.from_email.setText(self.email_config.from_email)
        layout.addRow("From Email:", self.from_email)
        
        # Password
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        if self.email_config and self.email_config.smtp_password:
            self.password.setText(self.email_config.smtp_password)
        layout.addRow("Password:", self.password)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)
        
    def get_config(self):
        return {
            'from_email': self.from_email.text(),
            'password': self.password.text()
        }

class StormcloudMessageBox(QMessageBox):
    def __init__(self, parent=None, theme_manager=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.setWindowTitle("Stormcloud")
        self.apply_theme()

    def apply_theme(self):
        if self.theme_manager:
            theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
            self.setStyleSheet(theme["stylesheet"])

    @staticmethod
    def information(parent, title, text, theme_manager=None):
        msg_box = StormcloudMessageBox(parent, theme_manager)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText(text)
        msg_box.setWindowTitle(title)
        msg_box.setStandardButtons(QMessageBox.Ok)
        return msg_box.exec_()

    @staticmethod
    def critical(parent, title, text, theme_manager=None):
        msg_box = StormcloudMessageBox(parent, theme_manager)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setText(text)
        msg_box.setWindowTitle(title)
        msg_box.setStandardButtons(QMessageBox.Ok)
        return msg_box.exec_()

@dataclass
class Transaction:
    id: str
    date: datetime
    amount: float
    status: str
    customer_name: str
    description: str
    payment_method: str
    
@dataclass
class OutstandingBill:
    id: str
    customer_name: str
    amount: float
    due_date: datetime
    description: str
    days_overdue: int
    status: str  # 'pending', 'reminder_sent', 'overdue'
        
class PaymentProcessingTab(QWidget):
    def __init__(self, parent, theme_manager):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.parent = parent
        self.stripe = None
        self.email_config = EmailConfig()
        self.init_ui()
        self.load_settings()
        self.load_mock_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # API Key Setup Section
        api_group = QGroupBox("Stripe Configuration")
        api_group.setProperty("class", "payment-group-box")
        api_layout = QHBoxLayout()
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Enter Stripe Secret Key (Demo Mode Enabled)")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        
        self.connect_button = QPushButton("Connect to Stripe")
        self.connect_button.setObjectName("payment-stripe-connect")
        self.connect_button.clicked.connect(self.connect_stripe)
        
        api_layout.addWidget(self.api_key_input)
        api_layout.addWidget(self.connect_button)
        api_group.setLayout(api_layout)
        layout.addWidget(api_group)

        # Main Content Area with Fixed Width Panels
        content_layout = QHBoxLayout()
        content_layout.setSpacing(10)  # Add spacing between panels
        
        # Calculate initial widths (minimum 400px)
        initial_width = max(400, int(self.window().width() * 0.48))  # Use 48% to account for margins/spacing
        
        # Left Side - Recent Transactions (Fixed 50% width)
        transactions_container = QWidget()
        transactions_container.setFixedWidth(initial_width)
        transactions_layout = QVBoxLayout(transactions_container)
        transactions_layout.setContentsMargins(0, 0, 0, 0)
        
        transactions_group = QGroupBox("Recent Transactions")
        transactions_inner_layout = QVBoxLayout()
        
        # Transaction search and filters
        transactions_search_layout = QHBoxLayout()
        self.transactions_search = QLineEdit()
        self.transactions_search.setObjectName("SearchBox")
        self.transactions_search.setPlaceholderText("Search transactions...")
        self.transactions_search.textChanged.connect(self.filter_transactions)
        transactions_search_layout.addWidget(self.transactions_search)
        
        # Transaction filters in same row as search
        self.date_range = QComboBox()
        self.date_range.addItems(["All Time", "Last 24 Hours", "Last 7 Days", "Last 30 Days"])
        self.date_range.currentTextChanged.connect(self.filter_transactions)
        
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All Statuses", "Succeeded", "Failed", "Pending"])
        self.status_filter.currentTextChanged.connect(self.filter_transactions)
        
        transactions_search_layout.addWidget(QLabel("Date Range:"))
        transactions_search_layout.addWidget(self.date_range)
        transactions_search_layout.addWidget(QLabel("Status:"))
        transactions_search_layout.addWidget(self.status_filter)
        
        transactions_inner_layout.addLayout(transactions_search_layout)
        
        # Transaction summaries
        summary_layout = QHBoxLayout()
        self.succeeded_total = QLabel("Succeeded: $0.00")
        self.succeeded_total.setObjectName("payment-success-summary")
        self.pending_total = QLabel("Pending: $0.00")
        self.pending_total.setObjectName("payment-pending-summary")
        self.failed_total = QLabel("Failed: $0.00")
        self.failed_total.setObjectName("payment-failed-summary")
        summary_layout.addWidget(self.succeeded_total)
        summary_layout.addWidget(self.pending_total)
        summary_layout.addWidget(self.failed_total)
        transactions_inner_layout.addLayout(summary_layout)
        
        # Transactions table
        self.transactions_table = QTableWidget()
        self.transactions_table.setProperty("class", "payment-table")
        self.transactions_table.setColumnCount(6)
        self.transactions_table.setHorizontalHeaderLabels([
            "Date", "Customer", "Amount", "Status", "Method", "Description"
        ])
        self.transactions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.transactions_table.setAlternatingRowColors(True)
        transactions_inner_layout.addWidget(self.transactions_table)
        
        transactions_group.setLayout(transactions_inner_layout)
        transactions_layout.addWidget(transactions_group)
        content_layout.addWidget(transactions_container)
        
        # Right Side - Outstanding Bills (Fixed 50% width)
        bills_container = QWidget()
        bills_container.setFixedWidth(initial_width)
        bills_layout = QVBoxLayout(bills_container)
        bills_layout.setContentsMargins(0, 0, 0, 0)
        
        bills_group = QGroupBox("Outstanding Bills")
        bills_inner_layout = QVBoxLayout()
        
        # Create vertical splitter for bills panels
        bills_splitter = QSplitter(Qt.Vertical)
        bills_splitter.setChildrenCollapsible(False)  # Prevent panels from being collapsed
        
        # Top panel - Bills list
        bills_top_panel = QWidget()
        bills_top_layout = QVBoxLayout(bills_top_panel)
        bills_top_layout.setContentsMargins(0, 0, 0, 0)
        
        # Bills search and summary
        bills_search_layout = QHBoxLayout()
        self.bills_search = QLineEdit()
        self.bills_search.setObjectName("SearchBox")
        self.bills_search.setPlaceholderText("Search bills...")
        self.bills_search.textChanged.connect(self.filter_bills)
        bills_search_layout.addWidget(self.bills_search)
        bills_top_layout.addLayout(bills_search_layout)
        
        summary_layout = QHBoxLayout()
        self.total_outstanding = QLabel("Total Outstanding: $0.00")
        self.total_outstanding.setObjectName("payment-total-outstanding")
        self.overdue_count = QLabel("Overdue: 0")
        self.overdue_count.setObjectName("payment-overdue-count")
        summary_layout.addWidget(self.total_outstanding)
        summary_layout.addWidget(self.overdue_count)
        summary_layout.addStretch()
        bills_top_layout.addLayout(summary_layout)
        
        # Bills table
        self.bills_table = QTableWidget()
        self.bills_table.setProperty("class", "payment-table")
        self.bills_table.setColumnCount(5)
        self.bills_table.setHorizontalHeaderLabels([
            "Customer", "Amount", "Due Date", "Days Overdue", "Action"
        ])
        self.bills_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.bills_table.setAlternatingRowColors(True)
        self.bills_table.itemSelectionChanged.connect(self.update_email_preview)
        bills_top_layout.addWidget(self.bills_table)
        bills_splitter.addWidget(bills_top_panel)
        
        # Bottom panel - Email preview
        bills_bottom_panel = QWidget()
        bills_bottom_layout = QVBoxLayout(bills_bottom_panel)
        bills_bottom_layout.setContentsMargins(0, 0, 0, 0)
        
        # When creating the email preview, now pass the settings path
        self.email_preview = OutlookStyleEmailPreview(self.theme_manager)
        bills_bottom_layout.addWidget(self.email_preview)
        bills_splitter.addWidget(bills_bottom_panel)
        
        # Set initial sizes for the splitter (50/50 split)
        bills_splitter.setStretchFactor(0, 1)
        bills_splitter.setStretchFactor(1, 1)
        bills_inner_layout.addWidget(bills_splitter)
        
        # Action buttons
        action_layout = QHBoxLayout()
        self.config_email_btn = QPushButton("Configure Email")
        self.config_email_btn.setObjectName("payment-config-btn")
        self.config_email_btn.clicked.connect(self.configure_email)
        
        self.send_reminders_btn = QPushButton("Send All Reminders")
        self.send_reminders_btn.setObjectName("payment-all-reminders-btn")
        self.send_reminders_btn.clicked.connect(self.send_reminders)
        self.send_reminders_btn.setEnabled(False)
        
        self.export_bills_btn = QPushButton("Export to CSV")
        self.export_bills_btn.setObjectName("payment-export-btn")
        self.export_bills_btn.clicked.connect(self.export_bills)
        
        action_layout.addWidget(self.config_email_btn)
        action_layout.addWidget(self.send_reminders_btn)
        action_layout.addWidget(self.export_bills_btn)
        bills_inner_layout.addLayout(action_layout)
        
        bills_group.setLayout(bills_inner_layout)
        bills_layout.addWidget(bills_group)
        content_layout.addWidget(bills_container)
        
        layout.addLayout(content_layout)

        # Add resize event handler
        self.resizeEvent = self.on_resize

    def load_settings(self):
        """Load settings file path similar to backup functionality"""
        appdata_path = os.getenv('APPDATA')
        settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')
        
        if not os.path.exists(settings_path):
            logging.error('Settings file not found at %s', settings_path)
            StormcloudMessageBox.critical(self, 'Error', 'Settings file not found.')
            return

        with open(settings_path, 'r') as f:
            stable_settings = json.load(f)

        install_path = stable_settings.get('install_path', '').replace('\\', '/')
        self.settings_cfg_path = os.path.join(install_path, 'settings.cfg').replace('\\', '/')

        if not os.path.exists(self.settings_cfg_path):
            logging.error('Configuration file not found at %s', self.settings_cfg_path)
            StormcloudMessageBox.critical(self, 'Error', 'Configuration file not found in the installation directory.')
            return
            
        # Update email preview with settings path
        if hasattr(self, 'email_preview'):
            self.email_preview.settings_path = self.settings_cfg_path
            self.email_preview.load_email_template()

    def on_resize(self, event):
        """Handle window resize events"""
        # Calculate new width accounting for margins and spacing
        new_width = max(400, int(self.width() * 0.48))  # 48% of window width, minimum 400px
        
        # Find and resize the containers
        for child in self.findChildren(QWidget):
            if child.parent() == self:
                # Only adjust direct children that are containers
                if isinstance(child.layout(), QVBoxLayout):
                    child.setFixedWidth(new_width)
        
        # Always call the parent class's resizeEvent
        super().resizeEvent(event)

    def configure_email(self):
        """Configure email settings"""
        dialog = EmailSetupDialog(self, self.email_config)
        if dialog.exec_():
            config = dialog.get_config()
            self.email_config.from_email = config['from_email']
            self.email_config.smtp_password = config['password']
            self.send_reminders_btn.setEnabled(self.email_config.is_configured())
            StormcloudMessageBox.information(self, "Success", "Email configuration saved successfully!")

    def filter_transactions(self):
        """Filter transactions and update summary statistics"""
        search_text = self.transactions_search.text().lower()
        date_filter = self.date_range.currentText()
        status_filter = self.status_filter.currentText()
        
        # Initialize totals for each status
        totals = {
            'Succeeded': 0.0,
            'Pending': 0.0,
            'Failed': 0.0
        }
        
        for row in range(self.transactions_table.rowCount()):
            # Get each cell's QTableWidgetItem
            date_item = self.transactions_table.item(row, 0)
            customer_item = self.transactions_table.item(row, 1)
            amount_item = self.transactions_table.item(row, 2)
            status_item = self.transactions_table.item(row, 3)
            method_item = self.transactions_table.item(row, 4)
            desc_item = self.transactions_table.item(row, 5)
            
            # Verify we have all items
            if not all([date_item, customer_item, amount_item, status_item, method_item, desc_item]):
                continue
                
            # Build searchable text
            row_text = ' '.join([
                date_item.text(),
                customer_item.text(),
                amount_item.text(),
                status_item.text(),
                method_item.text(),
                desc_item.text()
            ]).lower()
            
            # Check each filter independently
            should_show = True
            
            # 1. Text search filter
            if search_text and search_text not in row_text:
                should_show = False
            
            # 2. Status filter (only if not "All Statuses")
            if should_show and status_filter != "All Statuses":
                if status_item.text() != status_filter:
                    should_show = False
                    
            # 3. Date filter (only if not "All Time")
            if should_show and date_filter != "All Time":
                try:
                    date = datetime.strptime(date_item.text(), "%Y-%m-%d %H:%M")
                    now = datetime.now()
                    
                    if date_filter == "Last 24 Hours":
                        if date < now - timedelta(days=1):
                            should_show = False
                    elif date_filter == "Last 7 Days":
                        if date < now - timedelta(days=7):
                            should_show = False
                    elif date_filter == "Last 30 Days":
                        if date < now - timedelta(days=30):
                            should_show = False
                except ValueError:
                    pass
            
            # Apply visibility
            self.transactions_table.setRowHidden(row, not should_show)
            
            # Update totals for visible rows
            if should_show:
                try:
                    amount = float(amount_item.text().replace('$', '').replace(',', ''))
                    status = status_item.text()
                    if status in totals:
                        totals[status] += amount
                except (ValueError, AttributeError):
                    pass
        
        # Update summary labels
        self.succeeded_total.setText(f"Succeeded: ${totals['Succeeded']:,.2f}")
        self.pending_total.setText(f"Pending: ${totals['Pending']:,.2f}")
        self.failed_total.setText(f"Failed: ${totals['Failed']:,.2f}")
        
    def filter_bills(self):
        """Filter bills based on search text and update summary"""
        search_text = self.bills_search.text().lower()
        
        for row in range(self.bills_table.rowCount()):
            show_row = True
            row_data = []
            
            # Collect all cell text in the row (excluding Action column)
            for col in range(self.bills_table.columnCount() - 1):
                item = self.bills_table.item(row, col)
                if item:
                    row_data.append(item.text().lower())
            
            # Show/hide row based on search
            if search_text and not any(search_text in text for text in row_data):
                show_row = False
            
            self.bills_table.setRowHidden(row, not show_row)
        
        # Update summary after filtering
        self.update_bill_summary()

    def is_date_in_range(self, date, range_text):
        """Check if date is within the selected range"""
        now = datetime.now()
        date = date.replace(tzinfo=None)  # Remove timezone for comparison
        
        if range_text == "Last 24 Hours":
            return now - timedelta(days=1) <= date <= now
        elif range_text == "Last 7 Days":
            return now - timedelta(days=7) <= date <= now
        elif range_text == "Last 30 Days":
            return now - timedelta(days=30) <= date <= now
        else:  # "All Time"
            return True

    def update_transaction_summary(self, visible_transactions):
        """Update transaction summary information"""
        total_amount = sum(float(t['amount'].replace('$', '')) for t in visible_transactions)
        successful_count = sum(1 for t in visible_transactions if t['status'] == 'Succeeded')
        
        # Could update summary labels here if you want to add them
        pass

    def set_table_item_style(self, item, status=None, priority=None):
        """Helper method to set table item colors directly"""
        font = QFont("Arial", -1)  # Default font
        
        if status:
            if status.lower() == 'succeeded':
                item.setForeground(QColor('#28A745'))  # payment_success
                font.setBold(True)
                item.setData(Qt.UserRole, "Succeeded")
            elif status.lower() == 'failed':
                item.setForeground(QColor('#DC3545'))  # payment_failed
                font.setBold(True)
                item.setData(Qt.UserRole, "Failed")
            elif status.lower() == 'pending':
                item.setForeground(QColor('#FFC107'))  # payment_pending
                font.setBold(True)
                item.setData(Qt.UserRole, "Pending")
        elif priority == "high":
            item.setForeground(QColor('#DC3545'))  # payment_high_priority
        else:
            item.setForeground(QColor('#e8eaed'))  # text_primary
        
        item.setFont(font)

    def update_email_preview(self):
        """Update email preview when bill selection changes"""
        selected_items = self.bills_table.selectedItems()
        if selected_items:
            row = selected_items[0].row()
            customer_name = self.bills_table.item(row, 0).text()
            amount = self.bills_table.item(row, 1).text()
            due_date = self.bills_table.item(row, 2).text()
            days_overdue = self.bills_table.item(row, 3).text()
            
            self.email_preview.update_preview(
                customer_name,
                amount,
                due_date,
                days_overdue
            )

    def connect_stripe(self):
        """Handle Stripe connection attempt"""
        api_key = self.api_key_input.text()
        if not api_key:
            StormcloudMessageBox.critical(self, "Error", "Please enter your Stripe API key.")
            return
            
        # In demo mode, just show a success message
        self.stripe = True  # Simulate connection
        self.status_label.setText("Connected to Stripe (Demo Mode)")
        self.load_mock_data()

    def send_reminders(self):
        """Send reminders for all overdue bills"""
        if not self.email_config.is_configured():
            StormcloudMessageBox.critical(self, "Error", "Please configure email settings first.")
            return
            
        sent_count = 0
        error_count = 0
        
        for row in range(self.bills_table.rowCount()):
            if not self.bills_table.isRowHidden(row):
                days_overdue = int(self.bills_table.item(row, 3).text())
                if days_overdue > 0:
                    customer_name = self.bills_table.item(row, 0).text()
                    amount = self.bills_table.item(row, 1).text()
                    due_date = self.bills_table.item(row, 2).text()
                    
                    # Create default reminder content
                    email_content = {
                        'subject': f"Payment Reminder - Invoice {amount} Due",
                        'message': f"""Dear {customer_name},

This is a friendly reminder that payment of {amount} was due on {due_date} ({days_overdue} days ago).

Please process this payment at your earliest convenience. If you have already sent this payment, please disregard this reminder.

If you have any questions or concerns, please don't hesitate to contact us.

Best regards,
Dark Age Medical"""
                    }
                    
                    try:
                        self.send_reminder_email(customer_name, email_content)
                        sent_count += 1
                    except Exception as e:
                        error_count += 1
                        logging.error(f"Failed to send reminder to {customer_name}: {str(e)}")
        
        message = f"Successfully sent {sent_count} reminders."
        if error_count > 0:
            message += f"\nFailed to send {error_count} reminders. Check the log for details."
        
        StormcloudMessageBox.information(self, "Reminder Status", message)

    def send_single_reminder(self, bill):
        """Send a reminder for a specific bill"""
        if not self.email_config.is_configured():
            StormcloudMessageBox.critical(self, "Error", "Please configure email settings first.")
            return
        
        # Calculate days overdue
        days_overdue = self.calculate_days_overdue(bill['due_date'])
        
        # Update email preview with bill details
        self.email_preview.update_preview(
            bill['customer'],
            bill['amount'],
            bill['due_date'],
            days_overdue
        )
        
        try:
            email_content = self.email_preview.get_email_content()
            self.send_reminder_email(bill['email'], email_content)
            StormcloudMessageBox.information(
                self,
                "Success",
                f"Payment reminder sent to {bill['customer']}"
            )
        except Exception as e:
            StormcloudMessageBox.critical(
                self,
                "Error",
                f"Failed to send reminder: {str(e)}"
            )

    def send_reminder_email(self, customer_name, email_content):
        """Send actual email via SMTP"""
        # In real implementation, you would:
        # 1. Look up customer's email from your database
        # 2. Create and send the actual email
        
        # For demo purposes, we'll simulate sending
        customer_email = f"{customer_name.lower().replace(' ', '.')}@example.com"
        
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_config.from_email
            msg['To'] = customer_email
            msg['Subject'] = email_content['subject']
            msg.attach(MIMEText(email_content['message'], 'plain'))
            
            with smtplib.SMTP(self.email_config.smtp_server, self.email_config.smtp_port) as server:
                server.starttls()
                server.login(self.email_config.from_email, self.email_config.smtp_password)
                server.send_message(msg)
                
        except Exception as e:
            logging.error(f"Failed to send email: {str(e)}")
            raise

    def export_bills(self):
        """Export outstanding bills to CSV"""
        try:
            file_path, _ = QFileDialog.getSaveFileName(
                self, 
                "Save Bills Report", 
                "outstanding_bills.csv", 
                "CSV Files (*.csv)"
            )
            if file_path:
                with open(file_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Customer", "Amount", "Due Date", "Days Overdue"])
                    
                    for row in range(self.bills_table.rowCount()):
                        writer.writerow([
                            self.bills_table.item(row, 0).text(),
                            self.bills_table.item(row, 1).text(),
                            self.bills_table.item(row, 2).text(),
                            self.bills_table.item(row, 3).text()
                        ])
                        
                StormcloudMessageBox.information(
                    self, 
                    "Success", 
                    f"Bills exported successfully to {file_path}"
                )
        except Exception as e:
            StormcloudMessageBox.critical(
                self, 
                "Error", 
                f"Failed to export bills: {str(e)}"
            )

    def populate_transactions_table(self, transactions):
        """Populate transactions table with data"""
        self.transactions_table.setRowCount(0)
        
        for transaction in transactions:
            row = self.transactions_table.rowCount()
            self.transactions_table.insertRow(row)
            
            # Date
            date_item = QTableWidgetItem(transaction['date'])
            self.set_table_item_style(date_item)
            self.transactions_table.setItem(row, 0, date_item)
            
            # Customer
            customer_item = QTableWidgetItem(transaction['customer'])
            customer_item.setToolTip('Click to view patient details')
            self.set_table_item_style(customer_item)
            self.transactions_table.setItem(row, 1, customer_item)
            
            # Amount
            amount_item = QTableWidgetItem(transaction['amount'])
            self.set_table_item_style(amount_item)
            self.transactions_table.setItem(row, 2, amount_item)
            
            # Status
            status_item = QTableWidgetItem(transaction['status'])
            self.set_table_item_style(status_item, status=transaction['status'])
            self.transactions_table.setItem(row, 3, status_item)
            
            # Method
            method_item = QTableWidgetItem(transaction['method'])
            self.set_table_item_style(method_item)
            self.transactions_table.setItem(row, 4, method_item)
            
            # Description
            desc_item = QTableWidgetItem(transaction['description'])
            self.set_table_item_style(desc_item)
            self.transactions_table.setItem(row, 5, desc_item)
        
        # Update transaction totals after populating
        self.filter_transactions()

    def populate_bills_table(self, bills):
        """Populate bills table with data"""
        self.bills_table.setRowCount(0)
        
        for bill in bills:
            row = self.bills_table.rowCount()
            self.bills_table.insertRow(row)
            
            # Customer name
            customer_item = QTableWidgetItem(bill['customer'])
            self.set_table_item_style(customer_item)  # No priority specified, uses default style
            self.bills_table.setItem(row, 0, customer_item)
            
            # Amount (remove the extra $ since it's in the data)
            amount_str = bill['amount'].replace('$', '')  # Remove $ if present in the data
            amount_item = QTableWidgetItem(f"${amount_str}")
            self.set_table_item_style(amount_item)  # No priority specified, uses default style
            self.bills_table.setItem(row, 1, amount_item)
            
            # Due date
            due_date_item = QTableWidgetItem(bill['due_date'])
            self.set_table_item_style(due_date_item)
            self.bills_table.setItem(row, 2, due_date_item)
            
            # Days overdue
            days_overdue = self.calculate_days_overdue(bill['due_date'])
            days_overdue_item = QTableWidgetItem(str(days_overdue))
            # Only apply high priority (red) styling to the days overdue column
            self.set_table_item_style(days_overdue_item, priority="high" if days_overdue > 0 else "normal")
            self.bills_table.setItem(row, 3, days_overdue_item)
            
            # Action button
            reminder_btn = QPushButton("Send Reminder")
            reminder_btn.setObjectName("payment-reminder-btn")
            reminder_btn.clicked.connect(lambda checked, b=bill: self.send_single_reminder(b))
            self.bills_table.setCellWidget(row, 4, reminder_btn)
        
        # Update summary after populating
        self.update_bill_summary()

    def calculate_days_overdue(self, due_date_str):
        """Calculate days overdue based on current date"""
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        days_overdue = (today - due_date).days
        return max(0, days_overdue)

    def calculate_bill_totals(self):
        """Calculate total outstanding and overdue count for visible bills"""
        total_outstanding = 0
        overdue_count = 0
        
        for row in range(self.bills_table.rowCount()):
            if not self.bills_table.isRowHidden(row):
                # Calculate total - Amount is in column 1
                amount_item = self.bills_table.item(row, 1)
                if amount_item:
                    try:
                        # Convert "$1,234.56" to float
                        amount_str = amount_item.text().replace('$', '').replace(',', '')
                        amount = float(amount_str)
                        total_outstanding += amount
                    except (ValueError, AttributeError):
                        logging.error(f"Failed to parse amount: {amount_item.text() if amount_item else 'None'}")
                
                # Count overdue - Days overdue is in column 3
                days_overdue_item = self.bills_table.item(row, 3)
                if days_overdue_item:
                    try:
                        if int(days_overdue_item.text()) > 0:
                            overdue_count += 1
                    except (ValueError, AttributeError):
                        logging.error(f"Failed to parse days overdue: {days_overdue_item.text() if days_overdue_item else 'None'}")
        
        return total_outstanding, overdue_count

    def update_bill_summary(self):
        """Update the bills summary labels"""
        total_outstanding, overdue_count = self.calculate_bill_totals()
        self.total_outstanding.setText(f"Total Outstanding: ${total_outstanding:,.2f}")
        self.overdue_count.setText(f"Overdue: {overdue_count}")

    def load_mock_data(self):
        """Load sample data for development"""
        # Mock transactions
        sample_transactions = [
            {
                'date': '2024-02-15 14:30',
                'customer': 'John Smith',
                'amount': '$150.00',
                'status': 'Succeeded',
                'method': 'Credit Card',
                'description': 'Dermatology Consultation'
            },
            {
                'date': '2024-02-15 11:20',
                'customer': 'Sarah Johnson',
                'amount': '$75.00',
                'status': 'Succeeded',
                'method': 'ACH Transfer',
                'description': 'Follow-up Visit'
            },
            {
                'date': '2024-02-14 16:45',
                'customer': 'Michael Brown',
                'amount': '$250.00',
                'status': 'Failed',
                'method': 'Credit Card',
                'description': 'Skin Treatment'
            },
            {
                'date': '2024-02-14 09:15',
                'customer': 'Emily Davis',
                'amount': '$180.00',
                'status': 'Pending',
                'method': 'Credit Card',
                'description': 'Acne Treatment'
            },
            {
                'date': '2024-02-13 15:30',
                'customer': 'Robert Wilson',
                'amount': '$200.00',
                'status': 'Succeeded',
                'method': 'HSA Card',
                'description': 'Skin Cancer Screening'
            }
        ]

        # Mock outstanding bills
        sample_bills = [
            {
                'customer': 'David Lee',
                'email': 'david.lee@example.com',
                'amount': '$320.00',
                'due_date': '2024-02-28',
                'high_priority': False
            },
            {
                'customer': 'Jennifer White',
                'email': 'jennifer.white@example.com',
                'amount': '$150.00',
                'due_date': '2024-02-01',
                'high_priority': True
            },
            {
                'customer': 'Thomas Anderson',
                'email': 'thomas.anderson@example.com',
                'amount': '$275.00',
                'due_date': '2024-02-10',
                'high_priority': True
            },
            {
                'customer': 'Lisa Martinez',
                'email': 'lisa.martinez@example.com',
                'amount': '$180.00',
                'due_date': '2024-03-05',
                'high_priority': False
            }
        ]

        self.populate_transactions_table(sample_transactions)
        self.populate_bills_table(sample_bills)

class MeetingSchedulerTab(QWidget):
    def __init__(self, parent, theme_manager):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.parent = parent
        self.users = {}
        self.meetings = []
        self.scheduler = None  # Will initialize when needed
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Settings panel
        settings_group = QGroupBox("Scheduler Settings")
        settings_layout = QFormLayout()
        
        # Days to schedule
        self.days_spinbox = QSpinBox()
        self.days_spinbox.setRange(1, 30)
        self.days_spinbox.setValue(10)
        settings_layout.addRow("Days to Schedule:", self.days_spinbox)
        
        # Time increment
        self.increment_combo = QComboBox()
        self.increment_combo.addItems(["15", "30", "45", "60"])
        settings_layout.addRow("Time Increment (minutes):", self.increment_combo)
        
        # Max meeting length
        self.max_length_combo = QComboBox()
        self.max_length_combo.addItems(["60", "90", "120", "180"])
        settings_layout.addRow("Max Meeting Length (minutes):", self.max_length_combo)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # User management
        user_group = QGroupBox("User Management")
        user_layout = QVBoxLayout()
        
        # User list
        self.user_table = QTableWidget()
        self.user_table.setColumnCount(4)
        self.user_table.setHorizontalHeaderLabels(["User ID", "Timezone", "Working Hours", "Team"])
        user_layout.addWidget(self.user_table)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.add_user_btn = QPushButton("Add User")
        self.add_user_btn.clicked.connect(self.add_user)
        self.remove_user_btn = QPushButton("Remove User")
        self.remove_user_btn.clicked.connect(self.remove_user)
        self.import_users_btn = QPushButton("Import Users")
        self.import_users_btn.clicked.connect(self.import_users)
        button_layout.addWidget(self.add_user_btn)
        button_layout.addWidget(self.remove_user_btn)
        button_layout.addWidget(self.import_users_btn)
        user_layout.addLayout(button_layout)
        
        user_group.setLayout(user_layout)
        layout.addWidget(user_group)
        
        # Meeting management
        meeting_group = QGroupBox("Meeting Management")
        meeting_layout = QVBoxLayout()
        
        # Meeting list
        self.meeting_table = QTableWidget()
        self.meeting_table.setColumnCount(4)
        self.meeting_table.setHorizontalHeaderLabels(["Length", "Invited Users", "Scheduled Time", "Status"])
        meeting_layout.addWidget(self.meeting_table)
        
        # Buttons
        meeting_button_layout = QHBoxLayout()
        self.add_meeting_btn = QPushButton("Add Meeting")
        self.add_meeting_btn.clicked.connect(self.add_meeting)
        self.remove_meeting_btn = QPushButton("Remove Meeting")
        self.remove_meeting_btn.clicked.connect(self.remove_meeting)
        self.import_meetings_btn = QPushButton("Import Meetings")
        self.import_meetings_btn.clicked.connect(self.import_meetings)
        self.schedule_btn = QPushButton("Schedule All Meetings")
        self.schedule_btn.clicked.connect(self.schedule_all_meetings)
        
        meeting_button_layout.addWidget(self.add_meeting_btn)
        meeting_button_layout.addWidget(self.remove_meeting_btn)
        meeting_button_layout.addWidget(self.import_meetings_btn)
        meeting_button_layout.addWidget(self.schedule_btn)
        meeting_layout.addLayout(meeting_button_layout)
        
        meeting_group.setLayout(meeting_layout)
        layout.addWidget(meeting_group)

    def add_user(self):
        dialog = AddUserDialog(self)
        if dialog.exec_():
            user_id, timezone, working_hours, team = dialog.get_user_data()
            self.add_user_to_table(user_id, timezone, working_hours, team)
            
            # Convert working hours string to WorkingHours object
            try:
                working_hours_obj = WorkingHours.from_string(working_hours)
            except ValueError as e:
                StormcloudMessageBox.critical(self, "Error", f"Invalid working hours format: {e}")
                return

            # Create Participant object
            self.users[int(user_id)] = Participant(
                user_id=str(user_id),
                role=ParticipantRole.REQUIRED,  # Default to required
                timezone=timezone,
                working_hours=working_hours_obj
            )

    def add_user_to_table(self, user_id, timezone, working_hours, team):
        row = self.user_table.rowCount()
        self.user_table.insertRow(row)
        self.user_table.setItem(row, 0, QTableWidgetItem(str(user_id)))
        self.user_table.setItem(row, 1, QTableWidgetItem(str(timezone)))
        self.user_table.setItem(row, 2, QTableWidgetItem(working_hours))
        self.user_table.setItem(row, 3, QTableWidgetItem(str(team)))

    def remove_user(self):
        selected_rows = self.user_table.selectedItems()
        if not selected_rows:
            return
            
        row = selected_rows[0].row()
        user_id = int(self.user_table.item(row, 0).text())
        self.user_table.removeRow(row)
        if user_id in self.users:
            del self.users[user_id]

    def import_users(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Users", "", "CSV Files (*.csv)")
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            working_hours = row['working_hours']
                            working_hours_obj = WorkingHours.from_string(working_hours)
                            
                            user_id = int(row['user_id'])
                            self.add_user_to_table(
                                user_id, 
                                row['timezone'], 
                                working_hours,
                                int(row['team_id'])
                            )
                            
                            self.users[user_id] = Participant(
                                user_id=str(user_id),
                                role=ParticipantRole.REQUIRED,
                                timezone=row['timezone'],
                                working_hours=working_hours_obj
                            )
                        except KeyError as ke:
                            raise ValueError(f"Missing required column: {ke}")
                        except ValueError as ve:
                            raise ValueError(f"Invalid data in row for user {row.get('user_id', 'unknown')}: {ve}")
            except Exception as e:
                StormcloudMessageBox.critical(self, "Error", f"Failed to import users: {str(e)}")

    def add_meeting(self):
        dialog = AddMeetingDialog(self, list(self.users.keys()))
        if dialog.exec_():
            length, invited_users = dialog.get_meeting_data()
            self.add_meeting_to_table(length, invited_users)
            
            # Add to meetings list
            invited_user_ids = invited_users.split('&')
            try:
                participants = [self.users[int(uid)] for uid in invited_user_ids]
                
                self.meetings.append(Meeting(
                    title=f"Meeting {len(self.meetings) + 1}",
                    duration=timedelta(minutes=length),
                    participants=participants,
                    earliest_start=datetime.now(pytz.UTC)
                ))
            except KeyError as ke:
                StormcloudMessageBox.critical(self, "Error", f"Unknown user ID: {ke}")
            except Exception as e:
                StormcloudMessageBox.critical(self, "Error", f"Failed to create meeting: {str(e)}")

    def add_meeting_to_table(self, length, invited_users):
        row = self.meeting_table.rowCount()
        self.meeting_table.insertRow(row)
        self.meeting_table.setItem(row, 0, QTableWidgetItem(str(length)))
        self.meeting_table.setItem(row, 1, QTableWidgetItem(invited_users))
        self.meeting_table.setItem(row, 2, QTableWidgetItem("Not scheduled"))
        self.meeting_table.setItem(row, 3, QTableWidgetItem("Pending"))

    def remove_meeting(self):
        selected_rows = self.meeting_table.selectedItems()
        if not selected_rows:
            return
            
        row = selected_rows[0].row()
        self.meeting_table.removeRow(row)
        if row < len(self.meetings):
            self.meetings.pop(row)

    def import_meetings(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Meetings", "", "CSV Files (*.csv)")
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            length = int(row['length'])
                            invited_users = row['invited']
                            self.add_meeting_to_table(length, invited_users)
                            
                            invited_user_ids = invited_users.split('&')
                            participants = []
                            for uid in invited_user_ids:
                                try:
                                    participants.append(self.users[int(uid)])
                                except KeyError:
                                    raise ValueError(f"Unknown user ID: {uid}")
                                except ValueError:
                                    raise ValueError(f"Invalid user ID format: {uid}")
                            
                            self.meetings.append(Meeting(
                                title=row.get('title', f"Meeting {len(self.meetings) + 1}"),
                                duration=timedelta(minutes=length),
                                participants=participants,
                                earliest_start=datetime.now(pytz.UTC)
                            ))
                        except KeyError as ke:
                            raise ValueError(f"Missing required column: {ke}")
                        except ValueError as ve:
                            raise ValueError(f"Invalid data in row: {ve}")
            except Exception as e:
                StormcloudMessageBox.critical(self, "Error", f"Failed to import meetings: {str(e)}")

    def schedule_all_meetings(self):
        if not self.users or not self.meetings:
            StormcloudMessageBox.critical(self, "Error", "Please add users and meetings first.")
            return
            
        try:
            # Initialize scheduler with default settings
            self.scheduler = (SchedulerBuilder()
                            .with_time_increment(timedelta(minutes=int(self.increment_combo.currentText())))
                            .build())
            
            # Schedule meetings
            scheduled_meetings = self.scheduler.schedule(self.meetings)
            
            # Update UI with results
            for idx, meeting in enumerate(scheduled_meetings):
                if meeting.scheduled_time:
                    self.meeting_table.setItem(
                        idx, 2, 
                        QTableWidgetItem(meeting.scheduled_time.start.strftime("%Y-%m-%d %H:%M"))
                    )
                    self.meeting_table.setItem(idx, 3, QTableWidgetItem("Scheduled"))
                else:
                    self.meeting_table.setItem(idx, 2, QTableWidgetItem("No available slot"))
                    self.meeting_table.setItem(idx, 3, QTableWidgetItem("Failed"))
            
            StormcloudMessageBox.information(self, "Success", "Meetings scheduled successfully!")
            
        except Exception as e:
            StormcloudMessageBox.critical(self, "Error", f"Failed to schedule meetings: {str(e)}")

# Add new OnCallSchedulerTab class
class OnCallSchedulerTab(QWidget):
    def __init__(self, parent, theme_manager):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.parent = parent
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Settings panel
        settings_group = QGroupBox("On-Call Settings")
        settings_layout = QFormLayout()
        
        # Schedule range
        self.days_spinbox = QSpinBox()
        self.days_spinbox.setRange(1, 365)  # Allow up to a year of scheduling
        self.days_spinbox.setValue(30)  # Default to monthly schedule
        settings_layout.addRow("Days to Schedule:", self.days_spinbox)
        
        # Shift duration
        self.shift_length_combo = QComboBox()
        self.shift_length_combo.addItems(["8", "12", "24"])
        settings_layout.addRow("Shift Length (hours):", self.shift_length_combo)
        
        # Minimum rest period
        self.rest_period_spinbox = QSpinBox()
        self.rest_period_spinbox.setRange(8, 48)
        self.rest_period_spinbox.setValue(12)
        settings_layout.addRow("Minimum Rest Period (hours):", self.rest_period_spinbox)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # Staff management
        staff_group = QGroupBox("Staff Management")
        staff_layout = QVBoxLayout()
        
        # Staff list
        self.staff_table = QTableWidget()
        self.staff_table.setColumnCount(5)
        self.staff_table.setHorizontalHeaderLabels([
            "Staff ID", 
            "Name", 
            "Role", 
            "Max Shifts/Week",
            "Preferred Days"
        ])
        staff_layout.addWidget(self.staff_table)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.add_staff_btn = QPushButton("Add Staff")
        self.add_staff_btn.clicked.connect(self.add_staff)
        self.remove_staff_btn = QPushButton("Remove Staff")
        self.remove_staff_btn.clicked.connect(self.remove_staff)
        self.import_staff_btn = QPushButton("Import Staff")
        self.import_staff_btn.clicked.connect(self.import_staff)
        button_layout.addWidget(self.add_staff_btn)
        button_layout.addWidget(self.remove_staff_btn)
        button_layout.addWidget(self.import_staff_btn)
        staff_layout.addLayout(button_layout)
        
        staff_group.setLayout(staff_layout)
        layout.addWidget(staff_group)
        
        # Schedule View
        schedule_group = QGroupBox("On-Call Schedule")
        schedule_layout = QVBoxLayout()
        
        # Calendar view for schedule
        self.schedule_calendar = OnCallCalendarView(self.theme_manager)
        schedule_layout.addWidget(self.schedule_calendar)
        
        # Schedule controls
        control_layout = QHBoxLayout()
        self.generate_schedule_btn = QPushButton("Generate Schedule")
        self.generate_schedule_btn.clicked.connect(self.generate_schedule)
        self.export_schedule_btn = QPushButton("Export Schedule")
        self.export_schedule_btn.clicked.connect(self.export_schedule)
        control_layout.addWidget(self.generate_schedule_btn)
        control_layout.addWidget(self.export_schedule_btn)
        schedule_layout.addLayout(control_layout)
        
        schedule_group.setLayout(schedule_layout)
        layout.addWidget(schedule_group)

    def add_staff(self):
        # TODO: Implement staff addition
        pass

    def remove_staff(self):
        # TODO: Implement staff removal
        pass

    def import_staff(self):
        # TODO: Implement staff import
        pass

    def generate_schedule(self):
        # TODO: Implement schedule generation
        pass

    def export_schedule(self):
        # TODO: Implement schedule export
        pass

class OnCallCalendarView(QCalendarWidget):
    def __init__(self, theme_manager):
        super().__init__()
        self.theme_manager = theme_manager
        self.setGridVisible(True)
        self.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.setSelectionMode(QCalendarWidget.NoSelection)
        
    def paintCell(self, painter, rect, date):
        super().paintCell(painter, rect, date)
        # TODO: Add custom painting for shifts

class AddUserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add User")
        self.init_ui()
        
    def init_ui(self):
        layout = QFormLayout(self)
        
        self.user_id = QSpinBox()
        self.user_id.setRange(1, 10000)
        layout.addRow("User ID:", self.user_id)
        
        self.timezone = QDoubleSpinBox()
        self.timezone.setRange(-12, 12)
        self.timezone.setDecimals(1)
        layout.addRow("Timezone (UTC offset):", self.timezone)
        
        self.working_hours = QLineEdit()
        self.working_hours.setPlaceholderText("8.5&17.5")
        layout.addRow("Working Hours (start&end):", self.working_hours)
        
        self.team = QSpinBox()
        self.team.setRange(1, 100)
        layout.addRow("Team ID:", self.team)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        
    def get_user_data(self):
        return (self.user_id.value(),
                self.timezone.value(),
                self.working_hours.text(),
                self.team.value())

class AddMeetingDialog(QDialog):
    def __init__(self, parent=None, available_users=None):
        super().__init__(parent)
        self.available_users = available_users or []
        self.setWindowTitle("Add Meeting")
        self.init_ui()
        
    def init_ui(self):
        layout = QFormLayout(self)
        
        self.length = QComboBox()
        self.length.addItems(['15', '30', '45', '60', '75', '90', '105', '120'])
        layout.addRow("Length (minutes):", self.length)
        
        self.user_list = QListWidget()
        self.user_list.setSelectionMode(QListWidget.MultiSelection)
        for user_id in self.available_users:
            self.user_list.addItem(str(user_id))
        layout.addRow("Select Users:", self.user_list)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        
    def get_meeting_data(self):
        selected_users = [item.text() for item in self.user_list.selectedItems()]
        return (int(self.length.currentText()),
                "&".join(selected_users))

class StormcloudApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.theme_manager = ThemeManager()
        self.setWindowTitle('Stormcloud Backup Manager')
        self.setGeometry(100, 100, 800, 600)
        self.backup_schedule = {'weekly': {}, 'monthly': {}}
        
        # Create systray at initialization
        systray_menu_options = (("Backup now", None, 
            lambda x: logging.info("User clicked 'Backup now'")),)
        self.systray = SysTrayIcon("stormcloud.ico", 
            "Stormcloud Backup Engine", systray_menu_options)
        self.systray.start()
        
        # Load settings and get install path first
        self.load_settings()
        self.install_path = self.get_install_path()
        
        # Initialize history manager after install path is set
        self.history_manager = HistoryManager(self.install_path)
        
        # Then initialize UI and other components
        self.set_app_icon()
        self.create_spinbox_arrow_icons()
        self.init_ui()
        self.update_status()
        self.load_backup_paths()
        self.load_properties()
        self.apply_backup_mode()
        self.apply_theme()

    def init_ui(self):
        central_widget = QWidget(self)
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Create toolbar
        toolbar = QToolBar()
        toolbar.setObjectName("mainToolBar")
        self.addToolBar(Qt.TopToolBarArea, toolbar)
        
        # Add theme selection to toolbar
        theme_label = QLabel("Theme:")
        toolbar.addWidget(theme_label)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark Age Classic Dark", "Light"])
        self.theme_combo.setCurrentText(self.theme_manager.current_theme)
        self.theme_combo.currentTextChanged.connect(self.change_theme)
        self.theme_combo.setFixedWidth(150)
        self.theme_combo.setCursor(Qt.PointingHandCursor)
        toolbar.addWidget(self.theme_combo)

        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.South)
        main_layout.addWidget(self.tab_widget)

        # Create and add tabs
        self.backup_tab = self.create_backup_tab()
        self.tab_widget.addTab(self.backup_tab, "💾 Backup")

        payment_tab = QWidget()
        self.setup_payment_tab(payment_tab)
        self.tab_widget.addTab(payment_tab, "💳 Payments")

        self.meeting_scheduler_tab = MeetingSchedulerTab(self, self.theme_manager)
        self.tab_widget.addTab(self.meeting_scheduler_tab, "📅 Schedule | 👥 Meetings")
        
        self.oncall_scheduler_tab = OnCallSchedulerTab(self, self.theme_manager)
        self.tab_widget.addTab(self.oncall_scheduler_tab, "📅 Schedule | 🏥 On-Call")

    def get_install_path(self):
        """Get Stormcloud installation path from stable settings"""
        try:
            appdata_path = os.getenv('APPDATA')
            stable_settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')
            
            if not os.path.exists(stable_settings_path):
                logging.error(f"Stable settings file not found at: {stable_settings_path}")
                return None
                
            with open(stable_settings_path, 'r') as f:
                stable_settings = json.load(f)
                install_path = stable_settings.get('install_path', '').replace('\\', '/')
                logging.info(f"Found installation path: {install_path}")
                return install_path
                
        except Exception as e:
            logging.error(f"Failed to get installation path: {e}")
            return None

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
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        
        # Create up arrow icon
        up_arrow = QPixmap(8, 8)
        up_arrow.fill(Qt.transparent)
        painter = QPainter(up_arrow)
        painter.setBrush(QColor(theme['text_primary']))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPoint(0, 6), QPoint(4, 2), QPoint(8, 6))
        painter.end()
        up_arrow.save(f'up-arrow-{self.theme_manager.current_theme.lower()}.png')

        # Create down arrow icon
        down_arrow = QPixmap(8, 8)
        down_arrow.fill(Qt.transparent)
        painter = QPainter(down_arrow)
        painter.setBrush(QColor(theme['text_primary']))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPoint(0, 2), QPoint(4, 6), QPoint(8, 2))
        painter.end()
        down_arrow.save(f'down-arrow-{self.theme_manager.current_theme.lower()}.png')

    def setup_backup_tab(self, tab):
        layout = QVBoxLayout(tab)
        
        # Header with Start Backup Engine button and Theme Selection
        header_widget = self.create_header_widget()
        layout.addWidget(header_widget)

        # Grid layout for panels
        grid_widget = QWidget()
        self.grid_layout = QGridLayout(grid_widget)
        self.setup_grid_layout()
        layout.addWidget(grid_widget)

    def setup_payment_tab(self, tab):
        layout = QVBoxLayout(tab)

        # Enhanced styles for the summary labels
        style = """
            QLabel#payment-success-summary {
                color: #28A745;  /* Green for success */
                font-weight: bold;
                font-size: 14px;
                margin: 5px;
            }
            
            QLabel#payment-pending-summary {
                color: #FFC107;  /* Yellow for pending */
                font-weight: bold;
                font-size: 14px;
                margin: 5px;
            }
            
            QLabel#payment-failed-summary {
                color: #DC3545;  /* Red for failed */
                font-weight: bold;
                font-size: 14px;
                margin: 5px;
            }
            
            /* Ensure these match the table status colors */
            QTableWidget QTableWidgetItem[status="Succeeded"] {
                color: #28A745;
                font-weight: bold;
            }
            
            QTableWidget QTableWidgetItem[status="Pending"] {
                color: #FFC107;
                font-weight: bold;
            }
            
            QTableWidget QTableWidgetItem[status="Failed"] {
                color: #DC3545;
                font-weight: bold;
            }
            
            QLabel#SubpanelHeader {
                font-size: 14px;
                font-weight: bold;
                color: #202124;
                padding: 5px 0;
                border-bottom: 1px solid #dadce0;
                margin-bottom: 10px;
            }
            
            QTextEdit {
                border: 1px solid #dadce0;
                border-radius: 4px;
                background-color: #ffffff;
                selection-background-color: #e8f0fe;
                selection-color: #1a73e8;
            }
            
            QSplitter::handle {
                height: 2px;
                background-color: #dadce0;
            }
            
            QSplitter::handle:hover {
                background-color: #1a73e8;
            }
        """
        tab.setStyleSheet(tab.styleSheet() + style)

        # Create and add the PaymentProcessingTab widget
        payment_processor = PaymentProcessingTab(self, self.theme_manager)
        layout.addWidget(payment_processor)

    def create_header_widget(self):
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        
        self.start_button = QPushButton('Start Backup Engine')
        self.start_button.setObjectName("start_button")
        self.start_button.setFixedSize(200, 40)
        self.start_button.clicked.connect(self.toggle_backup_engine)
        self.start_button.setCursor(Qt.PointingHandCursor)
        
        header_layout.addWidget(self.start_button)
        header_layout.addStretch()
        
        return header_widget

    def apply_theme(self):
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        self.setStyleSheet(theme["stylesheet"])
        
        # Apply specific styles that might not be covered by the general stylesheet
        self.status_value_text.setStyleSheet(f"color: {theme['status_running'] if self.is_backup_engine_running() else theme['status_not_running']};")
        
        # Update arrow icons for spinboxes
        self.create_spinbox_arrow_icons()
        
        # Refresh the UI to ensure all widgets update their appearance
        self.repaint()

    def change_theme(self, theme_name):
        self.theme_manager.set_theme(theme_name)
        self.apply_theme()

    def on_backup_versions_changed(self, value):
        print(f"Number of backup versions changed to: {value}")

    def setup_grid_layout(self):
        # Implementation remains the same, but we'll use the theme for colors
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        
        # Top-left panel (Configuration Dashboard)
        config_dashboard = self.create_configuration_dashboard()
        self.grid_layout.addWidget(config_dashboard, 0, 0)

        # Top-right panel (Backup Schedule)
        backup_schedule = self.create_backup_schedule_panel()
        self.grid_layout.addWidget(backup_schedule, 0, 1)

        # Bottom-left panel (Blank for now)
        blank_panel = self.create_blank_panel()
        self.grid_layout.addWidget(blank_panel, 1, 0)

        # Bottom-right panel
        bottom_right_panel = self.create_bottom_right_panel()
        self.grid_layout.addWidget(bottom_right_panel, 1, 1)

        # Set equal column and row stretches
        self.grid_layout.setColumnStretch(0, 1)
        self.grid_layout.setColumnStretch(1, 1)
        self.grid_layout.setRowStretch(0, 1)
        self.grid_layout.setRowStretch(1, 1)

    def create_bottom_right_panel(self):
        """Create the operation history panel with dropdown selector"""
        content = QWidget()
        content.setObjectName("ContentWidget")
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create single history panel that can switch between backup/restore
        self.history_panel = OperationHistoryPanel('backup', self.history_manager, self.theme_manager)
        main_layout.addWidget(self.history_panel)

        return self.create_panel('Device History', content)

    def create_file_explorer_panel(self):
        """Create the file explorer panel"""
        if not hasattr(self, 'settings_cfg_path'):
            logging.error('Settings path not initialized')
            return self.create_panel('File Explorer', QLabel("Settings not loaded"))

        content = QWidget()
        content.setObjectName("ContentWidget")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        appdata_path = os.getenv('APPDATA')
        json_directory = os.path.join(appdata_path, 'Stormcloud')
        
        if not os.path.exists(json_directory):
            os.makedirs(json_directory)
        
        file_explorer = FileExplorerPanel(
            json_directory, 
            self.theme_manager, 
            self.settings_cfg_path,
            self.systray,
            self.history_manager
        )
        
        content_layout.addWidget(file_explorer)
        
        return self.create_panel('File Explorer', content)

    def create_panel(self, title, content_widget):
        panel = QWidget()
        panel.setObjectName("PanelWidget")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        header = QLabel(title)
        header.setObjectName("HeaderLabel")
        header.setProperty("panelType", title)
        header.setAlignment(Qt.AlignCenter)
        header.setFixedHeight(30)
        layout.addWidget(header)

        content_widget.setObjectName("ContentWidget")
        layout.addWidget(content_widget)

        return panel

    def create_backup_schedule_panel(self):
        content = QWidget()
        content.setObjectName("BackupSchedulePanel")
        layout = QVBoxLayout(content)

        self.schedule_calendar = BackupScheduleCalendar(self.theme_manager)
        self.schedule_calendar.schedule_updated.connect(self.update_backup_schedule)
        layout.addWidget(self.schedule_calendar)

        return self.create_panel('Backup Schedule', content)

    def format_backup_schedule(self):
        """
        Formats the backup schedule by maintaining a clean dictionary structure
        and converting to YAML-style format once at the end
        """
        # Build the complete schedule dictionary
        schedule_dict = {
            'BACKUP_SCHEDULE': {
                'weekly': {},
                'monthly': {}
            }
        }
        
        # Populate the dictionary with time values
        for schedule_type in ['weekly', 'monthly']:
            for day, times in self.backup_schedule[schedule_type].items():
                schedule_dict['BACKUP_SCHEDULE'][schedule_type][day] = [time.toString('HH:mm') for time in times]
        
        # Convert dictionary to YAML-style lines
        schedule_lines = []
        
        # Add BACKUP_SCHEDULE header
        schedule_lines.append('BACKUP_SCHEDULE:')
        
        # Add weekly section if it exists
        schedule_lines.append('  weekly:')
        if schedule_dict['BACKUP_SCHEDULE']['weekly']:
            for day, times in schedule_dict['BACKUP_SCHEDULE']['weekly'].items():
                schedule_lines.append(f'    {day}:')
                schedule_lines.append(f'      {times}')
                
        # Add monthly section if it exists
        schedule_lines.append('  monthly:')
        if schedule_dict['BACKUP_SCHEDULE']['monthly']:
            for day, times in schedule_dict['BACKUP_SCHEDULE']['monthly'].items():
                schedule_lines.append(f'    {day}:')
                schedule_lines.append(f'      {times}')
        
        return schedule_lines

    def save_backup_settings(self):
        """
        Save backup settings to the configuration file with YAML format for schedule
        """
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
                # Find the end of the BACKUP_SCHEDULE section
                schedule_end = schedule_start + 1
                while schedule_end < len(settings):
                    # Stop if we hit another top-level key (no indentation) that isn't empty
                    if settings[schedule_end].strip() and not settings[schedule_end].startswith(' '):
                        break
                    schedule_end += 1
                    
                # Replace the old schedule with the new one
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

        # Create layout for two panels
        panel_layout = QHBoxLayout()

        # Left panel with stacked Settings and Properties
        left_panel = self.create_stacked_settings_panel()
        
        # Add vertical divider - using same style as Web & Folders panel
        vertical_line = QFrame()
        vertical_line.setFrameShape(QFrame.VLine)
        vertical_line.setObjectName("VerticalDivider")
        
        # Right panel for Backed Up Folders
        right_panel = self.create_backed_up_folders_subpanel()

        # Add panels and divider to layout with equal width
        panel_layout.addWidget(left_panel)
        panel_layout.addWidget(vertical_line)
        panel_layout.addWidget(right_panel)
        panel_layout.setStretch(0, 1)  # Left panel takes 1 part
        panel_layout.setStretch(2, 1)  # Right panel takes 1 part
        panel_layout.setSpacing(0)  # Reduce spacing to make divider look consistent

        main_layout.addLayout(panel_layout)

        return self.create_panel('Configuration Dashboard', content)

    def create_stacked_settings_panel(self):
        """Create left panel with stacked Settings and Properties"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)  # Remove spacing to control it within the splitter

        # Create vertical splitter
        splitter = QSplitter(Qt.Vertical)
        splitter.setObjectName("SettingsSplitter")
        splitter.setHandleWidth(3)  # Make handle slightly thicker than regular lines
        
        # Settings section
        settings_widget = self.create_settings_section()
        splitter.addWidget(settings_widget)
        
        # Properties section
        properties_widget = self.create_properties_section()
        splitter.addWidget(properties_widget)
        
        # Set initial sizes (60% settings, 40% properties)
        splitter.setSizes([60, 40])
        
        layout.addWidget(splitter)
        
        # Apply styling to splitter
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {theme['divider_color']};
                margin: 10px 10px;  /* Match padding of panels */
            }}
            QSplitter::handle:hover {{
                background-color: {theme['accent_color']};
            }}
        """)
        
        return panel

    def create_settings_section(self):
        """Create settings section of the stacked panel"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)  # Consistent padding

        # Subpanel header
        header = QLabel("Settings")
        header.setObjectName("SubpanelHeader")
        layout.addWidget(header)

        # Horizontal divider
        horizontal_line = QFrame()
        horizontal_line.setFrameShape(QFrame.HLine)
        horizontal_line.setObjectName("HorizontalDivider")
        layout.addWidget(horizontal_line)

        # Status
        self.status_value_text = QLabel('Unknown')
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel('Backup Engine Status:'))
        status_layout.addWidget(self.status_value_text)
        layout.addLayout(status_layout)

        # Backup mode
        self.backup_mode_dropdown = QComboBox()
        self.backup_mode_dropdown.addItems(['Realtime', 'Scheduled'])
        self.backup_mode_dropdown.currentIndexChanged.connect(self.on_backup_mode_changed)
        self.backup_mode_dropdown.setCursor(Qt.PointingHandCursor)
        backup_mode_layout = QHBoxLayout()
        backup_mode_layout.addWidget(QLabel('Backup Mode:'))
        backup_mode_layout.addWidget(self.backup_mode_dropdown)
        layout.addLayout(backup_mode_layout)

        # Backup versions
        maximum_backup_versions = 10
        self.backup_versions_spinbox = QSpinBox()
        self.backup_versions_spinbox.setMinimum(1)
        self.backup_versions_spinbox.setMaximum(maximum_backup_versions)
        self.backup_versions_spinbox.setValue(3)
        self.backup_versions_spinbox.valueChanged.connect(self.on_backup_versions_changed)
        self.backup_versions_spinbox.setObjectName("BackupVersionsSpinBox")
        backup_versions_layout = QHBoxLayout()
        backup_versions_layout.addWidget(QLabel(f'Backup Versions (max {maximum_backup_versions}):'))
        backup_versions_layout.addWidget(self.backup_versions_spinbox)
        layout.addLayout(backup_versions_layout)

        layout.addStretch(1)
        return widget
        
    def create_properties_section(self):
        """Create properties section of the stacked panel"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)  # Consistent padding

        # Subpanel header
        header = QLabel("Properties")
        header.setObjectName("SubpanelHeader")
        layout.addWidget(header)

        # Horizontal divider
        horizontal_line = QFrame()
        horizontal_line.setFrameShape(QFrame.HLine)
        horizontal_line.setObjectName("HorizontalDivider")
        layout.addWidget(horizontal_line)

        # Properties
        properties_layout = QFormLayout()
        self.agent_id_value = QLabel('Unknown')
        self.api_key_value = QLabel('Unknown')
        properties_layout.addRow('AGENT_ID:', self.agent_id_value)
        properties_layout.addRow('API_KEY:', self.api_key_value)
        layout.addLayout(properties_layout)

        layout.addStretch(1)
        return widget
        """Create the bottom right panel with the new layout"""
        content = QWidget()
        content.setObjectName("ContentWidget")
        main_layout = QVBoxLayout(content)

        # Create two subpanels
        subpanel_layout = QHBoxLayout()
        
        # Left subpanel (empty for now - will contain new functionality)
        left_subpanel = QWidget()
        left_subpanel.setObjectName("EmptySubpanel")
        left_layout = QVBoxLayout(left_subpanel)
        
        # Add future widget placeholder header
        header = QLabel("Future Widget")
        header.setObjectName("SubpanelHeader")
        left_layout.addWidget(header)

        # Add horizontal divider
        horizontal_line = QFrame()
        horizontal_line.setFrameShape(QFrame.HLine)
        horizontal_line.setObjectName("HorizontalDivider")
        left_layout.addWidget(horizontal_line)

        left_layout.addStretch()

        # Add vertical divider
        vertical_line = QFrame()
        vertical_line.setFrameShape(QFrame.VLine)
        vertical_line.setObjectName("VerticalDivider")

        # Right subpanel (Stormcloud Web)
        right_subpanel = self.create_web_links_subpanel()

        # Set width proportions
        subpanel_layout.addWidget(left_subpanel, 50)
        subpanel_layout.addWidget(vertical_line)
        subpanel_layout.addWidget(right_subpanel, 50)
        subpanel_layout.setSpacing(0)  # Reduce spacing for consistent divider appearance

        main_layout.addLayout(subpanel_layout)

        return self.create_panel('Web & Folders', content)

    def create_subpanel(self, title):
        subpanel = QWidget()
        layout = QVBoxLayout(subpanel)

        # Subpanel header
        header = QLabel(title)
        header.setObjectName("SubpanelHeader")
        layout.addWidget(header)

        # Horizontal divider
        horizontal_line = QFrame()
        horizontal_line.setFrameShape(QFrame.HLine)
        horizontal_line.setObjectName("HorizontalDivider")
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

            maximum_backup_versions = 10

            self.backup_versions_spinbox = QSpinBox()
            self.backup_versions_spinbox.setMinimum(1)
            self.backup_versions_spinbox.setMaximum(maximum_backup_versions)
            self.backup_versions_spinbox.setValue(3)  # Default value
            self.backup_versions_spinbox.valueChanged.connect(self.on_backup_versions_changed)
            self.backup_versions_spinbox.setObjectName("BackupVersionsSpinBox")
            backup_versions_layout = QHBoxLayout()
            backup_versions_layout.addWidget(QLabel(f'Number of Backup Versions (max {maximum_backup_versions}):'))
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
        """Toggle backup schedule panel and update button colors"""
        # Find the Backup Schedule panel
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if isinstance(widget, QWidget) and widget.findChild(QLabel, "HeaderLabel").text() == 'Backup Schedule':
                content_widget = widget.findChild(QWidget, "ContentWidget")
                if content_widget:
                    content_widget.setEnabled(enabled)
                    content_widget.setProperty("enabled", str(enabled).lower())
                    
                    # Find all buttons and update their style
                    for button in content_widget.findChildren(QPushButton):
                        if not enabled:
                            button.setStyleSheet("""
                                QPushButton {
                                    background-color: #444444;
                                    color: #888888;
                                    border: none;
                                    padding: 5px 10px;
                                    border-radius: 5px;
                                }
                                QPushButton:hover {
                                    background-color: #4a4a4a;
                                }
                                QPushButton:pressed {
                                    background-color: #404040;
                                }
                            """)
                        else:
                            button.setStyleSheet("")  # Reset to default theme style
                    
                    content_widget.style().unpolish(content_widget)
                    content_widget.style().polish(content_widget)
                    break

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

    def create_backup_tab(self):
        """Create and return the backup tab with its complete layout"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Header with Start Backup Engine button
        header_widget = self.create_header_widget()
        layout.addWidget(header_widget)

        # Grid layout for panels
        grid_widget = QWidget()
        self.grid_layout = QGridLayout(grid_widget)
        
        # Top-left panel (Configuration Dashboard)
        config_dashboard = self.create_configuration_dashboard()
        self.grid_layout.addWidget(config_dashboard, 0, 0)

        # Top-right panel (Backup Schedule)
        backup_schedule = self.create_backup_schedule_panel()
        self.grid_layout.addWidget(backup_schedule, 0, 1)

        # Bottom-left panel (File Explorer)
        self.file_explorer = self.create_file_explorer_panel()  # Updated method name
        self.grid_layout.addWidget(self.file_explorer, 1, 0)

        # Bottom-right panel (Operation History)
        if not hasattr(self, 'operation_history_panel'):
            self.operation_history_panel = self.create_bottom_right_panel()
        self.grid_layout.addWidget(self.operation_history_panel, 1, 1)

        # Set equal column and row stretches
        self.grid_layout.setColumnStretch(0, 1)
        self.grid_layout.setColumnStretch(1, 1)
        self.grid_layout.setRowStretch(0, 1)
        self.grid_layout.setRowStretch(1, 1)
        
        layout.addWidget(grid_widget)
        return tab

    def create_backed_up_folders_subpanel(self):
        subpanel = QWidget()
        layout = QVBoxLayout(subpanel)

        # Subpanel header
        header = QLabel("Backed Up Folders")
        header.setObjectName("SubpanelHeader")
        layout.addWidget(header)

        # Horizontal divider
        horizontal_line = QFrame()
        horizontal_line.setFrameShape(QFrame.HLine)
        horizontal_line.setObjectName("HorizontalDivider")
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
        """Add a new folder to backup"""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Backup")
        if folder:
            # Convert to forward slashes for consistency
            folder = folder.replace('\\', '/')
            
            # Check if folder is already being backed up
            if folder in self.backup_paths or folder in self.recursive_backup_paths:
                StormcloudMessageBox.information(self, "Info", "This folder is already being backed up.")
                return
            
            # Add to regular backup paths by default
            if folder not in self.backup_paths:  # Prevent duplicates
                self.backup_paths.append(folder)
                self.add_folder_to_backup(folder, False)
                self.update_settings_file()
            
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
        """Save current backup paths to settings file"""
        if not hasattr(self, 'settings_cfg_path') or not os.path.exists(self.settings_cfg_path):
            StormcloudMessageBox.critical(self, 'Error', 'Settings file not found.')
            return

        try:
            # Read all lines from settings file
            with open(self.settings_cfg_path, 'r') as f:
                lines = f.readlines()

            # Create new lines list
            new_lines = []
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                
                if line.startswith('BACKUP_PATHS:'):
                    if self.backup_paths:
                        new_lines.append('BACKUP_PATHS:\n')
                        for path in self.backup_paths:
                            new_lines.append(f'- {path}\n')
                    else:
                        new_lines.append('BACKUP_PATHS: []\n')
                        
                    # Skip until we hit the next non-path line
                    i += 1
                    while i < len(lines) and (
                        lines[i].strip().startswith('- ') or 
                        lines[i].strip() == '[]' or 
                        not lines[i].strip()
                    ):
                        i += 1
                    continue
                        
                elif line.startswith('RECURSIVE_BACKUP_PATHS:'):
                    if self.recursive_backup_paths:
                        new_lines.append('RECURSIVE_BACKUP_PATHS:\n')
                        for path in self.recursive_backup_paths:
                            new_lines.append(f'- {path}\n')
                    else:
                        new_lines.append('RECURSIVE_BACKUP_PATHS: []\n')
                        
                    # Skip until we hit the next non-path line
                    i += 1
                    while i < len(lines) and (
                        lines[i].strip().startswith('- ') or 
                        lines[i].strip() == '[]' or 
                        not lines[i].strip()
                    ):
                        i += 1
                    continue
                    
                else:
                    new_lines.append(lines[i])
                    i += 1

            # Write updated content back to file
            with open(self.settings_cfg_path, 'w') as f:
                f.writelines(new_lines)

            logging.info('Settings file updated successfully.')
                
        except Exception as e:
            logging.error('Failed to update settings file: %s', e)
            StormcloudMessageBox.critical(self, 'Error', f'Failed to update settings file: {str(e)}')

    def update_settings_section(self, settings, section_name, paths):
        # Remove any duplicate sections first
        settings[:] = [line for i, line in enumerate(settings) 
                      if not (line.strip() == section_name and 
                             any(s.strip() == section_name for s in settings[:i]))]
        
        # Find the section
        try:
            section_index = next(i for i, line in enumerate(settings) if line.strip() == section_name)
        except StopIteration:
            return None
        
        # Remove existing paths under this section
        i = section_index + 1
        while i < len(settings) and (settings[i].startswith("- ") or not settings[i].strip()):
            settings.pop(i)
        
        # Add paths or empty list notation
        if paths:
            for path in paths:
                settings.insert(i, f"- {path}")
                i += 1
        else:
            settings.insert(i, "[]")
        
        return section_index

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
        if not os.path.exists(self.settings_cfg_path):
            return

        with open(self.settings_cfg_path, 'r') as f:
            settings = f.read().splitlines()

        self.backup_schedule = {'weekly': {}, 'monthly': {}}
        
        in_schedule = False
        current_type = None
        current_day = None
        
        for line in settings:
            # line = line.strip()
            
            if line.startswith('BACKUP_SCHEDULE:'):
                in_schedule = True
                continue
                
            if not in_schedule or not line:
                continue
                
            if not line.startswith(' '):  # End of schedule section
                break
            
            # Handle schedule type (weekly/monthly)
            if line.strip() == 'weekly:':
                current_type = 'weekly'
                continue
            elif line.strip() == 'monthly:':
                current_type = 'monthly'
                continue
                
            # Handle days and times
            if line.lstrip().endswith(':'):  # Day line
                current_day = line.strip().rstrip(':')
                continue
                
            # Handle times
            if current_type and current_day and '[' in line:
                times_str = line.strip().strip('[]')
                if times_str:
                    time_list = [t.strip().strip('"\'') for t in times_str.split(',')]
                    self.backup_schedule[current_type][current_day] = [
                        QTime.fromString(t.strip(), "HH:mm") for t in time_list
                    ]
        
        self.update_backup_schedule_widget()
        logging.info(f"Loaded backup schedule: {self.backup_schedule}")

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
        """Move a folder between regular and recursive backup lists"""
        # Remove from both lists first
        if folder in self.backup_paths:
            self.backup_paths.remove(folder)
        if folder in self.recursive_backup_paths:
            self.recursive_backup_paths.remove(folder)
        
        # Add to appropriate list
        if recursive:
            if folder not in self.recursive_backup_paths:  # Prevent duplicates
                self.recursive_backup_paths.append(folder)
        else:
            if folder not in self.backup_paths:  # Prevent duplicates
                self.backup_paths.append(folder)
        
        # Save changes
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
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        running = self.is_backup_engine_running()
        self.status_value_text.setText('Running' if running else 'Not Running')
        self.status_value_text.setStyleSheet(f"color: {theme['status_running'] if running else theme['status_not_running']};")
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
            
            # Add history event for realtime mode
            if self.backup_mode == 'Realtime':
                self.history_manager.add_event('backup', HistoryEvent(
                    timestamp=dt.datetime.now(),
                    source=InitiationSource.REALTIME,
                    status=OperationStatus.IN_PROGRESS
                ))
            
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

    def closeEvent(self, event):
        """Handle cleanup when the application closes"""
        if hasattr(self, 'systray'):
            self.systray.shutdown()
        super().closeEvent(event)

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

    def __init__(self, theme_manager):
        super().__init__()
        self.theme_manager = theme_manager
        self.schedule = {'weekly': {}, 'monthly': {}}
        self.initUI()
        self.apply_theme()

        # Connect to theme changes
        self.theme_manager.theme_changed.connect(self.on_theme_changed)

    def initUI(self):
        main_layout = QHBoxLayout(self)

        # Left side: Schedule setup
        schedule_setup = QWidget()
        schedule_setup.setObjectName("BackupScheduleSubpanel")
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
        monthly_days = [ordinal(i) for i in range(1, 29)] + ["Last day"]
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
        calendar_widget.setObjectName("CalendarWidgetSubpanel")
        calendar_layout = QVBoxLayout(calendar_widget)
        self.calendar_view = CustomCalendarWidget(self.theme_manager)
        self.calendar_view.setSelectionMode(QCalendarWidget.NoSelection)
        calendar_layout.addWidget(self.calendar_view)
        main_layout.addWidget(calendar_widget)

    def apply_theme(self):
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        self.setStyleSheet(theme["stylesheet"])
        
        # Explicitly set the background color for the main widget
        self.setStyleSheet(f"BackupScheduleCalendar {{ background-color: {theme['app_background']}; }}")
        
        # Update colors for specific widgets
        self.day_combo.setStyleSheet(f"color: {theme['text_primary']}; background-color: {theme['input_background']};")
        self.weekly_time_edit.setStyleSheet(f"color: {theme['text_primary']}; background-color: {theme['input_background']};")
        self.day_of_month_combo.setStyleSheet(f"color: {theme['text_primary']}; background-color: {theme['input_background']};")
        self.monthly_time_edit.setStyleSheet(f"color: {theme['text_primary']}; background-color: {theme['input_background']};")
        
        button_style = f"""
            QPushButton {{
                color: {theme['button_text']};
                background-color: {theme['button_background']};
                border: none;
                padding: 5px 10px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
            QPushButton:pressed {{
                background-color: {theme['button_pressed']};
            }}
        """
        self.add_weekly_button.setStyleSheet(button_style)
        self.add_monthly_button.setStyleSheet(button_style)
        self.remove_button.setStyleSheet(button_style)

        self.schedule_list.setStyleSheet(f"color: {theme['text_primary']}; background-color: {theme['panel_background']};")

        # Force update of the calendar view
        self.calendar_view.apply_theme()

    def on_theme_changed(self):
        self.apply_theme()

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
        monthly_days = [ordinal(i) for i in range(1, 29)] + ["Last day"]
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
        
        # Strip suffix when saving to schedule
        if day == "Last day":
            day_key = day
        else:
            # Remove suffix (st, nd, rd, th) and convert to string
            day_key = str(int(''.join(filter(str.isdigit, day))))
            
        if day_key not in self.schedule['monthly']:
            self.schedule['monthly'][day_key] = []
        if time not in self.schedule['monthly'][day_key]:
            self.schedule['monthly'][day_key].append(time)
            self.update_schedule_list()
            self.update_calendar_view()
            self.schedule_updated.emit(self.schedule)

    def remove_backup(self):
        current_item = self.schedule_list.currentItem()
        if current_item:
            text = current_item.text()
            schedule_type, day, time_str = text.split(" - ")
            time = QTime.fromString(time_str, "hh:mm AP")
            
            # Convert display day back to storage format
            if schedule_type.lower() == 'monthly' and day != "Last day":
                day = str(int(''.join(filter(str.isdigit, day))))
                
            self.schedule[schedule_type.lower()][day].remove(time)
            if not self.schedule[schedule_type.lower()][day]:
                del self.schedule[schedule_type.lower()][day]
            self.update_schedule_list()
            self.update_calendar_view()
            self.schedule_updated.emit(self.schedule)
                    
    def update_schedule_list(self):
        self.schedule_list.clear()
        for schedule_type, schedule_data in self.schedule.items():
            for day, times in schedule_data.items():
                # Add suffix back for display
                if schedule_type == 'monthly' and day != "Last day":
                    display_day = ordinal(int(day))
                else:
                    display_day = day
                    
                for time in sorted(times):
                    item_text = f"{schedule_type.capitalize()} - {display_day} - {time.toString('hh:mm AP')}"
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

class CustomCalendarWidget(QCalendarWidget):
    def __init__(self, theme_manager, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.schedule = {'weekly': {}, 'monthly': {}}
        self.initUI()
        self.apply_theme()

        # Connect to theme changes
        self.theme_manager.theme_changed.connect(self.on_theme_changed)

    def initUI(self):
        # Remove the default navigation bar completely
        self.setNavigationBarVisible(False)
    
        # Set the color for weekends to be the same as weekdays
        weekday_color = QColor(self.theme_manager.get_theme(self.theme_manager.current_theme)['text_primary'])
        weekend_format = QTextCharFormat()
        weekend_format.setForeground(weekday_color)
        self.setWeekdayTextFormat(Qt.Saturday, weekend_format)
        self.setWeekdayTextFormat(Qt.Sunday, weekend_format)

        # Remove the vertical header (week numbers)
        self.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)

        # Create custom navigation bar
        navigation_bar = QWidget(self)
        nav_layout = QHBoxLayout(navigation_bar)

        self.prev_button = CustomArrowButton('left', self.theme_manager)
        self.next_button = CustomArrowButton('right', self.theme_manager)
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

    def apply_theme(self):
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        self.setStyleSheet(theme["stylesheet"])

        # Update colors for specific widgets
        self.month_year_label.setStyleSheet(f"color: {theme['text_primary']}; font-weight: bold;")

        # Update weekday text format
        weekday_color = QColor(theme['text_primary'])
        weekend_format = QTextCharFormat()
        weekend_format.setForeground(weekday_color)
        self.setWeekdayTextFormat(Qt.Saturday, weekend_format)
        self.setWeekdayTextFormat(Qt.Sunday, weekend_format)

        # Force repaint
        self.updateCells()

    def on_theme_changed(self):
        self.apply_theme()

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
            painter.setBrush(QColor(66, 133, 244, 100))
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

class CustomArrowButton(QPushButton):
    def __init__(self, direction, theme_manager, parent=None):
        super().__init__(parent)
        self.direction = direction
        self.theme_manager = theme_manager
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("CustomArrowButton")

        # Connect to theme changes
        self.theme_manager.theme_changed.connect(self.on_theme_changed)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        
        # Draw circle
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme["button_background"]))
        painter.drawEllipse(2, 2, 20, 20)

        # Draw arrow
        painter.setPen(QColor(theme["button_text"]))
        painter.setBrush(QColor(theme["button_text"]))
        if self.direction == 'left':
            painter.drawPolygon(QPoint(14, 6), QPoint(14, 18), QPoint(8, 12))
        else:
            painter.drawPolygon(QPoint(10, 6), QPoint(10, 18), QPoint(16, 12))

    def on_theme_changed(self):
        self.update()  # Force repaint when theme changes
# ---------------

class SearchResultDelegate(QStyledItemDelegate):
    def __init__(self, theme_manager):
        super().__init__()
        self.theme_manager = theme_manager

    def paint(self, painter, option, index):
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        
        # Save the original state
        painter.save()
        
        # Handle selection background
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor(theme["list_item_selected"]))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, QColor(theme["list_item_hover"]))
        
        # Set text color
        if index.parent().isValid():  # This is a child item (actual result)
            text_color = QColor(theme["text_primary"])
        else:  # This is a root item (search summary)
            result_type = index.data(Qt.UserRole)
            if result_type == "found":
                text_color = QColor(theme["search_results_found"])
            elif result_type == "not_found":
                text_color = QColor(theme["search_results_not_found"])
            else:
                text_color = QColor(theme["text_primary"])
        
        # Draw the text
        painter.setPen(text_color)
        text = index.data(Qt.DisplayRole)
        painter.drawText(option.rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        
        # Restore the original state
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + 5)  # Add some vertical padding
        return size

class FileExplorerPanel(QWidget):
    def __init__(self, json_directory, theme_manager, settings_cfg_path=None, systray=None, history_manager=None):
        super().__init__()
        self.theme_manager = theme_manager
        self.settings_path = settings_cfg_path  # Store as settings_path internally for compatibility
        self.systray = systray
        self.history_manager = history_manager
        self.install_path = self.get_install_path()
        
        # Update metadata directory path
        self.metadata_dir = os.path.join(self.install_path, 'file_explorer', 'manifest')
        os.makedirs(self.metadata_dir, exist_ok=True)
        
        self.search_history = []
        self.init_ui()
        self.load_data()
        self.apply_theme()
        
        self.theme_manager.theme_changed.connect(self.on_theme_changed)

    def init_ui(self):
        self.setObjectName("FileExplorerPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Add search box
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("Search for file or folder...")
        self.search_box.returnPressed.connect(self.search_item)
        layout.addWidget(self.search_box)

        # Main splitter
        self.main_splitter = QSplitter(Qt.Vertical)
        layout.addWidget(self.main_splitter)

        # Tree view
        self.tree_view = QTreeView()
        self.tree_view.setObjectName("FileTreeView")
        self.custom_style = CustomTreeCarrot(self.theme_manager)
        self.tree_view.setStyle(self.custom_style)
        self.main_splitter.addWidget(self.tree_view)

        # Results panel
        self.results_panel = QTreeWidget()
        self.results_panel.setObjectName("ResultsPanel")
        self.results_panel.setHeaderHidden(True)
        self.results_panel.itemClicked.connect(self.navigate_to_result)
        self.results_panel.setVisible(False)
        self.results_panel.setItemDelegate(SearchResultDelegate(self.theme_manager))
        
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

        # Update TreeView
        self.tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.show_context_menu)
        self.tree_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree_view.doubleClicked.connect(self.show_metadata)

        self.load_data()
        
        # Progress widget with history manager
        self.progress_widget = OperationProgressWidget(self)
        self.progress_widget.history_manager = self.history_manager
        self.progress_widget.operation_completed.connect(self.on_operation_completed)
        layout.addWidget(self.progress_widget)

    def apply_theme(self):
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        self.setStyleSheet(theme["stylesheet"])
        self.results_panel.setItemDelegate(SearchResultDelegate(self.theme_manager))

    def on_theme_changed(self):
        self.apply_theme()

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
        """Get the full path for a file, resolving against installation directory if needed"""
        path = []
        while item:
            path.insert(0, item.text())
            item = item.parent()
        relative_path = '/'.join(path)
        
        # Resolve against installation directory
        return self.resolve_path(relative_path) or relative_path

    def get_install_path(self):
        """Get Stormcloud installation path from stable settings"""
        try:
            appdata_path = os.getenv('APPDATA')
            stable_settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')
            
            if not os.path.exists(stable_settings_path):
                logging.error(f"Stable settings file not found at: {stable_settings_path}")
                return None
                
            with open(stable_settings_path, 'r') as f:
                stable_settings = json.load(f)
                install_path = stable_settings.get('install_path', '').replace('\\', '/')
                logging.info(f"Found installation path: {install_path}")
                return install_path
                
        except Exception as e:
            logging.error(f"Failed to get installation path: {e}")
            return None

    def get_metadata_files(self):
        """Get list of metadata files sorted by timestamp (newest first)"""
        try:
            files = [f for f in os.listdir(self.metadata_dir) 
                    if f.startswith('file_metadata_') and f.endswith('.json')]
            
            # Sort files by timestamp in filename
            files.sort(key=lambda x: datetime.strptime(
                x, 'file_metadata_%Y%m%d_%H%M%S.json'), reverse=True)
            
            return files
        except Exception as e:
            logging.error(f"Error getting metadata files: {e}")
            return []

    def cleanup_old_metadata(self, max_files=10):
        """Remove old metadata files keeping only the most recent ones"""
        try:
            files = self.get_metadata_files()
            if len(files) > max_files:
                for old_file in files[max_files:]:
                    file_path = os.path.join(self.metadata_dir, old_file)
                    try:
                        os.remove(file_path)
                        logging.info(f"Removed old metadata file: {old_file}")
                    except Exception as e:
                        logging.error(f"Failed to remove old metadata file {old_file}: {e}")
        except Exception as e:
            logging.error(f"Error during metadata cleanup: {e}")

    def resolve_path(self, relative_path):
        """Resolve a path relative to the installation directory"""
        if not self.install_path:
            logging.error("Installation path not found - cannot resolve relative path")
            return None
            
        # Convert path separators to match the system
        relative_path = relative_path.replace('\\', '/').lstrip('/')
        full_path = os.path.join(self.install_path, relative_path)
        full_path = os.path.normpath(full_path)
        
        logging.info(f"Resolved path: {relative_path} -> {full_path}")
        return full_path

    def show_partial_matches(self, search_text, match_data):
        matches, folders_searched, files_searched = match_data
        self.add_to_search_history(search_text, [m[0] for m in matches], folders_searched, files_searched)
        self.update_results_panel()

    def show_context_menu(self, position):
        """Enhanced context menu with file/folder awareness"""
        settings = self.read_settings()
        if not settings:
            StormcloudMessageBox.critical(self, "Error", "Could not read required settings")
            return

        index = self.tree_view.indexAt(position)
        if not index.isValid():
            return

        self.current_item = self.model.itemFromIndex(index)
        self.current_path = self.get_full_path(self.current_item)
        
        menu = QMenu(self)
        restore_action = menu.addAction("Restore")
        backup_action = menu.addAction("Backup Now")
        
        # Add version history option only for files
        versions_action = None
        if not self.is_folder(self.current_item):
            metadata = self.current_item.data(Qt.UserRole)
            if metadata and 'versions' in metadata:
                versions_action = menu.addMenu("Versions")
                for version in metadata['versions']:
                    timestamp = version.get('timestamp', 'Unknown')
                    version_action = versions_action.addAction(f"Restore version from {timestamp}")
                    version_action.setData(version)

        action = menu.exec_(self.tree_view.viewport().mapToGlobal(position))
        
        if not action:
            return

        try:
            if action == restore_action:
                self.restore_item()
            elif action == backup_action:
                self.backup_item()
            elif versions_action and action.parent() == versions_action:
                version_data = action.data()
                self.restore_file_version(self.current_path, version_data)
        except Exception as e:
            StormcloudMessageBox.critical(self, "Error", f"Operation failed: {str(e)}")

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
            
            # Set custom roles for coloring
            root_item.setData(0, Qt.UserRole, "found" if len(result['matches']) > 0 else "not_found")
            
            for match in result['matches']:
                child_item = QTreeWidgetItem([match])
                root_item.addChild(child_item)
            self.results_panel.addTopLevelItem(root_item)
            
            # Expand the root item by default
            root_item.setExpanded(True)
            
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
        """Load file metadata from most recent JSON file"""
        metadata_files = self.get_metadata_files()
        
        if not metadata_files:
            logging.warning("No metadata files found")
            return

        # Use most recent file
        latest_file = metadata_files[0]
        json_path = os.path.join(self.metadata_dir, latest_file)
        
        try:
            with open(json_path, 'r') as file:
                data = json.load(file)
                for item in data:
                    self.model.add_file(item['ClientFullNameAndPathAsPosix'], item)
            
            logging.info(f"Loaded metadata from {latest_file}")
            
            # Cleanup old files
            self.cleanup_old_metadata()
            
        except Exception as e:
            logging.error(f"Error loading metadata: {str(e)}", exc_info=True)
            StormcloudMessageBox.critical(self, "Error", f"Failed to load file metadata: {str(e)}")

    def read_settings(self):
        """Read current settings from file with detailed logging"""
        if not self.settings_path:
            logging.error('Settings path is not set')
            return None
            
        logging.info(f'Attempting to read settings from: {self.settings_path}')
        
        if not os.path.exists(self.settings_path):
            logging.error(f'Settings file not found at: {self.settings_path}')
            return None

        try:
            with open(self.settings_path, 'r') as f:
                content = f.read()
                logging.debug(f'Raw settings content: {content[:100]}...')  # Log first 100 chars
                
                settings = yaml.safe_load(content)
                if not isinstance(settings, dict):
                    logging.error(f'Settings did not parse to dictionary, got: {type(settings)}')
                    return None
                    
                required_keys = ['API_KEY', 'AGENT_ID', 'SECRET_KEY']
                missing_keys = [key for key in required_keys if key not in settings]
                
                if missing_keys:
                    logging.error(f'Missing required settings keys: {missing_keys}')
                    logging.debug(f'Available keys: {list(settings.keys())}')
                    return None
                    
                logging.info('Successfully loaded all required settings')
                return settings
                
        except yaml.YAMLError as e:
            logging.error(f'Failed to parse YAML settings: {e}')
            return None
        except Exception as e:
            logging.error(f'Unexpected error reading settings: {type(e).__name__} - {str(e)}')
            return None

    def restore_item(self):
        """Start a restore operation"""
        self.start_operation('restore')

    def backup_item(self):
        """Start a backup operation"""
        self.start_operation('backup')

    def is_folder(self, item):
        """Determine if the item is a folder based on whether it has children"""
        return item.hasChildren()

    def restore_folder(self, folder_path):
        """Recursively restore a folder and its contents"""
        settings = self.read_settings()
        if not settings:
            return

        try:
            success_count = 0
            fail_count = 0
            skipped_count = 0

            # Process all items under this folder
            for child_row in range(self.current_item.rowCount()):
                child_item = self.current_item.child(child_row)
                child_path = self.get_full_path(child_item)
                
                if self.is_folder(child_item):
                    s, f, sk = self.restore_folder(child_path)
                    success_count += s
                    fail_count += f
                    skipped_count += sk
                else:
                    try:
                        if restore_utils.restore_file(child_path, 
                                                    settings['API_KEY'],
                                                    settings['AGENT_ID'],
                                                    settings['SECRET_KEY']):
                            success_count += 1
                        else:
                            fail_count += 1
                    except Exception as e:
                        logging.error(f"Failed to restore file {child_path}: {e}")
                        fail_count += 1

            # Show summary message
            message = f"Folder restore complete:\n\n"
            message += f"Successfully restored: {success_count} files\n"
            if fail_count > 0:
                message += f"Failed to restore: {fail_count} files\n"
            if skipped_count > 0:
                message += f"Skipped: {skipped_count} files\n"
            
            StormcloudMessageBox.information(self, "Restore Complete", message)
            return success_count, fail_count, skipped_count

        except Exception as e:
            logging.error(f"Failed to restore folder {folder_path}: {e}")
            StormcloudMessageBox.critical(self, "Error", f"Failed to restore folder: {str(e)}")
            return 0, 1, 0

    def backup_folder(self, folder_path):
        """Recursively backup a folder and its contents"""
        settings = self.read_settings()
        if not settings:
            return

        try:
            # Get the hash database connection
            hash_db_path = os.path.join(self.install_path, 'schash.db')
            dbconn = get_or_create_hash_db(hash_db_path)
            
            success_count = 0
            fail_count = 0
            
            try:
                # Process the folder recursively
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        try:
                            path_obj = pathlib.Path(file_path)
                            if backup_utils.process_file(path_obj,
                                                       settings['API_KEY'],
                                                       settings['AGENT_ID'],
                                                       settings['SECRET_KEY'],
                                                       dbconn,
                                                       True):  # Force backup
                                success_count += 1
                            else:
                                fail_count += 1
                        except Exception as e:
                            logging.error(f"Failed to backup file {file_path}: {e}")
                            fail_count += 1
                
                # Show summary message
                message = f"Folder backup complete:\n\n"
                message += f"Successfully backed up: {success_count} files\n"
                if fail_count > 0:
                    message += f"Failed to backup: {fail_count} files"
                
                StormcloudMessageBox.information(self, "Backup Complete", message)
                
            finally:
                if dbconn:
                    dbconn.close()

        except Exception as e:
            logging.error(f"Failed to backup folder {folder_path}: {e}")
            StormcloudMessageBox.critical(self, "Error", f"Failed to backup folder: {str(e)}")

    def restore_file(self, file_path):
        """Restore file from backup"""
        settings = self.read_settings()
        if not settings:
            StormcloudMessageBox.critical(self, "Error", "Could not read required settings")
            return

        try:
            file_path = file_path.replace('\\', '/')
            logging.info("Restore requested from application for file: {}".format(file_path))
            
            if restore_utils.restore_file(file_path
                                            , settings['API_KEY']
                                            , settings['AGENT_ID']
                                            , settings['SECRET_KEY']):
                StormcloudMessageBox.information(self, "Success", f"Successfully restored {file_path}")
            else:
                StormcloudMessageBox.critical(self, "Error", f"Failed to restore {file_path}")
        except Exception as e:
            logging.error(f"Failed to restore file {file_path}: {e}")
            StormcloudMessageBox.critical(self, "Error", f"Failed to restore file: {str(e)}")
            
    def restore_file_version(self, file_path, version_data):
        """Restore specific version of a file"""
        settings = self.read_settings()
        if not settings:
            StormcloudMessageBox.critical(self, "Error", "Could not read required settings")
            return

        try:
            # Add version info to the request
            version_id = version_data.get('version_id')
            if restore_utils.restore_file(file_path, settings['API_KEY'], settings['AGENT_ID'], 
                                       settings['SECRET_KEY'], version_id):
                StormcloudMessageBox.information(self, "Success", 
                    f"Successfully restored version from {version_data.get('timestamp')} of {file_path}")
            else:
                StormcloudMessageBox.critical(self, "Error", 
                    f"Failed to restore version from {version_data.get('timestamp')} of {file_path}")
        except Exception as e:
            logging.error(f"Failed to restore file version {file_path}: {e}")
            StormcloudMessageBox.critical(self, "Error", f"Failed to restore file version: {str(e)}")

    def backup_file(self, file_path):
        """Trigger immediate backup of a file with standardized path format"""
        settings = self.read_settings()
        if not settings:
            StormcloudMessageBox.critical(self, "Error", "Could not read required settings")
            return

        try:
            # Get the raw path
            full_path = self.resolve_path(file_path)
            if not full_path:
                logging.error("Manual backup failed: Could not resolve file path")
                StormcloudMessageBox.critical(self, "Error", "Could not resolve file path")
                return

            # Convert backslashes to forward slashes to match settings.cfg format
            full_path = full_path.replace('\\', '/')
            logging.info(f"Standardized path for backup: {full_path}")

            # Verify file exists and is accessible
            if not os.path.exists(full_path):
                logging.error(f"File not found: {full_path}")
                StormcloudMessageBox.critical(self, "Error", f"File not found: {os.path.basename(full_path)}")
                return

            # Connect to hash database
            hash_db_path = os.path.join(self.install_path, 'schash.db')
            logging.info(f"Connecting to hash database at: {hash_db_path}")
            
            try:
                dbconn = get_or_create_hash_db(hash_db_path)
                logging.info("Successfully connected to hash database")
            except Exception as e:
                logging.error(f"Failed to connect to hash database: {e}")
                StormcloudMessageBox.critical(self, "Error", "Could not connect to hash database")
                return

            try:
                logging.info(f"Attempting manual backup of file: {full_path}")

                path_obj = pathlib.Path(full_path)
                
                result = backup_utils.process_file(
                    path_obj,
                    settings['API_KEY'],
                    settings['AGENT_ID'],
                    settings['SECRET_KEY'],
                    dbconn,
                    True
                )

                if result:
                    logging.info(f"Manual backup successful for: {full_path}")
                    StormcloudMessageBox.information(self, "Success", 
                        f"Successfully backed up {os.path.basename(full_path)}")
                else:
                    logging.error(f"Manual backup failed for: {full_path}")
                    StormcloudMessageBox.critical(self, "Error", 
                        f"Failed to backup {os.path.basename(full_path)}")

            except Exception as e:
                logging.error(f"Error during backup operation: {str(e)}")
                StormcloudMessageBox.critical(self, "Error", f"Backup failed: {str(e)}")

        except Exception as e:
            logging.error(f"Manual backup operation failed: {str(e)}", exc_info=True)
            StormcloudMessageBox.critical(self, "Error", f"Backup operation failed: {str(e)}")
        finally:
            if 'dbconn' in locals():
                dbconn.close()
            logging.info("=== MANUAL BACKUP OPERATION COMPLETE ===")

    def on_operation_completed(self, result):
        """Handle completion of backup/restore operations"""
        if 'error' in result:
            StormcloudMessageBox.critical(self, "Operation Failed", result['error'])
            # Update the status of the existing event to FAILED
            if self.history_manager and result.get('operation_type'):
                self.history_manager.complete_operation(
                    result.get('operation_id'),
                    OperationStatus.FAILED,
                    result['error']
                )
        else:
            message = f"Operation completed:\n\n"
            message += f"Successfully processed: {result['success_count']} files\n"
            if result['fail_count'] > 0:
                message += f"Failed to process: {result['fail_count']} files\n"
            if result['total'] != (result['success_count'] + result['fail_count']):
                message += f"Skipped: {result['total'] - (result['success_count'] + result['fail_count'])} files\n"
            
            StormcloudMessageBox.information(self, "Operation Complete", message)
            
            # No need to create a new event - the status has already been updated
            # through file processing in the HistoryManager
            
            # Refresh file metadata after successful operation
            self.load_data()

    def start_operation(self, operation_type: str):
        """Start a backup or restore operation"""
        if not self.current_path:
            return
            
        settings = self.read_settings()
        if not settings:
            return
            
        # Start a new operation in history
        if self.history_manager:
            operation_id = self.history_manager.start_operation(
                operation_type,
                InitiationSource.USER
            )
            settings['operation_id'] = operation_id
            
        # Add required settings
        settings['settings_path'] = self.settings_path
        settings['operation_type'] = operation_type
        
        # Start operation with progress tracking
        self.progress_widget.start_operation(operation_type, self.current_path, settings)

class FileSystemModel(QStandardItemModel):
    def __init__(self):
        super().__init__()
        self.setHorizontalHeaderLabels(['Backed Up Files'])
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
        formatted_json = json.dumps(metadata, indent=2)
        self.text_edit.setText(formatted_json)
        layout.addWidget(self.text_edit)

        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)

class CustomTreeCarrot(QProxyStyle):
    def __init__(self, theme_manager):
        super().__init__()
        self.theme_manager = theme_manager

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PE_IndicatorBranch:
            if option.state & QStyle.State_Children:
                rect = option.rect
                center = rect.center()
                theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
                
                painter.save()
                # Don't use antialiasing - we want crisp pixels
                painter.setRenderHint(QPainter.Antialiasing, False)
                
                # Set up pen for single pixel drawing
                pen = QPen(QColor(theme["accent_color"]))
                pen.setWidth(1)
                painter.setPen(pen)
                
                if option.state & QStyle.State_Open:
                    # Down carrot (rotated 90 degrees from right carrot)
                    base_x = center.x() - 3
                    base_y = center.y() - 2
                    
                    # Left diagonal line
                    for i in range(4):
                        painter.drawPoint(base_x + i, base_y + i)
                    # Right diagonal line
                    for i in range(4):
                        painter.drawPoint(base_x + 6 - i, base_y + i)
                else:
                    # Right carrot (keep the working version)
                    base_x = center.x() - 2
                    base_y = center.y() - 3
                    
                    # Draw top diagonal line down-right
                    for i in range(4):
                        painter.drawPoint(base_x + i, base_y + i)
                    # Draw bottom diagonal line up-right
                    for i in range(4):
                        painter.drawPoint(base_x + i, base_y + 6 - i)
                
                painter.restore()
            else:
                super().drawPrimitive(element, option, painter, widget)
        else:
            super().drawPrimitive(element, option, painter, widget)

class ThemeManager(QObject):
    theme_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.themes = {
            "Dark Age Classic Dark": self.dark_theme(),
            "Light": self.light_theme()
        }
        self.current_theme = "Dark Age Classic Dark"

    def get_theme(self, theme_name):
        return self.themes.get(theme_name, self.themes["Dark Age Classic Dark"])

    def set_theme(self, theme_name):
        if theme_name in self.themes:
            self.current_theme = theme_name
            self.theme_changed.emit(theme_name)

    def dark_theme(self):
        return {
            "app_background": "#202124",
            "panel_background": "#333333",
            "text_primary": "#e8eaed",
            "text_secondary": "#9aa0a6",
            "accent_color": "#4285F4",
            "accent_color_hover": "#5294FF",
            "accent_color_pressed": "#3275E4",
            "panel_border": "#666",
            "input_background": "#333",
            "input_border": "#666",
            "input_border_focus": "#8ab4f8",
            "button_text": "white",
            "list_item_hover": "#3c4043",
            "list_item_selected": "#444",
            "list_item_selected_text": "#8ab4f8",
            "scroll_background": "#2a2a2a",
            "scroll_handle": "#5a5a5a",
            "scroll_handle_hover": "#6a6a6a",
            "header_background": "#171717",
            "divider_color": "#666",
            "status_running": "#28A745",
            "status_not_running": "#DC3545",
            "calendar_background": "#333",
            "calendar_text": "#e8eaed",
            "calendar_highlight": "#4285F4",
            "calendar_highlight_text": "#ffffff",
            "calendar_grid": "#444",
            "calendar_today": "#8ab4f8",
            "calendar_backup_day": "#66, 133, 244, 100",
            "button_background": "#4285F4",
            "button_hover": "#5294FF",
            "button_pressed": "#3275E4",
            "carrot_background": "#4285F4",
            "carrot_foreground": "#FFFFFF",
            "search_results_found": "#34A853",
            "search_results_not_found": "#EA4335",
            
            "payment_success": "#28A745",
            "payment_success_hover": "#218838",
            "payment_failed": "#DC3545",
            "payment_failed_hover": "#BD2130",
            "payment_pending": "#FFC107",
            "payment_pending_hover": "#E0A800",
            "payment_neutral": "#6C757D",
            "payment_neutral_hover": "#5A6268",
            "payment_primary": "#007BFF",
            "payment_primary_hover": "#0056b3",
            "payment_info": "#17A2B8",
            "payment_info_hover": "#138496",
            "payment_high_priority": "#DC3545",
            
            "stylesheet": """
                QMainWindow, QWidget#centralWidget, QWidget#gridWidget {
                    background-color: #202124;
                }
                QWidget {
                    background-color: transparent;
                    color: #e8eaed;
                    font-family: 'Arial', sans-serif;
                }
                #PanelWidget {
                    background-color: #333333;
                    border: 1px solid #666;
                    border-radius: 5px;
                }
                #HeaderLabel {
                    background-color: #202124;
                    color: #8ab4f8;
                    font-size: 16px;
                    font-weight: bold;
                    border: 1px solid #666;
                    border-top-left-radius: 5px;
                    border-top-right-radius: 5px;
                    padding: 5px;
                }
                #ContentWidget {
                    background-color: #333333;
                    border: 1px solid #666; 
                    border-radius: 5px;
                    border-top: 0px;
                    border-top-left-radius: 0px;
                    border-top-right-radius: 0px;
                }
                QMenuBar, QStatusBar {
                    background-color: #202124;
                    color: #e8eaed;
                }
                QMenuBar::item:selected {
                    background-color: #3c4043;
                }
                QMainWindow::title {
                    background-color: #202124;
                    color: #4285F4;
                    font-size: 16px;
                    font-weight: bold;
                    padding-left: 10px;
                }
                QPushButton {
                    background-color: #4285F4;
                    color: white;
                    border: none;
                    padding: 5px 10px;
                    border-radius: 5px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #5294FF;
                }
                QPushButton:pressed {
                    background-color: #3275E4;
                }
                QPushButton#start_button {
                    font-size: 16px;
                    font-weight: bold;
                }
                QLabel {
                    font-size: 14px;
                }
                QListWidget, QTreeWidget, QTreeView {
                    background-color: #333;
                    border: none;
                    border-radius: 5px;
                    outline: 0;
                    padding: 1px;
                }
                QListWidget::item, QTreeWidget::item, QTreeView::item {
                    padding: 5px;
                }
                QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover {
                    background-color: #3c4043;
                }
                QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {
                    background-color: #444;
                    color: #8ab4f8;
                }
                #HeaderLabel[panelType="Configuration Dashboard"] {
                    color: #2ECC71;
                }
                #HeaderLabel[panelType="Backup Schedule"] {
                    color: #3498DB;
                }
                #HeaderLabel[panelType="File Explorer"] {
                    color: #bf2ee8;
                }
                #HeaderLabel[panelType="Web & Folders"] {
                    color: #F1C40F;
                }
                QLabel#SubpanelHeader {
                    font-weight: bold;
                }
                QLabel#HistoryTypeLabel {
                    color: #e8eaed;
                    font-size: 14px;
                }
                #WebLink {
                    background-color: transparent;
                    color: #8ab4f8;
                    text-align: left;
                }
                #WebLink:hover {
                    text-decoration: underline;
                }
                QComboBox, QSpinBox, QTimeEdit {
                    background-color: #333;
                    color: #e8eaed;
                    border: 1px solid #666;
                    border-radius: 5px;
                    padding: 5px;
                    min-width: 6em;
                }
                QComboBox:hover, QSpinBox:hover, QTimeEdit:hover {
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
                QFrame[frameShape="4"], QFrame[frameShape="5"] {
                    color: #666;
                    width: 1px;
                    height: 1px;
                }
                QWidget:disabled {
                    color: #888;
                }
                QComboBox:disabled, QTimeEdit:disabled, QSpinBox:disabled {
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
                    font-size: 12px;
                    font-style: italic;
                    padding-top: 5px;
                    padding-bottom: 5px;
                }
                QScrollBar:vertical, QScrollBar:horizontal {
                    background: #2a2a2a;
                    width: 10px;
                    height: 10px;
                    margin: 0px;
                }
                QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                    background: #5a5a5a;
                    min-height: 30px;
                    min-width: 30px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
                    background: #6a6a6a;
                }
                QScrollBar::add-line, QScrollBar::sub-line {
                    height: 0px;
                    width: 0px;
                }
                QScrollBar::add-page, QScrollBar::sub-page {
                    background: none;
                }
                QTimeEdit::up-button, QTimeEdit::down-button,
                QSpinBox::up-button, QSpinBox::down-button {
                    background-color: transparent;
                    border: none;
                    width: 16px;
                    height: 12px;
                }
                QSpinBox::up-arrow, QTimeEdit::up-arrow {
                    image: url(up-arrow-dark.png);
                    width: 8px;
                    height: 8px;
                }
                QSpinBox::down-arrow, QTimeEdit::down-arrow {
                    image: url(down-arrow-dark.png);
                    width: 8px;
                    height: 8px;
                }
                QWidget#BackupSchedulePanel[enabled="false"] {
                    background-color: #555;
                }
                QWidget#BackupSchedulePanel[enabled="true"] {
                    background-color: #333;
                }
                QCalendarWidget {
                    background-color: #333;
                    color: #e8eaed;
                }
                QCalendarWidget QTableView {
                    alternate-background-color: #3a3a3a;
                    background-color: #333;
                }
                QCalendarWidget QWidget {
                    alternate-background-color: #3a3a3a;
                }
                QCalendarWidget QMenu {
                    background-color: #333;
                    color: #e8eaed;
                }
                QCalendarWidget QToolButton {
                    background-color: transparent;
                    color: #e8eaed;
                }
                QCalendarWidget QToolButton:hover {
                    background-color: #4285F4;
                    border-radius: 2px;
                }
                QCalendarWidget #qt_calendar_navigationbar {
                    background-color: #2a2a2a;
                }
                QWidget#FileExplorerPanel {
                    background-color: #333;
                    color: #e8eaed;
                    font-family: 'Segoe UI', Arial, sans-serif;
                }
                QLineEdit#SearchBox {
                    background-color: #303134;
                    border: 1px solid #5f6368;
                    border-radius: 4px;
                    padding: 8px;
                    font-size: 12px;
                    color: #e8eaed;
                }
                QLineEdit#SearchBox:focus {
                    border-color: #8ab4f8;
                }
                QTableCornerButton::section {
                    background-color: #333333;  /* Match table background */
                    border: none;
                }

                QTableWidget {
                    background-color: #333333;
                    alternate-background-color: #3c4043;
                    border: none;
                    gridline-color: #666;
                }
                
                QHeaderView::section {
                    background-color: #303134;
                    color: #e8eaed;
                    padding: 8px;
                    border: none;
                    font-weight: bold;
                }
                
                QHeaderView::section:first {
                    background-color: #303134;
                }
                
                QSplitter::handle {
                    background-color: #666;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 1px solid #666;
                    border-radius: 5px;
                    margin-top: 7px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px 0 3px;
                }
                QTreeWidget#ResultsPanel QTreeWidgetItem {
                    color: #e8eaed;
                }
                QTreeWidget#ResultsPanel QTreeWidgetItem[results="found"] {
                    color: #34A853;
                }
                QTreeWidget#ResultsPanel QTreeWidgetItem[results="not_found"] {
                    color: #EA4335;
                }
                
                BackupScheduleCalendar {
                    background-color: #202124;
                }
                BackupScheduleCalendar > QWidget#BackupScheduleSubpanel {
                    background-color: #202124;
                    border: 1px solid #666;
                    border-radius: 5px;
                }
                BackupScheduleCalendar QGroupBox {
                    background-color: #202124;
                    border: 1px solid #666;
                    border-radius: 5px;
                    margin-top: 7px;
                }
                BackupScheduleCalendar QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px 0 3px;
                }
                BackupScheduleCalendar > QWidget#CalendarWidgetSubpanel {
                    background-color: #202124;
                    border-radius: 5px;
                }
                QTabWidget::pane {
                    border-top: none;
                    border-bottom: 2px solid #666;
                }
                QTabBar::tab {
                    background-color: #202124;
                    color: #e8eaed;
                    padding: 8px 12px;
                    margin-right: 4px;
                    border-top-left-radius: 0;
                    border-top-right-radius: 0;
                    border-bottom-left-radius: 4px;
                    border-bottom-right-radius: 4px;
                }
                QTabBar::tab:selected {
                    background-color: #333333;
                    border-bottom: 2px solid #4285F4;
                }
                QTabBar::tab:hover:!selected {
                    background-color: #3c4043;
                }
                QToolBar {
                    background-color: #202124;
                    border-bottom: 1px solid #666;
                    spacing: 10px;
                    padding: 5px;
                }
                QToolBar QLabel {
                    color: #e8eaed;
                }
                QToolBar QComboBox {
                    background-color: #333;
                    color: #e8eaed;
                    border: 1px solid #666;
                    border-radius: 3px;
                    padding: 2px 5px;
                }
                
                
                /* Payment Processing Specific Styles */
                .payment-group-box {
                    background-color: #333333;
                    border: 1px solid #666;
                    border-radius: 5px;
                    margin-top: 7px;
                    padding-top: 10px;
                    font-weight: bold;
                }
                
                #payment-stripe-connect {
                    background-color: #28A745;
                    color: white;
                    border: none;
                    padding: 5px 10px;
                    border-radius: 5px;
                    font-size: 14px;
                }
                #payment-stripe-connect:hover {
                    background-color: #34CE57;  /* Brighter green */
                }

                #payment-refresh-btn {
                    background-color: #4285F4;  /* Match backup tab blue */
                    color: white;
                    border: none;
                    padding: 5px 10px;
                    border-radius: 5px;
                    font-size: 14px;
                }
                #payment-refresh-btn:hover {
                    background-color: #5294FF;  /* Match backup tab hover */
                }

                #payment-reminder-btn {
                    background-color: #4285F4;
                    color: white;
                    border: none;  /* Explicitly remove border */
                    padding: 5px 10px;
                    border-radius: 5px;
                    font-size: 14px;
                    outline: none;  /* Remove outline */
                }
                #payment-reminder-btn:hover {
                    background-color: #5294FF;
                }
                #payment-reminder-btn:focus {
                    border: none;  /* Remove focus border */
                    outline: none;  /* Remove focus outline */
                }

                #payment-all-reminders-btn {
                    background-color: #4285F4;  /* Match backup tab blue */
                    color: white;
                    border: none;
                    padding: 5px 10px;
                    border-radius: 5px;
                    font-size: 14px;
                }
                #payment-all-reminders-btn:hover {
                    background-color: #5294FF;  /* Match backup tab hover */
                }

                #payment-export-btn {
                    background-color: #17A2B8;
                    color: white;
                    border: none;
                    padding: 5px 10px;
                    border-radius: 5px;
                    font-size: 14px;
                }
                #payment-export-btn:hover {
                    background-color: #1FC8E3;  /* Brighter cyan */
                }

                #payment-total-outstanding {
                    font-weight: bold;
                    color: #e8eaed;
                    margin: 5px;
                }

                #payment-overdue-count {
                    font-weight: bold;
                    color: #DC3545;
                    margin: 5px;
                }

                #payment-demo-label {
                    color: #FFC107;
                    font-style: italic;
                }

                .payment-table {
                    background-color: #333333;
                    alternate-background-color: #3c4043;
                    border: none;
                    gridline-color: #666;
                }

                .payment-table-item {
                    padding: 5px;
                }
            """
    }
        
    def light_theme(self):
        return {
            "app_background": "#f8f9fa",
            "panel_background": "#ffffff",
            "text_primary": "#202124",
            "text_secondary": "#5f6368",
            "accent_color": "#1a73e8",
            "accent_color_hover": "#1967d2",
            "accent_color_pressed": "#185abc",
            "panel_border": "#dadce0",
            "input_background": "#ffffff",
            "input_border": "#dadce0",
            "input_border_focus": "#1a73e8",
            "button_text": "white",
            "list_item_hover": "#f1f3f4",
            "list_item_selected": "#e8f0fe",
            "list_item_selected_text": "#1a73e8",
            "scroll_background": "#f1f3f4",
            "scroll_handle": "#dadce0",
            "scroll_handle_hover": "#bdc1c6",
            "header_background": "#f1f3f4",
            "divider_color": "#dadce0",
            "status_running": "#34a853",
            "status_not_running": "#ea4335",
            
            "calendar_background": "#ffffff",
            "calendar_text": "#202124",
            "calendar_highlight": "#1a73e8",
            "calendar_highlight_text": "#ffffff",
            "calendar_grid": "#dadce0",
            "calendar_today": "#1a73e8",
            "calendar_backup_day": "rgba(26, 115, 232, 0.2)",
            
            "button_background": "#1a73e8",
            "button_hover": "#1967d2",
            "button_pressed": "#185abc",
            
            "file_explorer_background": "#ffffff",
            "file_explorer_text": "#202124",
            "file_explorer_search_background": "#f1f3f4",
            "file_explorer_search_border": "#dadce0",
            "file_explorer_search_focus_border": "#1a73e8",
            "file_explorer_item_hover": "#f1f3f4",
            "file_explorer_item_selected": "#e8f0fe",
            "file_explorer_item_selected_text": "#1a73e8",
            "file_explorer_scrollbar_background": "#f8f9fa",
            "file_explorer_scrollbar_handle": "#dadce0",
            "file_explorer_scrollbar_handle_hover": "#bdc1c6",
            "file_explorer_header": "#f1f3f4",
            "file_explorer_splitter": "#dadce0",
            
            "carrot_background": "#1a73e8",
            "carrot_foreground": "#ffffff",
            
            "search_results_found": "#34A853",
            "search_results_not_found": "#EA4335",
            
            "stylesheet": """
                QMainWindow, QWidget {
                    background-color: #f8f9fa;
                    color: #202124;
                    font-family: 'Arial', sans-serif;
                }
                QMenuBar {
                    background-color: #ffffff;
                    color: #202124;
                }
                QMenuBar::item:selected {
                    background-color: #e8f0fe;
                }
                QMainWindow::title {
                    background-color: #ffffff;
                    color: #1a73e8;
                    font-size: 16px;
                    font-weight: bold;
                    padding-left: 10px;
                }
                QPushButton {
                    background-color: #1a73e8;
                    color: white;
                    border: none;
                    padding: 5px 10px;
                    border-radius: 5px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #1967d2;
                }
                QPushButton:pressed {
                    background-color: #185abc;
                }
                QPushButton#start_button {
                    font-size: 16px;
                    font-weight: bold;
                }
                QLabel {
                    font-size: 14px;
                }
                QLabel#SubpanelHeader {
                    font-weight: bold;
                }
                QLabel#HistoryTypeLabel {
                    color: #202124;
                    font-size: 14px;
                }
                QListWidget, QTreeWidget {
                    background-color: #ffffff;
                    border: 1px solid #dadce0;
                    border-radius: 5px;
                    outline: 0;
                    padding: 1px;
                }
                QListWidget::item, QTreeWidget::item {
                    padding: 5px;
                }
                QListWidget::item:hover, QTreeWidget::item:hover {
                    background-color: #f1f3f4;
                }
                QListWidget::item:selected, QTreeWidget::item:selected {
                    background-color: #e8f0fe;
                    color: #1a73e8;
                }
                #PanelWidget {
                    background-color: #ffffff;
                    border: 1px solid #dadce0;
                    border-radius: 5px;
                }
                
                QListWidget, QTreeWidget, QTreeView {
                    background-color: #ffffff;
                    border: none;
                    border-radius: 5px;
                    outline: 0;
                    padding: 1px;
                }
                QListWidget::item, QTreeWidget::item, QTreeView::item {
                    padding: 5px;
                }
                QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover {
                    background-color: #eee;
                }
                QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {
                    background-color: #ddd;
                    color: #2574f5;
                }
                
                #HeaderLabel {
                    font-size: 16px;
                    font-weight: bold;
                    background-color: #eee;
                    border: 1px solid #dadce0;
                    border-top-left-radius: 5px;
                    border-top-right-radius: 5px;
                    padding: 5px;
                }
                
                #HeaderLabel[panelType="Configuration Dashboard"] {
                    color: #228B22;
                }
                #HeaderLabel[panelType="Backup Schedule"] {
                    color: #4169E1;
                }
                #HeaderLabel[panelType="File Explorer"] {
                    color: #800080;
                }
                #HeaderLabel[panelType="Web & Folders"] {
                    color: #daa520;
                }
                
                #ContentWidget {
                    background-color: transparent;
                    border-bottom-left-radius: 5px;
                    border-bottom-right-radius: 5px;
                }
                #WebLink {
                    background-color: transparent;
                    color: #1a73e8;
                    text-align: left;
                }
                #WebLink:hover {
                    text-decoration: underline;
                }
                QComboBox, QSpinBox, QTimeEdit {
                    background-color: #ffffff;
                    color: #202124;
                    border: 1px solid #dadce0;
                    border-radius: 5px;
                    padding: 5px;
                    min-width: 6em;
                }
                QComboBox:hover, QSpinBox:hover, QTimeEdit:hover {
                    border-color: #1a73e8;
                }
                QComboBox::drop-down {
                    subcontrol-origin: padding;
                    subcontrol-position: center right;
                    width: 20px;
                    border-left: none;
                    background: transparent;
                }
                QFrame[frameShape="4"],
                QFrame[frameShape="5"] {
                    color: #dadce0;
                    width: 1px;
                    height: 1px;
                }
                QWidget:disabled {
                    color: #9aa0a6;
                    background-color: #f1f3f4;
                }
                QCalendarWidget QWidget:disabled {
                    color: #9aa0a6;
                    background-color: #f1f3f4;
                }
                QComboBox:disabled, QTimeEdit:disabled, QSpinBox:disabled {
                    background-color: #333;
                    color: #bdc1c6;
                }
                QPushButton:disabled {
                    background-color: #bdc1c6;
                    color: #f1f3f4;
                }
                QCheckBox {
                    spacing: 5px;
                }
                #FootnoteLabel {
                    color: #5f6368;
                    font-size: 12px;
                    font-style: italic;
                    padding-top: 5px;
                    padding-bottom: 5px;
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
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                    background: none;
                }
                QScrollBar:horizontal {
                    border: none;
                    background: #f1f3f4;
                    height: 10px;
                    margin: 0px;
                }
                QScrollBar::handle:horizontal {
                    background: #dadce0;
                    min-width: 30px;
                    border-radius: 5px;
                }
                QScrollBar::handle:horizontal:hover {
                    background: #bdc1c6;
                }
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                    width: 0px;
                }
                QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                    background: none;
                }
                QTimeEdit::up-button, QTimeEdit::down-button,
                QSpinBox::up-button, QSpinBox::down-button {
                    background-color: transparent;
                    border: none;
                    width: 16px;
                    height: 12px;
                }
                
                QSpinBox::up-arrow, QTimeEdit::up-arrow {
                    image: url(up-arrow-light.png);
                    width: 8px;
                    height: 8px;
                }
                QSpinBox::down-arrow, QTimeEdit::down-arrow {
                    image: url(down-arrow-light.png);
                    width: 8px;
                    height: 8px;
                }
                QWidget#BackupSchedulePanel[enabled="false"] {
                    background-color: #f1f3f4;
                }
                QWidget#BackupSchedulePanel[enabled="true"] {
                    background-color: #ffffff;
                }
                QCalendarWidget {
                    background-color: #ffffff;
                    color: #202124;
                }
                QCalendarWidget QTableView {
                    alternate-background-color: #f8f9fa;
                    background-color: #ffffff;
                }
                QCalendarWidget QWidget {
                    alternate-background-color: #f8f9fa;
                }
                QCalendarWidget QMenu {
                    background-color: #ffffff;
                    color: #202124;
                }
                QCalendarWidget QToolButton {
                    color: #202124;
                }
                QCalendarWidget QToolButton:hover {
                    background-color: #e8f0fe;
                    border-radius: 2px;
                }
                QCalendarWidget #qt_calendar_navigationbar {
                    background-color: #f1f3f4;
                }
                QWidget#FileExplorerPanel {
                    background-color: #ffffff;
                    color: #202124;
                }
                QLineEdit#SearchBox {
                    background-color: #f1f3f4;
                    border: 1px solid #dadce0;
                    color: #202124;
                }
                QHeaderView::section {
                    background-color: #f1f3f4;
                    color: #202124;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 1px solid #666;
                    border-radius: 5px;
                    margin-top: 7px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px 0 3px;
                }
                QTreeWidget#ResultsPanel QTreeWidgetItem {
                    color: #202124;  /* Default color */
                }
                QTreeWidget#ResultsPanel QTreeWidgetItem[results="found"] {
                    color: #34A853;  /* Green color for results found */
                }
                QTreeWidget#ResultsPanel QTreeWidgetItem[results="not_found"] {
                    color: #EA4335;  /* Red color for no results */
                }
                
                QLineEdit#SearchBox {
                    background-color: #eee;
                    border: 1px solid #ccc;
                    border-radius: 4px;
                    padding: 8px;
                    font-size: 12px;
                    color: #202124;
                }
                QLineEdit#SearchBox:focus {
                    border-color: #8ab4f8;
                }
                
                QListWidget#backup_paths_list {
                    background-color: #ffffff;
                }
                QListWidget#backup_paths_list::item {
                    background-color: #ffffff;
                }
                
                BackupScheduleCalendar {
                    background-color: #f1f3f4;
                }
                BackupScheduleCalendar > QWidget#BackupScheduleSubpanel {
                    background-color: #f1f3f4;
                    border: 1px solid #666;
                    border-radius: 5px;
                }
                BackupScheduleCalendar QGroupBox {
                    background-color: #f1f3f4;
                    border: 1px solid #666;
                    border-radius: 5px;
                    margin-top: 7px;
                }
                BackupScheduleCalendar QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px 0 3px;
                }
                BackupScheduleCalendar > QWidget#CalendarWidgetSubpanel {
                    background-color: #f1f3f4;
                    border-radius: 5px;
                }
                
                QTabWidget::pane {
                    border-top: 2px solid #dadce0;
                    background-color: #ffffff;
                }
                QTabWidget::tab-bar {
                    left: 5px;
                }
                QTabBar::tab {
                    background-color: #f8f9fa;
                    color: #202124;
                    padding: 8px 12px;
                    margin-right: 4px;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                }
                QTabBar::tab:selected {
                    background-color: #ffffff;
                    border-top: 2px solid #1a73e8;
                }
                QTabBar::tab:hover:!selected {
                    background-color: #f1f3f4;
                }
                
                QToolBar {
                    background-color: #f8f9fa;
                    border-bottom: 1px solid #dadce0;
                    spacing: 10px;
                    padding: 5px;
                }
                QToolBar QLabel {
                    color: #202124;
                }
                QToolBar QComboBox {
                    background-color: #ffffff;
                    color: #202124;
                    border: 1px solid #dadce0;
                    border-radius: 3px;
                    padding: 2px 5px;
                }
            """
        }

if __name__ == '__main__':
    app = QApplication([])
    window = StormcloudApp()
    window.show()
    app.exec_()