# standard python library imports
# -----------
import json
import logging
import multiprocessing
import os
import pathlib
import psutil
import pytz
import signal
import smtplib
import sqlite3
import subprocess
import sys
import time
import traceback
import queue
import win32api
import win32con
import win32event
import win32file
import win32gui
import winerror
import yaml

import concurrent.futures

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from multiprocessing import Process, Queue, Manager, Event
from pathlib import Path
from queue import Empty
from threading import Thread, Lock
from typing import Optional, Set, List, Dict

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QMenu,
                             QLabel, QPushButton, QToolButton, QListWidget, QListWidgetItem,
                             QMessageBox, QFileDialog, QGridLayout, QFormLayout,
                             QScrollArea, QSizePolicy, QCheckBox, QComboBox, QFrame,
                             QCalendarWidget, QTimeEdit, QStackedWidget, QGroupBox, QSpinBox,
                             QTreeView, QHeaderView, QStyle, QStyledItemDelegate, QLineEdit,
                             QAbstractItemView, QSplitter, QTreeWidget, QTreeWidgetItem, QDialog,
                             QTextEdit, QProxyStyle, QTabWidget, QTableWidget, QTableWidgetItem, QToolBar,
                             QDialogButtonBox, QProgressBar, QFileIconProvider)
from PyQt5.QtCore import Qt, QUrl, QPoint, QDate, QTime, pyqtSignal, QRect, QSize, QModelIndex, QObject, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty, QRectF, QDir, QEvent, QDateTime, QThread
from PyQt5.QtGui import (QDesktopServices, QFont, QIcon, QColor,
                         QPalette, QPainter, QPixmap, QTextCharFormat,
                         QStandardItemModel, QStandardItem, QPen, QPolygon, QPainterPath, QBrush)
from PyQt5.QtWinExtras import QtWin
# -----------

# stormcloud imports
# -----------
import restore_utils
import backup_utils
import network_utils

from client_db_utils import get_or_create_hash_db
from stormcloud import save_file_metadata, read_yaml_settings_file
# -----------

# dataclasses/helper classes
# -----------
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
class FileRecord:
   filepath: str
   timestamp: datetime
   status: OperationStatus
   error_message: Optional[str] = None
   operation_id: Optional[str] = None

@dataclass
class HistoryEvent:
    timestamp: datetime
    source: InitiationSource
    status: OperationStatus
    operation_type: Optional[str] = None  # Add operation_type field
    operation_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    files: List[FileOperationRecord] = field(default_factory=list)
    error_message: Optional[str] = None
    user_email: Optional[str] = None

@dataclass
class Operation:
    operation_id: str
    timestamp: datetime
    source: InitiationSource
    status: OperationStatus
    operation_type: str
    user_email: Optional[str] = None
    error_message: Optional[str] = None
    files: List[FileRecord] = field(default_factory=list)
    
    def __post_init__(self):
        # If this is a user operation with no email, default to "Unknown User"
        # This handles historical data that may lack proper attribution
        if self.source == InitiationSource.USER and not self.user_email:
            self.user_email = "Unknown User"
        # For system operations, always use "System"
        elif self.source in (InitiationSource.REALTIME, InitiationSource.SCHEDULED):
            self.user_email = "System"

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

@dataclass
class SearchProgress:
    folders_searched: int
    files_found: int
    current_path: str
    is_complete: bool

@dataclass
class Transaction:
    id: str
    date: datetime
    amount: float
    status: str
    customer_name: str
    description: str
    payment_method: str
# -----------

# Thread Registry (to ensure no orphaned processes on shutdown)
# -----------
class ProcessRegistry:
    """
    Singleton registry for managing application processes and threads.
    
    Key Features:
    - Single point of process/thread management
    - Automatic cleanup on application exit
    - Timeout-based termination
    - Logging for debugging
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ProcessRegistry, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self._processes: Set[Process] = set()
        self._threads: Set[QThread] = set()
        self._timers: Set[QTimer] = set()
        logging.info("ProcessRegistry initialized")

    def register_process(self, process: Process) -> None:
        """Register a multiprocessing.Process"""
        if not isinstance(process, Process):
            logging.error(f"Attempted to register invalid process type: {type(process)}")
            return
            
        self._processes.add(process)
        logging.info(f"Registered process {process.name} (PID: {process.pid if process.pid else 'Not started'})")

    def register_thread(self, thread: QThread) -> None:
        """Register a QThread"""
        if not isinstance(thread, QThread):
            logging.error(f"Attempted to register invalid thread type: {type(thread)}")
            return
            
        self._threads.add(thread)
        logging.info(f"Registered thread {thread.objectName() or 'Unnamed'}")

    def register_timer(self, timer: QTimer) -> None:
        """Register a QTimer"""
        if not isinstance(timer, QTimer):
            logging.error(f"Attempted to register invalid timer type: {type(timer)}")
            return
            
        self._timers.add(timer)

    def unregister_process(self, process: Process) -> None:
        """Unregister a process (e.g., when it completes normally)"""
        try:
            self._processes.remove(process)
            logging.info(f"Unregistered process {process.name}")
        except KeyError:
            logging.warning(f"Attempted to unregister unknown process {process.name}")

    def unregister_thread(self, thread: QThread) -> None:
        """Unregister a thread (e.g., when it completes normally)"""
        try:
            self._threads.remove(thread)
            logging.info(f"Unregistered thread {thread.objectName() or 'Unnamed'}")
        except KeyError:
            logging.warning("Attempted to unregister unknown thread")

    def unregister_timer(self, timer: QTimer) -> None:
        """Unregister a timer"""
        try:
            self._timers.remove(timer)
            logging.info("Unregistered timer")
        except KeyError:
            logging.warning("Attempted to unregister unknown timer")

    def cleanup(self, timeout: int = 5) -> None:
        """
        Clean up all registered processes and threads.
        
        Args:
            timeout: Maximum time in seconds to wait for each process/thread
        """
        logging.info("Starting ProcessRegistry cleanup")
        
        # Stop all timers first
        for timer in self._timers:
            try:
                if timer.isActive():
                    timer.stop()
                    logging.info("Stopped timer")
            except Exception as e:
                logging.error(f"Error stopping timer: {e}")

        # Clean up threads
        for thread in list(self._threads):
            try:
                if thread.isRunning():
                    logging.info(f"Stopping thread {thread.objectName() or 'Unnamed'}")
                    thread.quit()
                    if not thread.wait(timeout * 1000):  # Convert to milliseconds
                        logging.warning(f"Thread {thread.objectName() or 'Unnamed'} did not stop gracefully, forcing termination")
                        thread.terminate()
                self._threads.remove(thread)
            except Exception as e:
                logging.error(f"Error cleaning up thread: {e}")

        # Clean up processes
        for process in list(self._processes):
            try:
                if process.is_alive():
                    logging.info(f"Terminating process {process.name}")
                    process.terminate()
                    process.join(timeout=timeout)
                    if process.is_alive():
                        logging.warning(f"Process {process.name} did not terminate gracefully, killing")
                        process.kill()
                self._processes.remove(process)
            except Exception as e:
                logging.error(f"Error cleaning up process: {e}")

        logging.info("ProcessRegistry cleanup completed")

    @property
    def active_process_count(self) -> int:
        """Get count of active processes"""
        return len([p for p in self._processes if p.is_alive()])

    @property
    def active_thread_count(self) -> int:
        """Get count of active threads"""
        return len([t for t in self._threads if t.isRunning()])

    @property
    def active_timer_count(self) -> int:
        """Get count of active timers"""
        return len([t for t in self._timers if t.isActive()])
# -----------

# standalone functions
# -----------
def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

def init_db(db_path):
   with sqlite3.connect(db_path) as conn:
       conn.execute("""
       CREATE TABLE IF NOT EXISTS operations (
           operation_id TEXT PRIMARY KEY,
           timestamp DATETIME NOT NULL,
           source TEXT NOT NULL,
           status TEXT NOT NULL,
           operation_type TEXT NOT NULL,
           user_email TEXT,
           error_message TEXT,
           last_modified DATETIME NOT NULL
       )""")
       
       conn.execute("""
       CREATE TABLE IF NOT EXISTS file_records (
           id INTEGER PRIMARY KEY,
           operation_id TEXT NOT NULL,
           filepath TEXT NOT NULL,
           timestamp DATETIME NOT NULL,
           status TEXT NOT NULL, 
           error_message TEXT,
           FOREIGN KEY (operation_id) REFERENCES operations(operation_id)
       )""")
# -----------

# filesystem indexing / accelerated filesystem search
# -----------
class PathCache:
    """Thread-safe LRU cache for filesystem path metadata.

    Key Functions:
    - Caches frequently accessed filesystem path metadata using LRU eviction
    - Provides thread-safe get/put operations for concurrent access

    Implementation Details:
    - Built on OrderedDict with synchronized access via threading.Lock
    - Fixed maximum size with LRU eviction of oldest entries
    - Thread-safe operations for all cache modifications

    Application Integration:
    - Used by filesystem indexing components to optimize repeated path lookups
    - Reduces filesystem read operations by caching path metadata
    """

    def __init__(self, max_size: int = 10000):
        self.cache: OrderedDict[str, dict] = OrderedDict()
        self.max_size = max_size
        self._lock = Lock()

    def get(self, path: str) -> Optional[dict]:
        with self._lock:
            if path in self.cache:
                self.cache.move_to_end(path)
                return self.cache[path]
            return None

    def put(self, path: str, data: dict):
        with self._lock:
            if path in self.cache:
                self.cache.move_to_end(path)
            else:
                if len(self.cache) >= self.max_size:
                    self.cache.popitem(last=False)
            self.cache[path] = data

class FilesystemIndexer(Process):
    """Background process for indexing local filesystem content.

    Key Functions:
    - Scans all local drives to build searchable index
    - Synchronizes filesystem state with SQLite database 
    - Reports indexing progress through queue
    - Handles graceful shutdown on application exit

    Implementation Details:
    - Runs as separate process via multiprocessing
    - Uses SQLite database for persistent storage
    - Batch processing with configurable transaction sizes
    - Win32API for drive enumeration
    - Queue-based progress reporting
    - Event-based shutdown signaling

    Application Integration:
    - Launched by FilesystemIndex class
    - Provides data for file search functionality
    - Coordinates with main application via queues/events
    - Database used by search components
    """

    def __init__(self, db_path: str, status_queue: Queue, shutdown_event: Event):
        super().__init__()
        self.db_path = db_path
        self.status_queue = status_queue
        self.shutdown_event = shutdown_event
        self.batch_size = 10000
        
    def run(self):
        if __name__ == "__main__":
            multiprocessing.freeze_support()
            
        try:
            logging.info("Starting filesystem indexer process")
            self._init_db()
            self._sync_filesystem()
            
            # Check for shutdown signals periodically
            # while not self.shutdown_event.is_set():
                # # Perform periodic tasks or wait
                # self._perform_periodic_task()
            
        except Exception as e:
            logging.error(f"Indexer process error: {e}")
            self.status_queue.put(('error', str(e)))
        finally:
            logging.info("Filesystem indexer process completed")
            self.status_queue.put(('complete', None))

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS filesystem_index (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_path ON filesystem_index(path)")

    def _sync_filesystem(self):
        try:
            # Scan filesystem
            current_paths = set()
            total_items = 0
            
            for drive in self._get_local_drives():
                if self.shutdown_event.is_set():
                    return
                    
                try:
                    for item in Path(drive).rglob('*'):
                        if self.shutdown_event.is_set():
                            return
                            
                        try:
                            current_paths.add(str(item.absolute()))
                            total_items += 1
                            
                            if total_items % self.batch_size == 0:
                                self.status_queue.put(('progress', {
                                    'items_scanned': total_items,
                                    'current_path': str(item)
                                }))
                                
                        except PermissionError:
                            continue
                        except Exception as e:
                            logging.error(f"Error processing {item}: {e}")
                            
                except Exception as e:
                    logging.error(f"Error scanning drive {drive}: {e}")

            # Get existing database entries
            with sqlite3.connect(self.db_path) as conn:
                existing_paths = set(row[0] for row in conn.execute("SELECT path FROM filesystem_index"))

            # Calculate differences
            paths_to_add = current_paths - existing_paths
            paths_to_remove = existing_paths - current_paths

            # Update database in batches
            with sqlite3.connect(self.db_path) as conn:
                # Add new paths
                for i in range(0, len(paths_to_add), self.batch_size):
                    batch = list(paths_to_add)[i:i + self.batch_size]
                    conn.executemany(
                        "INSERT INTO filesystem_index (path) VALUES (?)",
                        [(path,) for path in batch]
                    )
                    conn.commit()
                    logging.info(f"Added {i + len(batch):,} of {len(paths_to_add):,} new paths")
                    self.status_queue.put(('batch_progress', {
                        'operation': 'add',
                        'processed': i + len(batch),
                        'total': len(paths_to_add)
                    }))

                # Remove deleted paths
                for i in range(0, len(paths_to_remove), self.batch_size):
                    batch = list(paths_to_remove)[i:i + self.batch_size]
                    placeholders = ','.join('?' * len(batch))
                    conn.execute(
                        f"DELETE FROM filesystem_index WHERE path IN ({placeholders})",
                        batch
                    )
                    conn.commit()
                    logging.info(f"Removed {i + len(batch):,} of {len(paths_to_remove):,} deleted paths")
                    self.status_queue.put(('batch_progress', {
                        'operation': 'remove',
                        'processed': i + len(batch),
                        'total': len(paths_to_remove)
                    }))

            self.status_queue.put(('sync_complete', {
                'total_items': total_items,
                'added_items': len(paths_to_add),
                'removed_items': len(paths_to_remove)
            }))

        except Exception as e:
            logging.error(f"Sync error: {e}")
            self.status_queue.put(('error', str(e)))

    def _get_local_drives(self) -> List[str]:
        drives = []
        bitmask = win32api.GetLogicalDrives()
        for letter in range(65, 91):
            if bitmask & (1 << (letter - 65)):
                drive = f"{chr(letter)}:\\"
                if win32file.GetDriveType(drive) in (win32file.DRIVE_FIXED, win32file.DRIVE_REMOVABLE):
                    drives.append(drive)
        return drives

    def _add_to_index(self, conn, path: Path):
        try:
            stats = path.stat()
            conn.execute("""
                INSERT OR REPLACE INTO filesystem_index 
                (path, name, parent_path, is_directory, last_modified, created, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                str(path),
                path.name,
                str(path.parent),
                path.is_dir(),
                datetime.fromtimestamp(stats.st_mtime),
                datetime.fromtimestamp(stats.st_ctime),
                datetime.now()
            ))
        except Exception as e:
            logging.error(f"Error adding {path} to index: {e}")

class FilesystemIndex:
    """High-level interface for filesystem indexing and searching.

    Key Functions:
    - Manages background indexing process
    - Provides search capabilities against indexed paths
    - Handles indexer lifecycle and status monitoring

    Implementation Details:
    - Controls FilesystemIndexer process
    - SQLite database queries for searches
    - Status monitoring via queue
    - Process management with graceful shutdown

    Application Integration:
    - Used by FileExplorerPanel for search functionality
    - Coordinates with UI for progress updates
    - Manages database used throughout application
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.status_queue = Queue()
        self.shutdown_event = Event()
        self.indexer = None

    def _start_indexer(self):
        if self.indexer is None:
            self.indexer = FilesystemIndexer(self.db_path, self.status_queue, self.shutdown_event)
            self.indexer.start()
            logging.info("Started filesystem indexer")
        else:
            logging.warning("Indexer already running")

    def start_indexing(self):
        if self.indexer is None:
            logging.info("Starting filesystem indexer...")
            self.indexer = FilesystemIndexer(
                self.db_path, self.status_queue, self.shutdown_event
            )
            self.indexer.start()  # Start the separate process
        else:
            logging.warning("Indexer already running")

    def search(self, query: str, max_results: int = 100) -> tuple[list, bool]:
        query = query.lower()
        results = []
        truncated = False
        stats = {'total_files': 0, 'total_folders': 0, 'matches_found': 0}
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Get total counts for searched items
                cursor = conn.execute("""
                    SELECT COUNT(*) 
                    FROM filesystem_index 
                    WHERE LOWER(path) LIKE ?
                """, (f"%{query}%",))
                stats['matches_found'] = cursor.fetchone()[0]

                # Get total searchable items
                cursor = conn.execute("""
                    SELECT 
                        COUNT(*) FILTER (WHERE path LIKE '%.%') as file_count,
                        COUNT(*) FILTER (WHERE path NOT LIKE '%.%') as folder_count
                    FROM filesystem_index
                """)
                stats['total_files'], stats['total_folders'] = cursor.fetchone()
                
                # Get paginated results
                cursor = conn.execute("""
                    SELECT path FROM filesystem_index 
                    WHERE LOWER(path) LIKE ?
                    LIMIT ?
                """, (f"%{query}%", max_results + 1))
                
                for i, row in enumerate(cursor):
                    if i < max_results:
                        path = Path(row[0])
                        results.append({
                            'path': str(path),
                            'is_directory': path.is_dir()
                        })
                    else:
                        truncated = True
                        break
                        
                return results, truncated, stats
                    
        except sqlite3.Error as e:
            logging.error(f"Database error during search: {e}")
            return [], False, {'total_files': 0, 'total_folders': 0, 'matches_found': 0}

    def get_indexing_status(self) -> tuple:
        try:
            return self.status_queue.get_nowait()
        except Empty:
            return None, None
        except Exception as e:
            logging.error(f"Error getting indexer status: {e}")
            return None, None

    def shutdown(self):
        """Clean shutdown of indexer process with timeout."""
        if self.indexer and self.indexer.is_alive():
            logging.info("Shutting down filesystem indexer...")
            self.shutdown_event.set()
            self.indexer.join(timeout=5)
            if self.indexer.is_alive():
                self.indexer.terminate()
                logging.warning("Had to force terminate indexer process")

class FileSearchWorker(Process):
    """Filesystem traversal worker for path searching.

    Key Functions:
    - Recursively searches directories for matching paths
    - Reports search progress and results
    - Handles permission errors and access issues

    Implementation Details:
    - Separate process for non-blocking operation
    - Queue-based progress/results reporting
    - Path traversal using os.walk
    - Permission and access error handling

    Application Integration:
    - Used for deep filesystem searches
    - Reports to FileExplorerPanel via queue
    - Complements indexed search capabilities
    """

    def __init__(self, root_path: str, search_term: str, progress_queue: Queue):
        super().__init__()
        self.root_path = root_path
        self.search_term = search_term.lower()
        self.progress_queue = progress_queue
        self.results: List[str] = []
        self.folders_searched = 0
        
    def run(self):
        if __name__ == "__main__":
            multiprocessing.freeze_support()
        try:
            self._search_directory(Path(self.root_path))
            # Signal completion
            self.progress_queue.put(SearchProgress(
                self.folders_searched,
                len(self.results),
                "",
                True
            ))
        except Exception as e:
            logging.error(f"Search worker failed: {e}")
            self.progress_queue.put(SearchProgress(
                self.folders_searched,
                len(self.results),
                str(e),
                True
            ))

    def _search_directory(self, directory: Path):
        try:
            for item in directory.iterdir():
                try:
                    if item.name.lower().find(self.search_term) != -1:
                        self.results.append(str(item))
                    
                    if item.is_dir():
                        self.folders_searched += 1
                        if self.folders_searched % 10 == 0:  # Update progress periodically
                            self.progress_queue.put(SearchProgress(
                                self.folders_searched,
                                len(self.results),
                                str(item),
                                False
                            ))
                        self._search_directory(item)
                except PermissionError:
                    continue
                except Exception as e:
                    logging.error(f"Error searching {item}: {e}")
                    continue
        except Exception as e:
            logging.error(f"Error accessing directory {directory}: {e}")

class LocalSearchWorker(QObject):
    """Qt worker for searching local filesystem index.

    Key Functions:
    - Queries indexed paths database
    - Emits results through Qt signals
    - Provides search statistics

    Implementation Details:
    - Qt signal/slot mechanism
    - SQLite database queries
    - Non-blocking operation via QThread

    Application Integration:
    - Used by FileExplorerPanel UI
    - Works with FilesystemIndex class
    - Updates search results display
    """

    finished = pyqtSignal()
    results_ready = pyqtSignal(list, bool, dict)  # Added stats parameter
    
    def __init__(self, search_text, filesystem_index):
        super().__init__()
        self.search_text = search_text
        self.filesystem_index = filesystem_index
    
    def run(self):
        try:
            results, truncated, stats = self.filesystem_index.search(self.search_text)
            self.results_ready.emit(results, truncated, stats)
        except Exception as e:
            logging.error(f"Search error: {e}")
            self.results_ready.emit([], False, {'total_files': 0, 'total_folders': 0})
        finally:
            self.finished.emit()

class RemoteSearchWorker(QObject):
    """Qt worker for searching remote file tree.

    Key Functions:
    - Traverses remote file tree model
    - Matches paths against search criteria
    - Emits results via Qt signals

    Implementation Details:
    - Qt model/view framework integration
    - Tree traversal algorithms
    - Non-blocking via QThread

    Application Integration:
    - Searches remote backup content
    - Updates FileExplorerPanel UI
    - Works with remote file tree model
    """

    finished = pyqtSignal()
    results_ready = pyqtSignal(list)
    
    def __init__(self, search_text, model):
        super().__init__()
        self.search_text = search_text.lower()
        self.model = model
        self.results = []

    def run(self):
        def search_recursive(parent):
            for row in range(parent.rowCount()):
                item = parent.child(row)
                if self.search_text in item.text().lower():
                    self.results.append(item.text())
                if item.hasChildren():
                    search_recursive(item)

        search_recursive(self.model.invisibleRootItem())
        self.results_ready.emit(self.results)
        self.finished.emit()

class SearchResultDelegate(QStyledItemDelegate):
    """Custom renderer for search result items.

    Key Functions:
    - Applies themed styling to search results
    - Indicates result status through colors
    - Handles mouse interaction

    Implementation Details:
    - Qt delegate painting system
    - Theme-aware color schemes
    - Custom drawing routines

    Application Integration:
    - Used by search results tree views
    - Works with theme management system
    - Provides visual feedback in UI
    """

    def __init__(self, theme_manager):
        super().__init__()
        self.theme_manager = theme_manager

    def paint(self, painter, option, index):
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        
        painter.save()
        
        # Draw background
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor(theme["list_item_selected"]))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, QColor(theme["list_item_hover"]))
        else:
            painter.fillRect(option.rect, QColor(theme["panel_background"]))

        # Set text color based on search result type
        result_type = index.data(Qt.UserRole)
        if result_type == "found":
            text_color = QColor(theme["search_results_found"])
        elif result_type == "not_found":
            text_color = QColor(theme["search_results_not_found"])
        else:
            text_color = QColor(theme["text_primary"])
        
        # Draw text
        painter.setPen(text_color)
        text = index.data(Qt.DisplayRole)
        font = option.font
        if not index.parent().isValid():  # Make root items bold
            font.setBold(True)
            painter.setFont(font)
        
        # Add padding to text rectangle
        text_rect = option.rect
        text_rect.setLeft(text_rect.left() + 5)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + 5)
        return size
# -----------

# Dialogs
# -----------
class LoginDialog(QDialog):
    """Authentication dialog for application login.

    Key Functions:
    - Handles user authentication
    - Manages login credentials and tokens
    - Provides visual feedback during login

    Implementation Details:
    - Qt dialog with themed UI components
    - Network authentication via network_utils
    - Secure token/credential storage
    - App icon extraction from executable

    Application Integration:
    - Entry point for user authentication
    - Provides auth tokens to main application
    - Updates StormcloudApp user context
    """

    def __init__(self, theme_manager, settings_path, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.settings_path = settings_path
        self.api_key = None
        self.user_info = None
        self.auth_tokens = None  # Add storage for auth tokens
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.init_ui()
        self.apply_theme()
        self.setWindowIcon(self.get_app_icon())
        
    def init_ui(self):
        self.setWindowTitle('Stormcloud Login')
        self.setFixedSize(380, 280)  # Golden ratio-based dimensions
        
        # Main layout with perfect spacing
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(32, 24, 32, 32)
        
        # Title
        title_label = QLabel('Welcome to Stormcloud')
        title_label.setObjectName("login-title")
        title_label.setAlignment(Qt.AlignCenter)
        font = title_label.font()
        font.setPointSize(18)
        font.setWeight(QFont.DemiBold)  # Slightly less heavy than bold
        title_label.setFont(font)
        layout.addWidget(title_label)
        
        # Add perfect spacing after title
        layout.addSpacing(28)
        
        # Form layout with proper alignment
        form_layout = QFormLayout()
        form_layout.setSpacing(20)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        # Key changes for alignment:
        form_layout.setRowWrapPolicy(QFormLayout.DontWrapRows)
        form_layout.setLabelAlignment(Qt.AlignVCenter | Qt.AlignRight)  # Right align labels
        form_layout.setFormAlignment(Qt.AlignVCenter)
        
        # Create inputs with labels
        for label_text, placeholder, is_password in [
            ("Email:", "Enter your email", False),
            ("Password:", "Enter your password", True)
        ]:
            # Create label with proper alignment
            label = QLabel(label_text)
            label.setObjectName("login-label")
            label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)  # Ensure label itself is aligned
            
            # Create input with consistent height
            input_field = QLineEdit()
            input_field.setPlaceholderText(placeholder)
            input_field.setObjectName("login-input")
            input_field.setFixedHeight(36)
            
            if is_password:
                input_field.setEchoMode(QLineEdit.Password)
                self.password_input = input_field
            else:
                self.email_input = input_field
            
            form_layout.addRow(label, input_field)

        layout.addLayout(form_layout)
        
        # Perfect spacing before button
        layout.addSpacing(24)
        
        # Error label
        self.error_label = QLabel()
        self.error_label.setObjectName("login-error")
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        
        # Login button with refined proportions
        self.login_button = AnimatedButton('Login')
        self.login_button.setObjectName("login-button")
        self.login_button.clicked.connect(self.attempt_login)
        self.login_button.setFixedHeight(40)
        layout.addWidget(self.login_button)
        
        # Subtle loading indicator
        self.loading_indicator = QProgressBar()
        self.loading_indicator.setObjectName("login-loading")
        self.loading_indicator.setFixedHeight(2)
        self.loading_indicator.setTextVisible(False)
        self.loading_indicator.hide()
        layout.addWidget(self.loading_indicator)
        
        # Connect enter key
        self.email_input.returnPressed.connect(self.login_button.click)
        self.password_input.returnPressed.connect(self.login_button.click)

    def get_app_icon(self):
        """Get application icon using existing process"""
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
                        
                        # Create QIcon and return it
                        icon = QIcon(pixmap)
                        
                        # Clean up
                        win32gui.DestroyIcon(hicon)
                        return icon
                except Exception as e:
                    logging.error(f"Failed to set icon: {e}")
        return QIcon()

    def apply_theme(self):
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        
        # Calculate subtle variations for depth
        input_border = QColor(theme['input_border'])
        input_border.setAlpha(40)  # More subtle border
        
        hover_color = QColor(theme['accent_color'])
        hover_color.setAlpha(90)  # Subtle hover state
        
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {theme['panel_background']};
            }}
            
            QLabel#login-title {{
                color: {theme['text_primary']};
                margin-bottom: 8px;
            }}
            
            QLabel#login-label {{
                color: {theme['text_primary']};
                font-size: 13px;
                font-weight: 500;
                margin-right: 12px;
                min-width: 75px;
            }}
            
            QLineEdit#login-input {{
                background-color: {theme['input_background']};
                color: {theme['text_primary']};
                border: 1px solid {input_border.name()};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 13px;
                selection-background-color: {hover_color.name()};
            }}
            
            QLineEdit#login-input:hover {{
                border: 1px solid {theme['input_border']};
            }}
            
            QLineEdit#login-input:focus {{
                border: 2px solid {theme['accent_color']};
                padding: 5px 11px;  /* Adjust padding to prevent size change */
            }}
            
            QLineEdit#login-input::placeholder {{
                color: rgba(200, 200, 200, 0.7);
            }}
            
            QPushButton#login-button {{
                background-color: {theme['accent_color']};
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 500;
                margin-top: 8px;
            }}
            
            QPushButton#login-button:hover {{
                background-color: {theme['accent_color_hover']};
            }}
            
            QPushButton#login-button:pressed {{
                background-color: {theme['accent_color_pressed']};
                /* Remove transform property as it's not supported */
            }}
            
            QLabel#login-error {{
                color: {theme['payment_failed']};
                font-size: 12px;
                margin: 4px 0;
            }}
            
            QProgressBar#login-loading {{
                background-color: transparent;
                border: none;
                margin-top: 8px;
            }}
            
            QProgressBar#login-loading::chunk {{
                background-color: {theme['accent_color']};
                border-radius: 1px;
            }}
        """)

    def show_error(self, message):
        """Display error message"""
        self.error_label.setText(message)
        self.error_label.show()
        self.loading_indicator.hide()
        self.login_button.setEnabled(True)

    def attempt_login(self):
        """Handle login attempt with enhanced authentication storage"""
        logging.info("Starting login attempt")
        self.error_label.hide()
        self.login_button.setEnabled(False)
        self.loading_indicator.show()
        self.loading_indicator.setRange(0, 0)
        
        email = self.email_input.text().strip()
        password = self.password_input.text()
        
        if not email or not password:
            logging.warning("Login attempt failed: Missing email or password")
            self.show_error("Please enter both email and password.")
            return
        
        try:
            response = network_utils.authenticate_user(email, password, self.settings_path)
            
            if response.get('success'):
                self.user_info = {
                    'email': email,
                    'verified': response['data']['user_info'].get('verified', False),
                    'mfa_enabled': response['data']['user_info'].get('mfa_enabled', False)
                }
                # Store complete auth data
                self.auth_tokens = {
                    'access_token': response['data'].get('access_token'),
                    'refresh_token': response['data'].get('refresh_token'),
                    'session_id': response['data'].get('session_id')
                }
                logging.info(f"Login successful for email: {email}")
                self.accept()
            else:
                error_msg = response.get('message', 'Invalid credentials')
                logging.warning(f"Authentication failed - Server message: {error_msg}")
                self.show_error(error_msg)
            
        except Exception as e:
            logging.error(f"Login attempt failed with exception: {str(e)}")
            logging.error(f"Exception traceback: {traceback.format_exc()}")
            self.show_error("Connection error. Please try again.")

class MetadataDialog(QDialog):
    """Dialog for displaying file metadata details.

    Key Functions:
    - Displays formatted JSON metadata
    - Provides read-only view of file properties

    Implementation Details:
    - Qt dialog with text display
    - JSON formatting/pretty printing

    Application Integration:
    - Used by FileExplorerPanel for file inspection
    - Accessed via context menus
    """

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

class StormcloudMessageBox(QMessageBox):
    """Themed message box for application notifications.

    Key Functions:
    - Shows themed information/error messages
    - Provides static convenience methods

    Implementation Details:
    - Custom Qt message box with theme support
    - Static methods for common message types

    Application Integration:
    - Used throughout app for user notifications
    - Maintains consistent visual style
    - Integrates with theme system
    """

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
# -----------

# Custom style classes
# -----------
class AnimatedButton(QPushButton):
    """Animated button with color transitions and state management.

    Key Functions:
    - Handles button state animations
    - Manages running/stopped states
    - Provides smooth color transitions

    Implementation Details:
    - Qt property animations
    - Custom painting for rounded corners
    - Color interpolation for transitions
    - State-based hover/press effects

    Application Integration:
    - Used for main control buttons
    - Provides visual feedback for operations
    - Integrates with theme system
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._animation_progress = 0.0
        self._base_color = QColor(66, 133, 244)
        self._current_color = self._base_color
        self._start_color = self._base_color
        self._target_color = self._base_color
        self._is_start_button = False
        self._running = False
        self._border_radius = 5

        self.color_animation = QPropertyAnimation(self, b"animation_progress")
        self.color_animation.setDuration(300)
        self.color_animation.setEasingCurve(QEasingCurve.InOutQuad)
        
        self.setStyleSheet("")
        self.setAttribute(Qt.WA_Hover)

    def setAsStartButton(self):
        self._is_start_button = True

    def setRunning(self, running):
        previous_state = self._running
        self._running = running
        
        # Only reset animation if the state actually changed
        if previous_state != running:
            # Reset to base state first
            self._current_color = self._base_color
            self._start_color = self._base_color
            self._target_color = self._base_color
            self._animation_progress = 0.0
            
            # If mouse is still over button, trigger a new hover animation
            if self.underMouse():
                self._start_color = self._base_color
                self._target_color = QColor(220, 53, 69) if running else QColor(40, 167, 69)
                self.color_animation.stop()
                self.color_animation.setStartValue(0.0)
                self.color_animation.setEndValue(1.0)
                self.color_animation.start()
                
        self.update()

    @pyqtProperty(float)
    def animation_progress(self):
        return self._animation_progress

    @animation_progress.setter
    def animation_progress(self, value):
        self._animation_progress = value
        self._update_current_color()
        self.update()

    def _update_current_color(self):
        # Interpolate between start and target colors
        self._current_color = QColor(
            int(self._start_color.red() + (self._target_color.red() - self._start_color.red()) * self._animation_progress),
            int(self._start_color.green() + (self._target_color.green() - self._start_color.green()) * self._animation_progress),
            int(self._start_color.blue() + (self._target_color.blue() - self._start_color.blue()) * self._animation_progress)
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Convert QRect to QRectF
        rect = QRectF(self.rect())
        
        # Create rounded rectangle path
        path = QPainterPath()
        path.addRoundedRect(rect, self._border_radius, self._border_radius)
        
        # Set the clipping path to ensure everything is rounded
        painter.setClipPath(path)
        
        # Fill the button with the current color
        painter.fillPath(path, self._current_color)
        
        # Draw the text
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(rect.toRect(), Qt.AlignCenter, self.text())

    def enterEvent(self, event):
        self._start_color = self._current_color
        if self._is_start_button:
            self._target_color = QColor(220, 53, 69) if self._running else QColor(40, 167, 69)
        else:
            self._target_color = self._base_color.lighter(120)

        self.color_animation.setStartValue(0.0)
        self.color_animation.setEndValue(1.0)
        self.color_animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._start_color = self._current_color
        self._target_color = self._base_color
        self.color_animation.setStartValue(0.0)
        self.color_animation.setEndValue(1.0)
        self.color_animation.start()
        super().leaveEvent(event)

class CustomTreeCarrot(QProxyStyle):
    """Themed directional arrow button.

    Key Functions:
    - Renders directional arrows (left/right)
    - Handles hover/press states

    Implementation Details:
    - Custom QPainter drawing
    - Circle background with arrow
    - Theme-based colors

    Application Integration:
    - Used in navigation controls
    - Calendar navigation
    """

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

class CustomArrowButton(QPushButton):
    """Themed directional arrow button.

    Key Functions:
    - Renders directional arrows (left/right)
    - Handles hover/press states

    Implementation Details:
    - Custom QPainter drawing
    - Circle background with arrow
    - Theme-based colors

    Application Integration:
    - Used in navigation controls
    - Calendar navigation
    """

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

class ThemeManager(QObject):
    """Central theme management system.

    Key Functions:
    - Manages application-wide themes
    - Provides theme switching
    - Defines color schemes and styles

    Implementation Details:
    - Qt signal system for theme changes
    - Comprehensive theme definitions
    - Complex stylesheet management
    - Color scheme coordination

    Application Integration:
    - Used by all UI components
    - Controls app-wide appearance
    - Provides consistent styling
    """

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
            "status_unknown": "#FFC107",  # Amber color for unknown state
            
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
                QWidget[class="folder-item"] QLabel {
                    min-width: 150px;
                    padding: 2px;
                    color: inherit;
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
                QPushButton#start_button:hover {
                    background-color: #28A745;  /* Green when not running */
                }
                QPushButton#start_button[status="running"]:hover {
                    background-color: #DC3545;  /* Red when running */
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
            "status_unknown": "#FFC107",  # Amber color for unknown state
            
            "search_results_found": "#34A853",  # Green
            "search_results_not_found": "#EA4335",  # Red
            
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
                QWidget[class="folder-item"] QLabel {
                    min-width: 150px;
                    padding: 2px;
                    color: inherit;
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
                QPushButton#start_button:hover {
                    background-color: #34a853;  /* Green when not running */
                }
                QPushButton#start_button[status="running"]:hover {
                    background-color: #ea4335;  /* Red when running */
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
                    font-family: 'Segoe UI', Arial, sans-serif;
                }

                QLineEdit#SearchBox {
                    background-color: #f1f3f4;
                    border: 1px solid #dadce0;
                    border-radius: 4px;
                    padding: 8px;
                    font-size: 12px;
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
                
                QTreeWidget#ResultsPanel {
                    background-color: #ffffff;
                    border: 1px solid #dadce0;
                    border-radius: 4px;
                }

                QTreeWidget#ResultsPanel QTreeWidgetItem {
                    color: #202124;
                    padding: 4px;
                }

                QTreeWidget#ResultsPanel QTreeWidgetItem:hover {
                    background-color: #f1f3f4;
                }

                QTreeWidget#ResultsPanel QTreeWidgetItem:selected {
                    background-color: #e8f0fe;
                    color: #1a73e8;
                }
                
                QTreeWidget#ResultsPanel QTreeWidgetItem[results="found"] {
                    color: #34A853;  /* Green color for results found */
                }
                QTreeWidget#ResultsPanel QTreeWidgetItem[results="not_found"] {
                    color: #EA4335;  /* Red color for no results */
                }
                
                QWidget#FileExplorerPanel QTreeView {
                    background-color: #ffffff;
                    border: 1px solid #dadce0;
                }
                
                QWidget#FileExplorerPanel QLineEdit#SearchBox {
                    background-color: #f1f3f4;
                    border: 1px solid #dadce0;
                    color: #202124;
                    padding: 8px;
                }
                
                QWidget#ResultsPanel {
                    background-color: #ffffff;
                    border: 1px solid #dadce0;
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
                    border-color: #1a73e8;
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
# -----------

# Device history management
# -----------
class HistoryManager:
    """Database manager for backup/restore operation history.

    Key Functions:
    - Records operation details and file statuses
    - Manages operation attribution and user tracking
    - Provides paginated history retrieval

    Implementation Details:
    - SQLite database for persistent storage
    - Thread-safe operations
    - Transaction batching
    - User attribution system

    Application Integration:
    - Used by FileExplorerPanel for operation tracking
    - Provides data for HistoryPanel display
    - Coordinates with backup/restore operations
    """

    def __init__(self, db_path):
        """Initialize the history manager with the database path
        
        Args:
            db_path (str): Path to the history database file
        """
        self.db_path = Path(db_path)
        
        # Create parent directory if it doesn't exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        init_db(self.db_path)
        
        self._current_user_email = None
        self.active_operations = {}
        self.last_checks = {'backup': datetime.min, 'restore': datetime.min}
        self.page_size = 100

    @property
    def current_user_email(self) -> Optional[str]:
        return self._current_user_email

    @current_user_email.setter
    def current_user_email(self, email: Optional[str]):
        if email != "System":  # Don't overwrite with system attribution
            self._current_user_email = email
            logging.info(f"HistoryManager current_user_email set to: {email}")

    def has_changes(self, operation_type: str) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT MAX(last_modified) FROM operations 
                    WHERE operation_type = ?
                """, (operation_type,))
                last_modified = cursor.fetchone()[0]
                if last_modified:
                    last_modified = datetime.fromisoformat(last_modified)
                    if last_modified > self.last_checks[operation_type]:
                        self.last_checks[operation_type] = last_modified
                        return True
                return False
        except sqlite3.Error as e:
            logging.error(f"Database error checking changes: {e}")
            return False

    def get_history(self, operation_type: str, page: int = 1) -> List[Operation]:
        """Get paginated history of operations
        
        Args:
            operation_type (str): Type of operation ('backup' or 'restore')
            page (int, optional): Page number to retrieve. Defaults to 1.
        
        Returns:
            List[Operation]: List of operations for the requested page
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                offset = (page - 1) * self.page_size
                    
                # First get limited operations
                cursor.execute("""
                    SELECT operation_id, timestamp, source, status, operation_type, user_email, error_message
                    FROM operations 
                    WHERE operation_type = ?
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """, (operation_type, self.page_size, offset))
                    
                operation_rows = cursor.fetchall()
                operations = {}
                    
                # Then get files for these operations
                for row in operation_rows:
                    op_id = row[0]
                    operations[op_id] = Operation(
                        operation_id=op_id,
                        timestamp=datetime.fromisoformat(row[1]),
                        source=InitiationSource(row[2]),
                        status=OperationStatus(row[3]),
                        operation_type=row[4],
                        user_email=row[5],
                        error_message=row[6],
                        files=[]
                    )
                        
                    # Get files for this operation
                    cursor.execute("""
                        SELECT filepath, timestamp, status, error_message
                        FROM file_records
                        WHERE operation_id = ?
                        ORDER BY timestamp DESC
                    """, (op_id,))
                        
                    for file_row in cursor.fetchall():
                        operations[op_id].files.append(FileRecord(
                            filepath=file_row[0],
                            timestamp=datetime.fromisoformat(file_row[1]),
                            status=OperationStatus(file_row[2]),
                            error_message=file_row[3],
                            operation_id=op_id
                        ))

                return list(operations.values())

        except sqlite3.Error as e:
            logging.error(f"Database error getting history: {e}")
            return []

    def fix_operation_attribution(self):
        """Utility method to fix historical operations with missing attribution"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Update any USER operations with null/empty email to "Unknown User"
                conn.execute("""
                    UPDATE operations 
                    SET user_email = 'Unknown User'
                    WHERE source = ? AND (user_email IS NULL OR user_email = '')
                """, (InitiationSource.USER.value,))
                
                # Update any REALTIME/SCHEDULED operations to use "System"
                conn.execute("""
                    UPDATE operations 
                    SET user_email = 'System'
                    WHERE source IN (?, ?) AND (user_email IS NULL OR user_email = '')
                """, (InitiationSource.REALTIME.value, InitiationSource.SCHEDULED.value))
                
                conn.commit()
                
            logging.info("Fixed attribution for historical operations")
            
        except sqlite3.Error as e:
            logging.error(f"Database error fixing operation attribution: {e}")
        
    def update_operation_status(self, operation_id: str):
        if operation_id not in self.active_operations:
            return
 
        operation = self.active_operations[operation_id]
        if operation.status == OperationStatus.IN_PROGRESS:
            return
 
        file_statuses = [f.status for f in operation.files]
        if OperationStatus.FAILED in file_statuses:
            new_status = OperationStatus.FAILED
        elif all(s == OperationStatus.SUCCESS for s in file_statuses):
            new_status = OperationStatus.SUCCESS
        else:
            new_status = OperationStatus.IN_PROGRESS

        if new_status != operation.status:
            operation.status = new_status
            self._update_operation(operation)

    def start_operation(self, operation_type: str, source: InitiationSource, user_email: Optional[str] = None) -> str:
        # Use provided email or current email for user operations
        operation_user_email = None
        if source == InitiationSource.USER:
            operation_user_email = user_email or self._current_user_email
            if not operation_user_email:
                # operation_user_email = "Unknown"
                raise ValueError("User email required for user-initiated operations")
        else:
            operation_user_email = "System"
        
        operation = Operation(
            operation_id=datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
            timestamp=datetime.now(),
            source=source,
            status=OperationStatus.IN_PROGRESS,
            operation_type=operation_type,
            user_email=operation_user_email,
            files=[]
        )
        
        self.active_operations[operation.operation_id] = operation
        self._save_operation(operation)
        return operation.operation_id

    def add_file_to_operation(self, operation_id: str, filepath: str, 
                            status: OperationStatus, error_message: Optional[str] = None):
        if operation_id not in self.active_operations:
            return

        operation = self.active_operations[operation_id]
        if not any(f.filepath == filepath for f in operation.files):
            file_record = FileRecord(
                filepath=filepath,
                timestamp=datetime.now(),
                status=status,
                error_message=error_message,
                operation_id=operation_id
            )
            operation.files.append(file_record)
            self._save_file_record(file_record)
            self.update_operation_status(operation_id)

    def complete_operation(self, operation_id: str, final_status: OperationStatus,
                           error_message: Optional[str] = None, user_email: Optional[str] = None):
        if operation_id in self.active_operations:
            operation = self.active_operations[operation_id]
            operation.status = final_status
            operation.error_message = error_message
            # Preserve the original user_email if it exists and no new one is provided
            operation.user_email = user_email or operation.user_email or self.current_user_email
            self._update_operation(operation)
            del self.active_operations[operation_id]
        
    def get_operation(self, operation_id: str) -> Optional[Operation]:
        """Get an operation by ID with improved user attribution handling"""
        # First check active operations
        if operation_id in self.active_operations:
            return self.active_operations[operation_id]
            
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT o.*, f.filepath, f.timestamp, f.status, f.error_message
                    FROM operations o
                    LEFT JOIN file_records f ON o.operation_id = f.operation_id
                    WHERE o.operation_id = ?
                """, (operation_id,))
                
                rows = cursor.fetchall()
                if not rows:
                    return None
                    
                # Create operation from first row with explicit user attribution
                operation = Operation(
                    operation_id=rows[0][0],
                    timestamp=datetime.fromisoformat(rows[0][1]),
                    source=InitiationSource(rows[0][2]),
                    status=OperationStatus(rows[0][3]),
                    operation_type=rows[0][4],
                    user_email=rows[0][5],  # Explicitly preserve user attribution
                    error_message=rows[0][6],
                    files=[]
                )
                
                # Add file records
                for row in rows:
                    if row[8]:  # If file record exists
                        operation.files.append(FileRecord(
                            filepath=row[8],
                            timestamp=datetime.fromisoformat(row[9]),
                            status=OperationStatus(row[10]),
                            error_message=row[11],
                            operation_id=operation_id
                        ))
                        
                return operation
                
        except sqlite3.Error as e:
            logging.error(f"Database error getting operation: {e}")
            return None

    def _save_operation(self, operation: Operation):
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Add logging to track user attribution
                logging.info(f"Saving operation {operation.operation_id} with user: {operation.user_email}")
                
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
            raise

    def _update_operation(self, operation: Operation):
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Add logging to track user attribution updates
                logging.info(f"Updating operation {operation.operation_id} with user: {operation.user_email}")
                
                conn.execute("""
                    UPDATE operations SET
                    status = ?,
                    error_message = ?,
                    user_email = ?,
                    last_modified = ?
                    WHERE operation_id = ?
                """, (
                    operation.status.value,
                    operation.error_message,
                    operation.user_email,
                    datetime.now().isoformat(),
                    operation.operation_id
                ))
        except sqlite3.Error as e:
            logging.error(f"Database error updating operation: {e}")
            raise

    def _save_file_record(self, file_record: FileRecord):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO file_records
                    (operation_id, filepath, timestamp, status, error_message)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    file_record.operation_id,
                    file_record.filepath,
                    file_record.timestamp.isoformat(),
                    file_record.status.value,
                    file_record.error_message
                ))
        except sqlite3.Error as e:
            logging.error(f"Database error saving file record: {e}")

class OperationHistoryPanel(QWidget):
    """UI panel displaying backup/restore history.

    Key Functions:
    - Displays hierarchical operation history
    - Provides filtering and search
    - Shows operation details and status

    Implementation Details:
    - Qt tree widget with custom delegates
    - Filter system for operations
    - Auto-refresh mechanism
    - Custom tree display formatting

    Application Integration:
    - Main history display component
    - Works with HistoryManager
    - Updates based on operations
    """
    
    def __init__(self, event_type: str, history_manager: HistoryManager, theme_manager, parent=None):
        super().__init__(parent)
        self.event_type = event_type
        self.history_manager = history_manager
        self.theme_manager = theme_manager
        self.user_expanded_states = {}
        self.current_page = 1
        self.scroll_position = 0
        self.custom_style = CustomTreeCarrot(self.theme_manager)
        self.current_offset = 0
        self.is_loading = False
        self.batch_size = 0
        self.thread = None
        self.worker = None        
        
        # Track current filter state
        self.current_filters = {
            'search_text': '',
            'date_range': 'All Time',
            'status': 'All Statuses'
        }
        
        self.init_ui()
        self.load_history()
        
        # Set up refresh timer
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.check_and_refresh_history)
        self.refresh_timer.start(2000)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # Remove panel margins since we're adding a header

        # Add header
        header = QLabel("Device History")
        header.setObjectName("HeaderLabel")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        # Main content widget with proper margins
        content = QWidget()
        content.setObjectName("ContentWidget")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 10, 10, 10)

        # Create filter layout
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)

        # Search box
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("Search history...")
        self.search_box.textChanged.connect(self.filter_operations)
        filter_layout.addWidget(self.search_box, 1)

        # Add some spacing between search and filters
        filter_layout.addSpacing(20)

        # History Type dropdown with label
        history_type_label = QLabel("History Type:")
        history_type_label.setObjectName("filter-label")
        self.history_type_combo = QComboBox()
        self.history_type_combo.addItems(["Backup", "Restore"])
        self.history_type_combo.setFixedWidth(150)
        self.history_type_combo.currentTextChanged.connect(self.on_history_type_changed)
        filter_layout.addWidget(history_type_label)
        filter_layout.addWidget(self.history_type_combo)

        # Date Range filter
        date_label = QLabel("Date Range:")
        date_label.setObjectName("filter-label")
        self.date_range = QComboBox()
        self.date_range.addItems(["All Time", "Last 24 Hours", "Last 7 Days", "Last 30 Days"])
        self.date_range.currentTextChanged.connect(self.filter_operations)
        filter_layout.addWidget(date_label)
        filter_layout.addWidget(self.date_range)

        # Status filter
        status_label = QLabel("Status:")
        status_label.setObjectName("filter-label")
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All Statuses", "Success", "Failed", "In Progress"])
        self.status_filter.currentTextChanged.connect(self.filter_operations)
        filter_layout.addWidget(status_label)
        filter_layout.addWidget(self.status_filter)

        content_layout.addLayout(filter_layout)

        # Tree widget setup with proper column headers
        self.tree = QTreeWidget()
        self.tree.setObjectName("HistoryTree")
        self.tree.setStyle(self.custom_style)
        self.tree.setHeaderLabels([
            "Time",
            "Source",
            "Status",
            "User",
            "Details"
        ])
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree.itemExpanded.connect(self.on_item_expanded)
        self.tree.itemCollapsed.connect(self.on_item_collapsed)
        
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.DescendingOrder)

        # Set column sizing
        for i in range(5):
            self.tree.header().setSectionResizeMode(i, QHeaderView.ResizeToContents)

        content_layout.addWidget(self.tree)

        # Load More button (hidden by default)
        self.load_more_btn = QPushButton("Load More")
        self.load_more_btn.clicked.connect(self.load_more)
        self.load_more_btn.hide()
        content_layout.addWidget(self.load_more_btn)

        # Add content widget to main layout
        layout.addWidget(content)

    def set_history_manager(self, manager):
        """Set history manager after initialization"""
        self.history_manager = manager

    def show_loading(self):
        """Show loading indicator"""
        self.tree.clear()
        loading_item = QTreeWidgetItem(["Loading history..."])
        self.tree.addTopLevelItem(loading_item)

    def init_load_timer(self):
        self.load_timer = QTimer(self)
        self.load_timer.timeout.connect(self.load_next_batch)
        
    def load_data(self):
        if not self.is_loading:
            self.is_loading = True
            self.current_offset = 0
            self.tree.clear()
            self.load_next_batch()

    def load_next_batch(self):
        events = self.history_manager.get_history(
            self.event_type, 
            limit=self.batch_size, 
            offset=self.current_offset
        )
        
        if events:
            for event in events:
                self.add_operation_to_tree(event)
            self.current_offset += len(events)
            
            if len(events) == self.batch_size:
                QTimer.singleShot(10, self.load_next_batch)
            else:
                self.is_loading = False
        else:
            self.is_loading = False
        
        QApplication.processEvents()

    def load_history(self):
        """Start asynchronous history loading"""
        if not self.history_manager:
            self.show_error("History manager not initialized")
            return
            
        self.thread = QThread()
        self.worker = HistoryWorker(self.history_manager, self.event_type)
        self.worker.moveToThread(self.thread)
        
        # Connect signals
        self.thread.started.connect(self.worker.run)
        self.worker.batch_ready.connect(self.on_batch_ready)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.finished.connect(self.on_history_complete)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        
        self.thread.start()

    def on_batch_ready(self, operation):
        if self.tree.topLevelItemCount() == 1 and self.tree.topLevelItem(0).text(0) == "Loading history...":
            self.tree.clear()
        self.add_operation_to_tree(operation)

    def on_history_loaded(self, events):
        self.tree.clear()
        for event in events:
            self.add_operation_to_tree(event)

    def on_history_complete(self):
        if self.tree.topLevelItemCount() == 0:
            no_history = QTreeWidgetItem(["No history found"])
            self.tree.addTopLevelItem(no_history)

    def add_operation_to_tree(self, event):
        summary_item = self.create_operation_summary_item(event)
        
        for file_record in sorted(event.files, key=lambda x: x.timestamp, reverse=True):
            file_item = self.create_file_item(file_record, event.source.value)
            summary_item.addChild(file_item)
        
        self.tree.addTopLevelItem(summary_item)
        
        # Apply expansion state
        should_expand = (event.operation_id in self.user_expanded_states and 
                        self.user_expanded_states[event.operation_id]) or event.status == OperationStatus.IN_PROGRESS
        summary_item.setExpanded(should_expand)

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

    def on_error(self, error_msg):
        self.tree.clear()
        error_item = QTreeWidgetItem([f"Error loading history: {error_msg}"])
        error_item.setForeground(0, QColor("#DC3545"))
        self.tree.addTopLevelItem(error_item)

    def refresh_history(self):
        """Refresh the history display"""
        self.current_page = 1
        self.tree.clear()
        events = self.history_manager.get_history(self.event_type, self.current_page)
        
        if events:
            for event in events:
                self.add_operation_to_tree(event)
            
            if len(events) == self.history_manager.page_size:
                self.load_more_btn.show()
            else:
                self.load_more_btn.hide()

    def refresh_history_with_events(self, events):
        """Refresh history while preserving expansion and filter states"""
        self.tree.clear()
        current_ops = set()

        for event in events:
            current_ops.add(event.operation_id)
            summary_item = self.create_operation_summary_item(event)
            
            # Add file details as child items, passing the parent's source
            for file_record in sorted(event.files, key=lambda x: x.timestamp, reverse=True):
                file_item = self.create_file_item(file_record, event.source.value)
                summary_item.addChild(file_item)
            
            self.tree.addTopLevelItem(summary_item)
            
            # Restore expansion state
            should_expand = False
            if event.operation_id in self.user_expanded_states:
                should_expand = self.user_expanded_states[event.operation_id]
            elif event.status == OperationStatus.IN_PROGRESS:
                should_expand = True
                self.user_expanded_states[event.operation_id] = True
            
            summary_item.setExpanded(should_expand)

        # Clean up tracking for removed operations
        self.user_expanded_states = {
            op_id: state 
            for op_id, state in self.user_expanded_states.items() 
            if op_id in current_ops
        }

        # Resize columns to content
        for i in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(i)
            
        # Reapply current filters after refresh
        self.apply_current_filters()

    def check_and_refresh_history(self):
        """Check for changes before refreshing"""
        self.save_scroll_position()
        
        if self.history_manager.has_changes(self.event_type):
            events = self.history_manager.get_history(self.event_type)
            if events:
                self.refresh_history_with_events(events)
            
        self.restore_scroll_position()
        
        # Reapply current filters after refresh
        self.apply_current_filters()

    def check_scroll_position(self, value):
        scrollbar = self.tree.verticalScrollBar()
        if scrollbar.value() == scrollbar.maximum() and self.load_more_btn.isVisible():
            self.load_more()

    def load_more(self):
        if not self.is_loading_more:
            self.is_loading_more = True
            self.current_page += 1
            
            events = self.history_manager.get_history(self.event_type, self.current_page)
            
            if events:
                for event in events:
                    self.add_operation_to_tree(event)
                
                if len(events) < self.history_manager.page_size:
                    self.load_more_btn.hide()
            else:
                self.load_more_btn.hide()
            
            self.is_loading_more = False

    def create_operation_summary_item(self, event: HistoryEvent) -> QTreeWidgetItem:
        status_counts = {
            OperationStatus.SUCCESS: 0,
            OperationStatus.FAILED: 0,
            OperationStatus.IN_PROGRESS: 0
        }
        
        for file_record in event.files:
            status_counts[file_record.status] = status_counts.get(file_record.status, 0) + 1
        
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

        item = QTreeWidgetItem([
            event.timestamp.strftime("%Y-%m-%d %H:%M"),
            event.source.value,
            event.status.value,
            event.user_email or "System",
            details
        ])
        
        # Store operation ID
        item.setData(0, Qt.UserRole, event.operation_id)
        
        self.set_item_status_color(item, event.status)
        font = item.font(0)
        font.setBold(True)
        for i in range(5):
            item.setFont(i, font)
        
        return item
    
    def create_file_item(self, file_record: FileOperationRecord, parent_source: str) -> QTreeWidgetItem:
        """Create a tree item for a file record with its individual timestamp"""
        item = QTreeWidgetItem([
            file_record.timestamp.strftime("%I:%M:%S %p"),  # Time
            parent_source,                                   # Source (inherited from parent)
            file_record.status.value,                       # Status
            "",                                             # User (blank for file items)
            file_record.filepath                            # File path
        ])
        
        # Store file data for reference
        item.setData(0, Qt.UserRole, file_record.filepath)
        
        # Set status-based styling
        self.set_item_status_color(item, file_record.status)
        
        # Add error message as a child item if present
        if file_record.error_message:
            error_item = QTreeWidgetItem([
                "",                 # Time
                "",                 # Source
                "",                 # Status
                "",                 # User
                f"Error: {file_record.error_message}"  # Error message
            ])
            error_item.setForeground(4, QColor("#DC3545"))  # Red color for errors
            item.addChild(error_item)
        
        return item

    def filter_operations(self):
        """Store and apply new filter criteria"""
        # Update stored filter state
        self.current_filters['search_text'] = self.search_box.text().lower()
        self.current_filters['date_range'] = self.date_range.currentText()
        self.current_filters['status'] = self.status_filter.currentText()
        
        # Apply the filters
        self.apply_current_filters()

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

    def apply_current_filters(self):
        """Apply stored filters to the current tree"""
        search_text = self.current_filters['search_text']
        date_filter = self.current_filters['date_range']
        status_filter = self.current_filters['status']
        
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            show_item = True
            
            # Build searchable text from all columns
            item_text = ' '.join([
                item.text(col) for col in range(item.columnCount())
            ]).lower()
            
            # Include child items in search
            child_matches = []
            for j in range(item.childCount()):
                child = item.child(j)
                child_text = ' '.join([
                    child.text(col) for col in range(child.columnCount())
                ]).lower()
                item_text += ' ' + child_text
                
                # Store whether each child matches the search text
                child_matches.append(not search_text or search_text in child_text)
            
            # Apply text filter
            if search_text and search_text not in item_text:
                show_item = False
            
            # Apply status filter
            if status_filter != "All Statuses":
                if item.text(2) != status_filter:
                    show_item = False
                    
            # Apply date filter
            if show_item and date_filter != "All Time":
                try:
                    item_date = datetime.strptime(item.text(0), "%Y-%m-%d %H:%M")
                    now = datetime.now()
                    
                    date_visible = True
                    if date_filter == "Last 24 Hours":
                        date_visible = item_date >= now - timedelta(days=1)
                    elif date_filter == "Last 7 Days":
                        date_visible = item_date >= now - timedelta(days=7)
                    elif date_filter == "Last 30 Days":
                        date_visible = item_date >= now - timedelta(days=30)
                    
                    if not date_visible:
                        show_item = False
                except ValueError:
                    logging.error(f"Failed to parse date: {item.text(0)}")
            
            # Show/hide the item and its children
            item.setHidden(not show_item)
            
            if show_item:
                # Only show children that match the search text if parent is visible
                for j in range(item.childCount()):
                    child = item.child(j)
                    child.setHidden(not child_matches[j])
            else:
                # Hide all children if parent is hidden
                for j in range(item.childCount()):
                    child = item.child(j)
                    child.setHidden(True)

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
            "Backup": "backup",
            "Restore": "restore"
        }
        self.event_type = history_type_map[history_type]
        
        # Force a refresh when switching history types
        if self.history_manager:
            events = self.history_manager.get_history(self.event_type)
            # Always refresh UI, even with empty list
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

    def apply_theme(self):
        """Apply theme to all widgets"""
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        
        # Style for labels
        label_style = f"""
            QLabel#filter-label {{
                color: {theme['text_primary']};
                margin-right: 4px;
            }}
        """
        
        # Style for search box
        search_style = f"""
            QLineEdit {{
                background-color: {theme['input_background']};
                color: {theme['text_primary']};
                border: 1px solid {theme['input_border']};
                border-radius: 4px;
                padding: 5px 8px;
                min-height: 20px;
            }}
            QLineEdit:focus {{
                border-color: {theme['accent_color']};
            }}
        """
        
        # Style for combo boxes
        combo_style = f"""
            QComboBox {{
                background-color: {theme['input_background']};
                color: {theme['text_primary']};
                border: 1px solid {theme['input_border']};
                border-radius: 4px;
                padding: 4px 8px;
                min-height: 20px;
            }}
            QComboBox:hover {{
                border-color: {theme['accent_color']};
            }}
            QComboBox::drop-down {{
                border: none;
                padding-right: 4px;
            }}
            QComboBox::down-arrow {{
                image: url(down-arrow-{self.theme_manager.current_theme.lower()}.png);
            }}
        """
        
        # Apply styles
        for label in self.findChildren(QLabel, "filter-label"):
            label.setStyleSheet(label_style)
        
        self.search_box.setStyleSheet(search_style)
        
        for combo in [self.date_range, self.status_filter, self.history_type_combo]:
            combo.setStyleSheet(combo_style)

class HistoryWorker(QObject):
    """Asynchronous worker for loading operation history.

    Key Functions:
    - Loads operation history in batches
    - Emits progress updates and results

    Implementation Details:
    - Qt signal/slot mechanism
    - SQLite queries
    - Non-blocking operation

    Application Integration:
    - Used by HistoryPanel for data loading
    - Updates UI with operation history
    """

    batch_ready = pyqtSignal(object)  # Single operation ready
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()
    
    def __init__(self, history_manager, operation_type):
        super().__init__()
        self.history_manager = history_manager
        self.operation_type = operation_type
        
    def run(self):
        try:
            with sqlite3.connect(self.history_manager.db_path) as conn:
                cursor = conn.cursor()
                
                # Get top 20 operations
                cursor.execute("""
                    SELECT operation_id, timestamp, source, status, operation_type, user_email, error_message
                    FROM operations 
                    WHERE operation_type = ?
                    ORDER BY timestamp DESC
                    LIMIT 20
                """, (self.operation_type,))
                
                # Process each operation individually
                for row in cursor.fetchall():
                    op_id = row[0]
                    operation = Operation(
                        operation_id=op_id,
                        timestamp=datetime.fromisoformat(row[1]),
                        source=InitiationSource(row[2]),
                        status=OperationStatus(row[3]),
                        operation_type=row[4],
                        user_email=row[5],
                        error_message=row[6],
                        files=[]
                    )
                    
                    # Get files for this operation
                    cursor.execute("""
                        SELECT filepath, timestamp, status, error_message
                        FROM file_records
                        WHERE operation_id = ?
                        ORDER BY timestamp DESC
                    """, (op_id,))
                    
                    for file_row in cursor.fetchall():
                        operation.files.append(FileRecord(
                            filepath=file_row[0],
                            timestamp=datetime.fromisoformat(file_row[1]),
                            status=OperationStatus(file_row[2]),
                            error_message=file_row[3],
                            operation_id=op_id
                        ))
                    
                    # Emit each operation as it's ready
                    self.batch_ready.emit(operation)
                    
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self.finished.emit()
# -----------

# Main app window
# -----------
class StormcloudApp(QMainWindow):
    """Main application window managing core functionality and UI.

    Key Functions:
    - Manages user authentication and session state
    - Controls backup engine operations
    - Handles filesystem indexing and searching
    - Manages core services initialization
    - Controls UI tabs and panels

    Implementation Details:
    - Qt main window architecture
    - Multi-threaded operation handling
    - SQLite databases for various functions
    - Background process management
    - Theme system integration
    - Windows API integration (process management)
    - Network operations for cloud services
    - File system monitoring
    - Secure credential storage

    Application Integration:
    - Core application controller
    - Manages all major subsystems:
       - Authentication system
       - Backup engine
       - File explorer
       - History tracking
       - Theme management
       - Search functionality
       - Configuration management
    - Coordinates between UI components and backend services
    - Handles application lifecycle
    """

    def __init__(self):
        super().__init__()
        
        # Add process registry as one of the first initializations
        self.process_registry = ProcessRegistry()
        
        self.theme_manager = ThemeManager()
        self.user_email = None
        self._operation_in_progress = False  # Add flag here too
        
        # Set window title and initial theme
        self.setWindowTitle('Stormcloud Backup Manager')
        self.apply_base_theme()
        
        logging.info("Application session initiated. Attempting user authentication.")
        
        # Initialize paths first
        self.init_paths()
        
        # Attempt login before initializing UI
        if not self.authenticate_user():
            logging.info("Authentication failed.")
            sys.exit(0)
        
        logging.info("Authentication succeeded. User: {}".format(self.user_email))
        
        # Initialize core services
        self.init_core_services()
        
        # Update history manager with authenticated user
        if hasattr(self, 'history_manager'):
            self.history_manager.current_user_email = self.user_email
        
        # Initialize UI
        self.set_app_icon()
        self.create_spinbox_arrow_icons()
        self.init_ui()
        
        # Apply theme to all widgets
        self.apply_theme()
        
        # Initialize filesystem indexing
        self.init_indexing()
        
        # Initialize metadata refresh timer
        self.init_metadata_refresh()
        
        # Check initial backup engine status
        self.update_status()
        
        # Start deferred loading of heavy components
        QTimer.singleShot(0, self.init_components)

    def init_ui(self):
        """Initialize the user interface"""
        # Get theme for styling
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        
        # Create toolbar
        toolbar = QToolBar()
        toolbar.setObjectName("mainToolBar")
        self.addToolBar(Qt.TopToolBarArea, toolbar)
        
        # Add theme selection to toolbar
        theme_label = QLabel("Theme:")
        theme_label.setStyleSheet(f"color: {theme['text_primary']};")
        toolbar.addWidget(theme_label)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark Age Classic Dark", "Light"])
        self.theme_combo.setCurrentText(self.theme_manager.current_theme)
        self.theme_combo.currentTextChanged.connect(self.change_theme)
        self.theme_combo.setFixedWidth(150)
        self.theme_combo.setCursor(Qt.PointingHandCursor)
        toolbar.addWidget(self.theme_combo)

        # Main layout
        main_layout = QVBoxLayout(self.centralWidget())
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.South)
        main_layout.addWidget(self.tab_widget)

        # Create and add tabs
        self.backup_tab = self.create_backup_tab()
        self.tab_widget.addTab(self.backup_tab, "💾 Backup")

    def init_components(self):
        """Initialize heavy components after UI is shown"""
        try:
            # Initialize filesystem index
            self.filesystem_index = FilesystemIndex(self.filesystem_db_path)
            
            # Initialize UI components that depend on filesystem index
            if hasattr(self, 'file_explorer'):
                self.file_explorer.set_filesystem_index(self.filesystem_index)
            
            # Load backup paths and properties
            self.load_backup_paths()
            self.load_properties()
            self.apply_backup_mode()
            
            # Start background data loading
            QTimer.singleShot(0, self.load_initial_data)

        except Exception as e:
            logging.error(f"Failed to initialize components: {e}")
            StormcloudMessageBox.critical(self, "Error", 
                "Failed to initialize application components. Please restart the application.")

    def init_indexing(self):
        """Initialize and start the filesystem indexing process."""
        try:
            self.filesystem_index = FilesystemIndex(self.filesystem_db_path)
            # Start indexing and register the process
            pid = self.filesystem_index.start_indexing()
            if pid and hasattr(self.filesystem_index, 'indexer'):
                self.process_registry.register_process(self.filesystem_index.indexer)
            logging.info("Filesystem indexing process started and registered")
        except Exception as e:
            logging.error(f"Failed to start indexing: {e}")

    def init_paths(self):
        """Initialize all application paths"""
        # Base paths
        self.appdata_path = os.getenv('APPDATA')
        self.app_dir = os.path.join(self.appdata_path, 'Stormcloud')
        os.makedirs(self.app_dir, exist_ok=True)
        
        # Auth file
        self.auth_file = os.path.join(self.app_dir, 'auth.dat')
        
        # Get installation path
        self.install_path = self.get_install_path()
        if not self.install_path:
            raise RuntimeError("Could not determine installation path")
            
        # Database directory
        self.db_dir = os.path.join(self.install_path, 'db')
        os.makedirs(self.db_dir, exist_ok=True)
        
        # Database paths - store just the file paths, not directories
        self.filesystem_db_path = os.path.join(self.db_dir, 'filesystem.db')
        self.history_db_path = os.path.join(self.db_dir, 'history.db')
        
        # Settings path
        self.settings_cfg_path = os.path.join(self.install_path, 'settings.cfg')
        
        # JSON directory
        self.json_directory = self.app_dir
        
    def init_core_services(self):
        """Initialize core services without heavy loading"""
        try:
            # Ensure database directory exists
            os.makedirs(os.path.dirname(self.history_db_path), exist_ok=True)
            
            # Initialize history manager
            self.history_manager = HistoryManager(self.history_db_path)
            
            # Initialize backup schedule
            self.backup_schedule = {'weekly': {}, 'monthly': {}}
            
            # Create systray
            # systray_menu_options = (("Backup now", None, 
                # lambda x: logging.info("User clicked 'Backup now'")),)
            # self.systray = SysTrayIcon("stormcloud.ico", 
                # "Stormcloud Backup Engine", systray_menu_options)
            # self.systray.start()
            
            # Load settings
            self.load_settings()
            
        except Exception as e:
            logging.error(f"Failed to initialize core services: {e}")
            raise

    def init_metadata_refresh(self):
        """Initialize metadata refresh timer"""
        self.metadata_timer = QTimer(self)
        self.metadata_timer.timeout.connect(self.refresh_metadata)
        self.metadata_timer.start(10000)  # 10 second interval
        # Register the timer
        self.process_registry.register_timer(self.metadata_timer)
        
        # Perform initial metadata refresh
        QTimer.singleShot(0, self.refresh_metadata)

    # Methods to set/clear operation flag that both classes can use
    def set_operation_in_progress(self):
        self._operation_in_progress = True
        if hasattr(self, 'file_explorer'):
            self.file_explorer._operation_in_progress = True
        logging.info("Operation flag set")

    def clear_operation_in_progress(self):
        self._operation_in_progress = False
        if hasattr(self, 'file_explorer'):
            self.file_explorer._operation_in_progress = False
        logging.info("Operation flag cleared")

    def refresh_metadata(self):
        """Refresh file metadata from API"""
        if self._operation_in_progress:
            logging.info("Skipping metadata refresh - operation in progress")
            return
            
        try:
            if not hasattr(self, 'settings_cfg_path') or not self.settings_cfg_path:
                logging.error("Settings path not configured")
                return

            settings = read_yaml_settings_file(self.settings_cfg_path)
            if not settings:
                logging.error("Failed to read settings file")
                return

            save_file_metadata(settings)
            logging.info("Metadata refresh completed successfully")
            
            # If we have a file explorer, trigger a refresh of the remote files view
            if hasattr(self, 'file_explorer'):
                self.file_explorer.refresh_remote_files()
                
        except Exception as e:
            logging.error(f"Error refreshing metadata: {e}")
        
    def apply_base_theme(self):
        """Apply initial theme to the main window"""
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        self.setStyleSheet(theme["stylesheet"])
        
        # Create a central widget with proper background
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        central_widget.setStyleSheet(f"QWidget#centralWidget {{ background-color: {theme['app_background']}; }}")
        self.setCentralWidget(central_widget)

    def load_initial_data(self):
        """Load initial data asynchronously"""
        logging.info("Beginning initial data load")
        try:
            # Start filesystem indexing if available
            if hasattr(self, 'filesystem_index'):
                self.filesystem_index._start_indexer()

            # Load initial data for file explorer if it exists
            if hasattr(self, 'file_explorer'):
                self.file_explorer.load_initial_data()
                
            logging.info("Initial data load complete")
            
        except Exception as e:
            logging.error(f"Error loading initial data: {e}", exc_info=True)
            if hasattr(self, 'filesystem_index'):
                try:
                    self.filesystem_index.shutdown()
                except Exception as shutdown_error:
                    logging.error(f"Error during indexer shutdown: {shutdown_error}")
                
    def authenticate_user(self) -> bool:
        while True:
            dialog = LoginDialog(
                theme_manager=self.theme_manager,
                settings_path=self.settings_cfg_path, 
                parent=self
            )
            
            if not dialog.exec_():
                return False
            
            if dialog.user_info:
                self.user_info = dialog.user_info
                self.user_email = dialog.user_info['email']
                self.auth_tokens = dialog.auth_tokens  # Store auth tokens
                
                # Save auth data securely
                self.save_auth_data()
                
                logging.info(f"StormcloudApp stored user email: {self.user_email}")
                return True
            return False

    def save_auth_data(self):
        """Save authentication data securely"""
        try:
            from cryptography.fernet import Fernet
            from base64 import b64encode
            
            # Generate key from machine-specific data
            machine_id = win32api.GetComputerName() + win32api.GetUserName()
            key = b64encode(machine_id.encode()[:32].ljust(32, b'0'))
            cipher_suite = Fernet(key)
            
            auth_data = {
                'user_email': self.user_email,
                'auth_tokens': self.auth_tokens,
                'timestamp': datetime.now().isoformat()
            }
            
            encrypted_data = cipher_suite.encrypt(json.dumps(auth_data).encode())
            
            with open(self.auth_file, 'wb') as f:
                f.write(encrypted_data)
                
            logging.info("Authentication data saved successfully")
            
        except Exception as e:
            logging.error(f"Failed to save authentication data: {e}")

    def load_auth_data(self):
        """Load saved authentication data"""
        try:
            if not os.path.exists(self.auth_file):
                return None
                
            from cryptography.fernet import Fernet
            from base64 import b64encode
            
            machine_id = win32api.GetComputerName() + win32api.GetUserName()
            key = b64encode(machine_id.encode()[:32].ljust(32, b'0'))
            cipher_suite = Fernet(key)
            
            with open(self.auth_file, 'rb') as f:
                encrypted_data = f.read()
                
            decrypted_data = json.loads(cipher_suite.decrypt(encrypted_data))
            
            # Verify timestamp is within last 24 hours
            saved_time = datetime.fromisoformat(decrypted_data['timestamp'])
            if datetime.now() - saved_time > timedelta(hours=24):
                return None
                
            return decrypted_data
            
        except Exception as e:
            logging.error(f"Failed to load authentication data: {e}")
            return None

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
        
        # self.start_button = QPushButton('Start Backup Engine')
        # self.start_button.setObjectName("start_button")
        # self.start_button.setFixedSize(200, 40)
        # self.start_button.clicked.connect(self.toggle_backup_engine)
        # self.start_button.setCursor(Qt.PointingHandCursor)
        
        # header_layout.addWidget(self.start_button)
        # header_layout.addStretch()
        
        return header_widget

    def apply_theme(self):
        """Apply theme to all widgets"""
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        
        # Apply main stylesheet
        self.setStyleSheet(theme["stylesheet"])
        
        # Update central widget background
        if self.centralWidget():
            self.centralWidget().setStyleSheet(
                f"QWidget#centralWidget {{ background-color: {theme['app_background']}; }}"
            )
        
        # Update toolbar style
        if hasattr(self, 'theme_combo'):
            self.theme_combo.setStyleSheet(theme.get("combobox_style", ""))
        
        # Update all panels
        if hasattr(self, 'backup_tab'):
            self.backup_tab.setStyleSheet(theme.get("tab_style", ""))
            
        # Apply theme to specific components
        panels = [
            'file_explorer',
            'history_panel',
            'progress_widget'
        ]
        
        for panel_name in panels:
            if hasattr(self, panel_name):
                panel = getattr(self, panel_name)
                if hasattr(panel, 'apply_theme'):
                    panel.apply_theme()

    def change_theme(self, theme_name):
        """Change the application theme"""
        self.theme_manager.set_theme(theme_name)
        self.apply_theme()
        self.create_spinbox_arrow_icons()  # Recreate icons for the new theme

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
        """Create the operation history panel without extra wrapping"""
        # Create history panel without wrapping it in another panel
        self.history_panel = OperationHistoryPanel('backup', self.history_manager, self.theme_manager)
        return self.history_panel

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
            # self.systray,
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
        
        # Properties section
        properties_widget = self.create_properties_section()
        splitter.addWidget(properties_widget)
        
        # Settings section
        settings_widget = self.create_settings_section()
        splitter.addWidget(settings_widget)
        
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
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)

        # Subpanel header
        header = QLabel("Settings")
        header.setObjectName("SubpanelHeader")
        layout.addWidget(header)

        # Horizontal divider
        horizontal_line = QFrame()
        horizontal_line.setFrameShape(QFrame.HLine)
        horizontal_line.setObjectName("HorizontalDivider")
        layout.addWidget(horizontal_line)

        # Status with proper styling
        status_layout = QHBoxLayout()
        status_label = QLabel('Backup Engine Status:')
        self.status_value_text = QLabel()
        
        status_layout.addWidget(status_label)
        status_layout.addWidget(self.status_value_text)
        layout.addLayout(status_layout)
        
        # Update initial status immediately
        self.update_status()
        
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
        
        # Start button
        self.start_button = AnimatedButton('Start Backup Engine')
        self.start_button.setObjectName("start_button")
        self.start_button.setAsStartButton()
        self.start_button.clicked.connect(self.toggle_backup_engine)
        self.start_button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.start_button)
        
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
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Header with Start Backup Engine button
        header_widget = self.create_header_widget()
        layout.addWidget(header_widget)

        # Grid layout for panels
        grid_widget = QWidget()
        self.grid_layout = QGridLayout(grid_widget)
        
        # Create all panels
        config_dashboard = self.create_configuration_dashboard()
        backup_schedule = self.create_backup_schedule_panel()
        file_explorer = self.create_file_browser_panel()
        operation_history = self.create_bottom_right_panel()
        
        # Add panels to grid
        self.grid_layout.addWidget(config_dashboard, 0, 0)
        self.grid_layout.addWidget(backup_schedule, 0, 1)
        self.grid_layout.addWidget(file_explorer, 1, 0)
        self.grid_layout.addWidget(operation_history, 1, 1)
        
        # Set equal stretches
        self.grid_layout.setColumnStretch(0, 1)
        self.grid_layout.setColumnStretch(1, 1)
        self.grid_layout.setRowStretch(0, 1)
        self.grid_layout.setRowStretch(1, 1)
        
        layout.addWidget(grid_widget)
        return tab

    def create_file_browser_panel(self):  # New method name
        """Create the file browser panel without recursion"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Create single FileExplorerPanel instance
        file_explorer = FileExplorerPanel(
            self.json_directory,
            self.theme_manager,
            self.settings_cfg_path,
            # self.systray,
            self.history_manager,
            self.user_email
        )
        layout.addWidget(file_explorer)
        
        return self.create_panel('File Explorer', panel)

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

        footnote = QLabel("Tip: Check the box to include subfolders in the backup.")
        footnote.setObjectName("FootnoteLabel")
        footnote.setWordWrap(True)
        layout.addWidget(footnote)

        buttons_layout = QHBoxLayout()
        add_folder_button = AnimatedButton("Add Folder")
        add_folder_button.setObjectName("FolderBackupButton")
        add_folder_button.clicked.connect(self.add_backup_folder)
        add_folder_button.setCursor(Qt.PointingHandCursor)
        buttons_layout.addWidget(add_folder_button)

        remove_folder_button = AnimatedButton("Remove Selected")
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
        widget.setMinimumWidth(200)  # Minimum width constraint
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(10, 5, 10, 5)  # Increased margins
        layout.setSpacing(10)  # Added explicit spacing

        checkbox = QCheckBox()
        checkbox.setChecked(recursive)
        checkbox.stateChanged.connect(lambda state, f=folder: self.toggle_recursive(f, state == Qt.Checked))
        checkbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        label = QLabel(folder)
        label.setWordWrap(True)
        label.setMinimumWidth(150)  # Minimum text width
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # Override any inherited styles
        label.setStyleSheet("""
            QLabel {
                padding: 2px;
                background: transparent;
                border: none;
            }
        """)

        layout.addWidget(checkbox)
        layout.addWidget(label, stretch=2)  # Increased stretch factor
        layout.setAlignment(Qt.AlignLeft)

        # Set size policies for the widget
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
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
        """Update backup engine status display"""
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        running_state = self.is_backup_engine_running()
        
        if running_state is None:
            status_text = 'Unknown'
            color = theme['status_unknown']
        else:
            status_text = 'Running' if running_state else 'Not Running'
            color = theme['status_running'] if running_state else theme['status_not_running']

        if hasattr(self, 'status_value_text'):
            self.status_value_text.setText(status_text)
            self.status_value_text.setStyleSheet(f"color: {color};")
        
        if hasattr(self, 'start_button'):
            self.start_button.setRunning(bool(running_state))
            button_text = 'Stop Backup Engine' if running_state else 'Start Backup Engine'
            self.start_button.setText(button_text)
    
    def toggle_backup_engine(self):
        """Toggle the backup engine between running and stopped states"""
        if self.is_backup_engine_running():
            self.stop_backup_engine()
        else:
            self.start_backup_engine()
        
    def is_backup_engine_running(self):
        """Check if backup engine is currently running"""
        try:
            return any(proc.info['name'] == 'stormcloud.exe' 
                      for proc in psutil.process_iter(['name']))
        except Exception as e:
            logging.error(f"Error checking backup engine status: {e}")
            return None

    def start_backup_engine(self):
        """Start the backup engine and record the operation"""
        if self.is_backup_engine_running():
            StormcloudMessageBox.information(self, 'Info', 'Backup engine is already running.')
            return

        try:
            # Get the executable path
            exe_path = os.path.join(os.path.dirname(self.settings_cfg_path), 'stormcloud.exe').replace('\\', '/')
            
            # Start the process
            subprocess.Popen([exe_path], shell=True, cwd=os.path.dirname(self.settings_cfg_path))
            logging.info('Backup engine started successfully at %s', exe_path)
            
            # Record operation in history if in realtime mode
            if hasattr(self, 'backup_mode') and self.backup_mode == 'Realtime' and hasattr(self, 'history_manager'):
                operation_id = self.history_manager.start_operation(
                    'backup',
                    InitiationSource.REALTIME,
                    self.user_email
                )
                logging.info(f'Started backup operation with ID: {operation_id}')
            
            StormcloudMessageBox.information(self, 'Info', 'Backup engine started successfully.')
            
        except Exception as e:
            logging.error('Failed to start backup engine: %s', e)
            StormcloudMessageBox.critical(self, 'Error', f'Failed to start backup engine: {e}')
        finally:
            self.update_status()
        
    def stop_backup_engine(self):
        """Stop the backup engine and update history"""
        if not self.is_backup_engine_running():
            StormcloudMessageBox.information(self, 'Info', 'Backup engine is not running.')
            return

        try:
            # Find all stormcloud processes
            stormcloud_processes = [proc for proc in psutil.process_iter(['name', 'pid'])
                                  if proc.info['name'] == 'stormcloud.exe']
            
            if not stormcloud_processes:
                logging.info('No stormcloud processes found to stop')
                return
                
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
            
            # Update any active operations in history
            if hasattr(self, 'history_manager'):
                # Create a list copy of operation IDs to avoid modification during iteration
                active_op_ids = list(self.history_manager.active_operations.keys())
                for op_id in active_op_ids:
                    try:
                        self.history_manager.complete_operation(
                            op_id,
                            OperationStatus.FAILED,
                            "Backup engine stopped by user",
                            self.user_email
                        )
                    except Exception as e:
                        logging.error(f'Failed to complete operation {op_id}: {e}')
            
            logging.info('All stormcloud processes stopped successfully.')
            StormcloudMessageBox.information(self, 'Info', 'Backup engine stopped successfully.')
                    
        except Exception as e:
            logging.error('Failed to stop backup engine: %s', e)
            StormcloudMessageBox.critical(self, 'Error', f'Failed to stop backup engine: {e}')
        finally:
            self.update_status()

    def shutdown(self):
        """Gracefully shut down the application and stop the indexer."""
        try:
            if hasattr(self, 'filesystem_index') and self.filesystem_index.indexer:
                if self.filesystem_index.indexer.is_alive():
                    logging.info("Shutting down filesystem indexer...")
                    self.filesystem_index.shutdown_event.set()  # Signal the indexer to stop
                    self.filesystem_index.indexer.join()  # Wait for the process to finish
        except Exception as e:
            logging.error(f"Error during shutdown: {e}")
        finally:
            logging.info("Application shutdown complete")
# -----------

# Calendar Widget
# -----------
class TimeSlot(QPushButton):
    """Interactive time slot button for schedule selection.

    Key Functions:
    - Represents individual time slots in schedule
    - Emits signals with time data
    - Manages selection state

    Implementation Details:
    - Qt button with custom signals
    - Time management using QTime

    Application Integration:
    - Used by backup schedule calendar
    - Coordinates schedule selection
    """

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
    """Backup schedule management calendar.

    Key Functions:
    - Manages weekly/monthly backup schedules
    - Provides visual schedule display
    - Handles schedule modifications

    Implementation Details:
    - Custom Qt widget layout
    - Schedule data structures
    - Theme integration
    - Time slot management
    - Event handling system

    Application Integration:
    - Main schedule interface
    - Updates backup configuration
    - Works with theme system
    """

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

        self.add_weekly_button = AnimatedButton("Add Weekly Backup")
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

        self.add_monthly_button = AnimatedButton("Add Monthly Backup")
        self.add_monthly_button.clicked.connect(self.add_monthly_backup)
        self.add_monthly_button.setCursor(Qt.PointingHandCursor)
        monthly_layout.addWidget(self.add_monthly_button)

        backup_types_layout.addWidget(monthly_group)

        schedule_layout.addLayout(backup_types_layout)

        # Combined schedule list
        self.schedule_list = QListWidget()
        schedule_layout.addWidget(self.schedule_list, 1)  # Give it more vertical space

        self.remove_button = AnimatedButton("Remove Selected")
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
    """Enhanced calendar widget for schedule visualization.

    Key Functions:
    - Shows scheduled backup days
    - Provides custom navigation
    - Displays schedule status

    Implementation Details:
    - Custom Qt calendar widget
    - Theme-aware rendering
    - Custom navigation controls
    - Schedule visualization system

    Application Integration:
    - Used by BackupScheduleCalendar
    - Shows backup schedule state
    - Theme system integration
    """

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
        """Determine if a backup is scheduled for the given date."""
        # Check weekly schedule
        day_name = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][date.dayOfWeek() - 1]
        if day_name in self.schedule['weekly'] and self.schedule['weekly'][day_name]:
            return True

        # Check monthly schedule
        day_of_month = str(date.day())  # Convert to string to match schedule format
        if day_of_month in self.schedule['monthly'] and self.schedule['monthly'][day_of_month]:
            return True

        # Check for last day of month scheduling
        if "Last day" in self.schedule['monthly'] and self.schedule['monthly']["Last day"]:
            if date.day() == date.daysInMonth():
                return True

        return False
    
    def update_schedule(self, schedule):
        self.schedule = schedule
        self.updateCells()
# -----------

# File Explorer Panel
# -----------
class FileExplorerPanel(QWidget):
    """Main file explorer interface managing local and remote file browsing.

    Key Functions:
    - Displays local filesystem and remote backup content
    - Handles drag-drop for backup/restore operations
    - Provides file search functionality
    - Manages file operations and progress tracking
    - Handles file metadata display

    Implementation Details:
    - Qt widgets with split views
    - Custom tree models and delegates
    - Background workers for search/operations
    - Progress tracking system
    - Windows API integration
    - SQLite database for search indexing
    - Network operations for remote content
    - Theme integration

    Application Integration:
    - Core file management interface
    - Works with backup/restore systems
    - Uses HistoryManager for tracking
    - Coordinates with theme system
    """

    def __init__(self, json_directory, theme_manager, settings_cfg_path=None, 
                 # systray=None,
                 history_manager=None, user_email=None):
        super().__init__()
        
        # Get process registry instance
        self.process_registry = ProcessRegistry()
        
        self.setObjectName("FileExplorerPanel")

        self._drag_source_item = None
        self._drag_source_path = None
        
        # Add flag to prevent auto-refresh during operations
        self._operation_in_progress = False

        self.theme_manager = theme_manager
        self.settings_path = settings_cfg_path
        # self.systray = systray
        self.history_manager = history_manager
        self._user_email = user_email
        self.custom_style = CustomTreeCarrot(self.theme_manager)

        # Initialize filesystem index
        index_db = os.path.join(json_directory, 'db', 'filesystem.db')
        self.filesystem_index = FilesystemIndex(index_db)
        
        # Status checking timer
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.check_indexing_status)
        self.status_timer.start(1000)  # Check every second
        self.process_registry.register_timer(self.status_timer)
        
        self.install_path = self.get_install_path()
        if self.install_path:
            self.metadata_dir = os.path.join(self.install_path, 'file_explorer', 'manifest')
            os.makedirs(self.metadata_dir, exist_ok=True)
        
        self.search_history = []
        
        # Create progress widget before initializing UI
        self.progress_widget = OperationProgressWidget(self)
        if self.history_manager:
            self.progress_widget.history_manager = self.history_manager
        self.progress_widget.user_email = self._user_email
        self.progress_widget.operation_completed.connect(self.on_operation_completed)
        
        self.init_models()
        self.init_ui()
        
        # Add theme change connection
        self.theme_manager.theme_changed.connect(self.on_theme_changed)
        
        QTimer.singleShot(100, self.load_data)

    @property
    def user_email(self) -> Optional[str]:
        return self._user_email

    @user_email.setter
    def user_email(self, email: Optional[str]):
        self._user_email = email
        if hasattr(self, 'progress_widget'):
            self.progress_widget.user_email = email
        logging.info(f"FileExplorerPanel user_email updated to: {email}")

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(3)
        layout.addWidget(main_splitter)

        # Local files panel
        local_panel = QWidget()
        local_layout = QVBoxLayout(local_panel)
        local_layout.setContentsMargins(0, 0, 0, 0)

        # Add results panel initialization here
        self.results_panel = QTreeWidget()
        self.results_panel.setObjectName("ResultsPanel")
        self.results_panel.setHeaderHidden(True)
        self.results_panel.setItemDelegate(SearchResultDelegate(self.theme_manager))
        self.results_panel.setVisible(False)
        local_layout.addWidget(self.results_panel)

        # Local header
        local_header = QLabel("Local Files")
        local_header.setObjectName("SubpanelHeader")
        local_layout.addWidget(local_header)

        local_line = QFrame()
        local_line.setFrameShape(QFrame.HLine)
        local_line.setObjectName("HorizontalDivider")
        local_layout.addWidget(local_line)

        # Local search
        self.local_search = QLineEdit()
        self.local_search.setObjectName("SearchBox")
        self.local_search.setPlaceholderText("Search local files...")
        self.local_search.returnPressed.connect(self.search_local)
        local_layout.addWidget(self.local_search)

        # Add progress bars with custom styling
        progress_style = """
            QProgressBar {
                background-color: #666666;
                border: none;
                border-radius: 2px;
                height: 4px;
            }
            QProgressBar::chunk {
                background-color: #4285F4;
                width: 10px;
                margin: 0px;
            }
        """
        
        # Local progress bar
        self.local_progress = QProgressBar()
        self.local_progress.setVisible(False)
        self.local_progress.setTextVisible(False)
        self.local_progress.setStyleSheet(progress_style)
        local_layout.addWidget(self.local_progress)

        # Local vertical splitter
        self.local_splitter = QSplitter(Qt.Vertical)
        self.local_splitter.setHandleWidth(3)
        local_layout.addWidget(self.local_splitter)

        # Local tree
        self.local_tree = QTreeView()
        self.local_tree.setObjectName("LocalTree")
        self.local_tree.setModel(self.local_model)
        self.local_tree.setHeaderHidden(True)
        self.local_tree.expanded.connect(self.on_item_expanded)
        self.local_tree.clicked.connect(self.on_item_clicked)
        self.local_tree.setIndentation(20)
        self.local_tree.setStyle(self.custom_style)
        self.local_tree.setDragEnabled(True)
        self.local_tree.setAcceptDrops(True)
        self.local_tree.setDropIndicatorShown(False)
        self.local_tree.setDragDropMode(QTreeView.InternalMove)
        self.local_tree.viewport().installEventFilter(self)
        self.local_splitter.addWidget(self.local_tree)

        # Local search results
        self.local_results = QTreeWidget()
        self.local_results.setObjectName("ResultsPanel")
        self.local_results.setHeaderHidden(True)
        self.local_results.itemClicked.connect(self.navigate_to_local_result)
        self.local_results.setVisible(False)
        self.local_results.setStyle(self.custom_style)
        self.local_splitter.addWidget(self.local_results)

        main_splitter.addWidget(local_panel)

        # Remote files panel
        remote_panel = QWidget()
        remote_layout = QVBoxLayout(remote_panel)
        remote_layout.setContentsMargins(0, 0, 0, 0)

        # Remote header
        remote_header = QLabel("Remote Files")
        remote_header.setObjectName("SubpanelHeader")
        remote_layout.addWidget(remote_header)

        remote_line = QFrame()
        remote_line.setFrameShape(QFrame.HLine)
        remote_line.setObjectName("HorizontalDivider")
        remote_layout.addWidget(remote_line)

        # Remote search
        self.remote_search = QLineEdit()
        self.remote_search.setObjectName("SearchBox")
        self.remote_search.setPlaceholderText("Search remote files...")
        self.remote_search.returnPressed.connect(self.search_remote)
        remote_layout.addWidget(self.remote_search)

        # Remote progress bar with same styling
        self.remote_progress = QProgressBar()
        self.remote_progress.setVisible(False)
        self.remote_progress.setTextVisible(False)
        self.remote_progress.setStyleSheet(progress_style)
        remote_layout.addWidget(self.remote_progress)

        # Remote vertical splitter
        self.remote_splitter = QSplitter(Qt.Vertical)
        self.remote_splitter.setHandleWidth(3)
        remote_layout.addWidget(self.remote_splitter)

        # Remote tree
        self.remote_tree = QTreeView()
        self.remote_tree.setObjectName("RemoteTree")
        self.remote_tree.setModel(self.remote_model)
        self.remote_tree.setHeaderHidden(True)
        self.remote_tree.setStyle(CustomTreeCarrot(self.theme_manager))
        self.remote_tree.setItemDelegate(PreviewButtonDelegate(self.remote_tree))
        self.remote_tree.setDragEnabled(True)
        self.remote_tree.setAcceptDrops(True)
        self.remote_tree.setDropIndicatorShown(False)
        self.remote_tree.setDragDropMode(QTreeView.InternalMove)
        self.remote_tree.viewport().installEventFilter(self)
        self.remote_splitter.addWidget(self.remote_tree)

        # Remote results
        self.remote_results = QTreeWidget()
        self.remote_results.setObjectName("ResultsPanel")
        self.remote_results.setHeaderHidden(True)
        self.remote_results.itemClicked.connect(self.navigate_to_remote_result)
        self.remote_results.setVisible(False)
        self.remote_results.setStyle(CustomTreeCarrot(self.theme_manager))
        self.remote_splitter.addWidget(self.remote_results)

        main_splitter.addWidget(remote_panel)
        
        # Style all splitters
        splitter_style = """
            QSplitter::handle {
                margin: 4px;
                background-color: #666;
            }
            QSplitter::handle:hover {
                background-color: #4285F4;
            }
        """
        main_splitter.setStyleSheet(splitter_style)
        self.local_splitter.setStyleSheet(splitter_style)
        self.remote_splitter.setStyleSheet(splitter_style)

        # Progress widget
        layout.addWidget(self.progress_widget)

    def eventFilter(self, source, event):
        if event.type() == QEvent.DragEnter:
            logging.debug("=== Drag Enter Event ===")
            if source == self.local_tree.viewport():
                index = self.local_tree.indexAt(event.pos())
                if index.isValid():
                    item = self.local_model.itemFromIndex(index)
                    logging.debug(f"Drag source path: {item.data(Qt.UserRole)}")
                    self._log_tree_state("Before drag")
            event.accept()
            return True
        elif event.type() == QEvent.Drop:
            logging.debug("=== Drop Event ===")
            self._log_tree_state("Before drop handling")
            result = self.handleDrop(source, event)
            self._log_tree_state("After drop handling")
            return result
        return super().eventFilter(source, event)
    
    def _log_tree_state(self, context):
        """Log the current state of the local file tree"""
        def log_item_state(item, depth=0):
            path = item.data(Qt.UserRole)
            has_placeholder = item.rowCount() == 1 and item.child(0).text() == ""
            # logging.debug(f"{'  ' * depth}Path: {path}")
            # logging.debug(f"{'  ' * depth}  rowCount: {item.rowCount()}")
            # logging.debug(f"{'  ' * depth}  hasPlaceholder: {has_placeholder}")
            
            for row in range(item.rowCount()):
                log_item_state(item.child(row), depth + 1)

        logging.debug(f"=== Tree State {context} ===")
        root = self.local_model.invisibleRootItem()
        for row in range(root.rowCount()):
            log_item_state(root.child(row))

    def handleDrop(self, target, event):
        try:
            if target.objectName() == "qt_scrollarea_viewport":
                target = target.parent()
                logging.info(f"Adjusted target to parent tree: {target.objectName()}")

            source_widget = event.source()
            source_index = source_widget.currentIndex()
            logging.debug(f"Drop event - Source widget type: {type(source_widget).__name__}")
            logging.debug(f"Source index valid: {source_index.isValid()}")
            
            if source_widget == self.local_tree:
                source_item = self.local_model.itemFromIndex(source_index)
                source_path = source_item.data(Qt.UserRole)
                logging.info(f"Local drag source path: {source_path}")
            else:
                source_item = self.remote_model.itemFromIndex(source_index)
                metadata = source_item.data(Qt.UserRole)
                if metadata and isinstance(metadata, dict) and 'ClientFullNameAndPathAsPosix' in metadata:
                    source_path = metadata['ClientFullNameAndPathAsPosix']
                else:
                    path_parts = []
                    current_item = source_item
                    while current_item:
                        path_parts.insert(0, current_item.text())
                        current_item = current_item.parent()
                    source_path = '/'.join(path_parts)
                logging.info(f"Remote drag source path: {source_path}")

            if not source_path:
                logging.error("Invalid source path")
                return False

            if source_widget == self.local_tree and (target == self.remote_tree or target == self.remote_tree.viewport()):
                logging.info(f"Initiating backup operation for: {source_path}")
                settings = self.read_settings()
                if settings:
                    settings['user_email'] = self.user_email
                    settings['settings_path'] = self.settings_path
                    if self.history_manager:
                        operation_id = self.history_manager.start_operation(
                            'backup', InitiationSource.USER, self.user_email
                        )
                        settings['operation_id'] = operation_id
                    self.progress_widget.start_operation('backup', source_path, settings)
                    
                    # After starting backup, completely reset the local tree
                    QTimer.singleShot(100, self.complete_tree_reset)

            elif source_widget == self.remote_tree and (target == self.local_tree or target == self.local_tree.viewport()):
                logging.info(f"Initiating restore operation for: {source_path}")
                settings = self.read_settings()
                if settings:
                    settings['user_email'] = self.user_email
                    settings['settings_path'] = self.settings_path
                    if self.history_manager:
                        operation_id = self.history_manager.start_operation(
                            'restore', InitiationSource.USER, self.user_email
                        )
                        settings['operation_id'] = operation_id

                    # Get main window reference
                    main_window = self.window()
                    if main_window:
                        # Set operation flag before reset
                        main_window.set_operation_in_progress()
                        
                        # Reset tree just once
                        # self.reset_remote_tree()
                        
                        # Start operation
                        self.progress_widget.start_operation('restore', source_path, settings)
                        
                        # Clear flag after delay
                        # QTimer.singleShot(5000, main_window.clear_operation_in_progress)
                        
                        # Only after operation starts, schedule a single tree reset
                        def reset_and_clear():
                            self.reset_remote_tree()
                            main_window.clear_operation_in_progress()
                            
                        QTimer.singleShot(5000, reset_and_clear)

            event.accept()
            return True

        except Exception as e:
            logging.error(f"Error handling drop event: {e}", exc_info=True)
            # Get main window reference for error handling
            main_window = self.window()
            if main_window:
                main_window.clear_operation_in_progress()  # Ensure flag is cleared on error
            return False
        
    def clear_operation_flag(self):
        """Clear the operation in progress flag"""
        self._operation_in_progress = False
        logging.info("Operation flag cleared")

    def reset_remote_tree(self):
        """Reset remote tree by creating a fresh model instance"""
        logging.info(f"=== Starting Remote Tree Reset ===")
        logging.info(f"Old model id: {id(self.remote_model)}")
        
        try:
            # Debug: Check metadata file before reset
            if hasattr(self, 'metadata_dir'):
                metadata_files = sorted(
                    [f for f in os.listdir(self.metadata_dir) 
                     if f.startswith('file_metadata_') and f.endswith('.json')],
                    reverse=True
                )
                if metadata_files:
                    json_path = os.path.join(self.metadata_dir, metadata_files[0])
                    with open(json_path, 'r') as f:
                        data = json.load(f)
                        logging.info(f"Current metadata file: {json_path}")
                        logging.info(f"Number of items in metadata: {len(data)}")
            
            # Explicitly delete old model
            if hasattr(self, 'remote_model'):
                old_model = self.remote_model
                self.remote_tree.setModel(None)
                old_model.deleteLater()
                
            # Force garbage collection
            import gc
            gc.collect()
            
            # Create new model instance
            self.remote_model = RemoteFileSystemModel()
            logging.info(f"New model id: {id(self.remote_model)}")
            
            # Set new model
            self.remote_tree.setModel(self.remote_model)
            
            # Load metadata
            if hasattr(self, 'metadata_dir'):
                self.remote_model.load_data(self.metadata_dir)
                
                # Debug: Check metadata after load
                metadata_files = sorted(
                    [f for f in os.listdir(self.metadata_dir) 
                     if f.startswith('file_metadata_') and f.endswith('.json')],
                    reverse=True
                )
                if metadata_files:
                    json_path = os.path.join(self.metadata_dir, metadata_files[0])
                    with open(json_path, 'r') as f:
                        data = json.load(f)
                        logging.info(f"After load - Number of items in metadata: {len(data)}")
                        logging.info(f"Model root item children count: {self.remote_model.invisibleRootItem().rowCount()}")
                
                logging.info("Remote tree reset complete")
                
        except Exception as e:
            logging.error(f"Error resetting remote tree: {e}", exc_info=True)
        finally:
            logging.info("=== Remote Tree Reset Complete ===")
        
    def complete_tree_reset(self):
        """Completely reset and reinitialize the local file tree"""
        logging.info("Performing complete reset of local file tree")
        try:
            # Create new model instance
            self.local_model = LocalFileSystemModel()
            
            # Disconnect old model and set new one
            self.local_tree.setModel(None)  # Explicitly remove old model
            self.local_tree.setModel(self.local_model)
            
            # Re-establish connections
            self.local_tree.expanded.connect(self.on_item_expanded)
            self.local_tree.clicked.connect(self.on_item_clicked)
            
            # Reset tree view properties
            self.local_tree.setHeaderHidden(True)
            self.local_tree.setIndentation(20)
            self.local_tree.setStyle(self.custom_style)
            self.local_tree.setDragEnabled(True)
            self.local_tree.setAcceptDrops(True)
            self.local_tree.setDropIndicatorShown(False)
            self.local_tree.setDragDropMode(QTreeView.InternalMove)
            
            # Force model to load top-level drives
            self.local_model.load_top_level_dirs()
            
            logging.info("Local file tree reset completed successfully")
            
        except Exception as e:
            logging.error(f"Error during complete tree reset: {e}", exc_info=True)
            # In case of error, try one more time with basic initialization
            try:
                self.local_model = LocalFileSystemModel()
                self.local_tree.setModel(self.local_model)
                self.local_model.load_top_level_dirs()
            except Exception as e2:
                logging.error(f"Fallback initialization also failed: {e2}")

    def reload_local_tree(self):
        """Reload the local file system tree from scratch"""
        logging.info("Reloading local file system tree")
        try:
            # Store the current expanded items and scroll position
            expanded_paths = []
            current_scroll = self.local_tree.verticalScrollBar().value()
            
            def store_expanded_items(parent=QModelIndex()):
                for row in range(self.local_model.rowCount(parent)):
                    idx = self.local_model.index(row, 0, parent)
                    if self.local_tree.isExpanded(idx):
                        item = self.local_model.itemFromIndex(idx)
                        path = item.data(Qt.UserRole)
                        expanded_paths.append(path)
                        store_expanded_items(idx)
            
            # Store currently expanded items
            store_expanded_items()
            
            # Reload the model
            self.local_model = LocalFileSystemModel()
            self.local_tree.setModel(self.local_model)
            
            # Restore expanded state
            def restore_expanded_items(parent=QModelIndex()):
                for row in range(self.local_model.rowCount(parent)):
                    idx = self.local_model.index(row, 0, parent)
                    item = self.local_model.itemFromIndex(idx)
                    path = item.data(Qt.UserRole)
                    if path in expanded_paths:
                        self.local_tree.setExpanded(idx, True)
                        restore_expanded_items(idx)
            
            # Restore expansion state and scroll position
            restore_expanded_items()
            self.local_tree.verticalScrollBar().setValue(current_scroll)
            
            logging.info("Local file system tree reloaded successfully")
            
        except Exception as e:
            logging.error(f"Error reloading local tree: {e}", exc_info=True)

    def check_indexing_status(self):
        """Monitor and update indexing status."""
        status_type, data = self.filesystem_index.get_indexing_status()
        
        if status_type == 'progress':
            pass
            
        elif status_type == 'batch_progress':
            operation = "Adding" if data['operation'] == 'add' else "Removing"
            logging.info(f"{operation} files... {data['processed']:,}/{data['total']:,}")
            
        elif status_type == 'sync_complete':
            message = (
                f"Filesystem sync complete. "
                f"Processed {data['total_items']:,} items "
                f"(Added: {data['added_items']:,}, "
                f"Removed: {data['removed_items']:,})"
            )
            logging.info(message)
            
        elif status_type == 'error':
            error_msg = f"Sync error: {data}"
            logging.error(error_msg)

    def search_local(self):
        search_text = self.local_search.text().strip()
        if not search_text:
            self.local_results.setVisible(False)
            return

        self.local_progress.setVisible(True)
        self.local_progress.setRange(0, 0)  # Indeterminate progress
        
        # Create search worker thread
        self.search_thread = QThread()
        self.search_worker = LocalSearchWorker(search_text, self.filesystem_index)
        self.search_worker.moveToThread(self.search_thread)
        
        # Register the thread
        self.process_registry.register_thread(self.search_thread)
        
        # Connect signals
        self.search_thread.started.connect(self.search_worker.run)
        self.search_worker.finished.connect(self.search_thread.quit)
        self.search_worker.finished.connect(self.search_worker.deleteLater)
        self.search_thread.finished.connect(self.search_thread.deleteLater)
        self.search_worker.results_ready.connect(lambda results, truncated, stats: 
            self.handle_local_search_results(results, truncated, stats))
        
        self.search_thread.start()

    def handle_local_search_results(self, results, truncated, stats):
        search_text = self.local_search.text()
        self.local_progress.setVisible(False)
        self.local_results.setVisible(True)
        
        parent_item = QTreeWidgetItem()
        timestamp = datetime.now().strftime("%H:%M:%S")
        parent_item.setData(0, Qt.UserRole + 1, timestamp)
        
        folders = [r for r in results if r['is_directory']]
        files = [r for r in results if not r['is_directory']]
        
        if results:
            result_text = (f"{stats['matches_found']} matches for '{search_text}' "
                          f"({len(results)} shown) in {stats['total_files']} "
                          f"files searched ({stats['total_folders']} folders)")
            parent_item.setData(0, Qt.UserRole, "found")
        else:
            result_text = (f"0 matches for '{search_text}' in "
                          f"{stats['total_files']} files "
                          f"({stats['total_folders']} folders)")
            parent_item.setData(0, Qt.UserRole, "not_found")
        
        parent_item.setText(0, result_text)
        parent_item.setToolTip(0, f"Search performed at {timestamp}")
        
        if results:
            if folders:
                folder_group = QTreeWidgetItem(parent_item)
                folder_group.setText(0, f"Folders ({len(folders)})")
                for folder in folders:
                    item = QTreeWidgetItem(folder_group)
                    item.setText(0, folder['path'])
                    item.setData(0, Qt.UserRole, "found")
                    item.setToolTip(0, f"Found at {timestamp}")
            
            if files:
                file_group = QTreeWidgetItem(parent_item)
                file_group.setText(0, f"Files ({len(files)})")
                for file in files:
                    item = QTreeWidgetItem(file_group)
                    item.setText(0, file['path'])
                    item.setData(0, Qt.UserRole, "found")
                    item.setToolTip(0, f"Found at {timestamp}")
        
        parent_item.setExpanded(True)
        
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        color = QColor(theme['search_results_found'] if results else theme['search_results_not_found'])
        parent_item.setForeground(0, color)
        
        self.local_results.insertTopLevelItem(0, parent_item)
        
        while self.local_results.topLevelItemCount() > 20:
            self.local_results.takeTopLevelItem(self.local_results.topLevelItemCount() - 1)

    def search_remote(self):
        search_text = self.remote_search.text().strip()
        if not search_text:
            self.remote_results.setVisible(False)
            return

        self.remote_progress.setVisible(True)
        self.remote_progress.setRange(0, 0)
        
        # Create search worker thread
        self.remote_search_thread = QThread()
        self.remote_search_worker = RemoteSearchWorker(search_text, self.remote_model)
        self.remote_search_worker.moveToThread(self.remote_search_thread)
        
        # Connect signals
        self.remote_search_thread.started.connect(self.remote_search_worker.run)
        self.remote_search_worker.finished.connect(self.remote_search_thread.quit)
        self.remote_search_worker.finished.connect(self.remote_search_worker.deleteLater)
        self.remote_search_thread.finished.connect(self.remote_search_thread.deleteLater)
        self.remote_search_worker.results_ready.connect(self.handle_remote_search_results)
        
        self.remote_search_thread.start()

    def handle_remote_search_results(self, results):
        def count_tree_items(root_item):
            """Count total files and folders in the remote tree"""
            file_count = 0
            folder_count = 0
            
            def count_recursive(item):
                nonlocal file_count, folder_count
                for row in range(item.rowCount()):
                    child = item.child(row)
                    if child.hasChildren():
                        folder_count += 1
                        count_recursive(child)
                    else:
                        file_count += 1
                        
            count_recursive(root_item)
            return file_count, folder_count

        def get_full_path(item, file_name):
            """Recursively build full path from tree structure"""
            for row in range(item.rowCount()):
                child = item.child(row)
                child_text = child.text()
                if child_text == os.path.basename(file_name):
                    path_parts = []
                    current = child
                    drive_letter = None
                    
                    # Build path and find drive letter
                    while current:
                        text = current.text()
                        if text.endswith(':'):  # Found drive letter
                            drive_letter = text
                        elif current.parent():  # Skip root item
                            path_parts.insert(0, text)
                        current = current.parent()
                    
                    # If we found a drive letter, use it, otherwise use the first available drive
                    if not drive_letter:
                        for i in range(root_item.rowCount()):
                            drive_text = root_item.child(i).text()
                            if drive_text.endswith(':'):
                                drive_letter = drive_text
                                break
                    
                    if drive_letter:
                        return f"{drive_letter}/" + '/'.join(path_parts)
                    return '/'.join(path_parts)  # Fallback with no drive letter
                    
                elif child.hasChildren():
                    result = get_full_path(child, file_name)
                    if result:
                        return result
            return None

        search_text = self.remote_search.text()
        self.remote_progress.setVisible(False)
        self.remote_results.setVisible(True)
        
        # Create parent item for new search
        parent_item = QTreeWidgetItem()
        timestamp = datetime.now().strftime("%H:%M:%S")
        parent_item.setData(0, Qt.UserRole + 1, timestamp)
        
        # Get total counts from remote tree
        root_item = self.remote_tree.model().invisibleRootItem()
        total_files, total_folders = count_tree_items(root_item)
        
        # Get list of available drives
        drives = []
        for row in range(root_item.rowCount()):
            drive_text = root_item.child(row).text()
            if drive_text.endswith(':'):
                drives.append(drive_text)
        
        # Separate results into files and folders based on file extension
        file_matches = []
        folder_matches = []
        
        for path in results:
            # Get full path
            full_path = get_full_path(root_item, os.path.basename(path))
            if not full_path:
                # Clean up path by removing any drive letters
                clean_path = path
                if ':' in path:
                    # Extract drive letter if present in path
                    drive, remainder = path.split(':', 1)
                    drive = drive.strip().upper() + ':'
                    if drive in drives:
                        full_path = f"{drive}/{remainder.lstrip('/')}"
                    else:
                        # Use first available drive if original drive not found
                        full_path = f"{drives[0]}/{remainder.lstrip('/')}" if drives else path
                else:
                    # Use first available drive if no drive letter in path
                    full_path = f"{drives[0]}/{clean_path}" if drives else path
                
            # Check if it's a file or folder based on extension
            basename = os.path.basename(path)
            if '.' in basename and not basename.endswith('.'):  # Has extension but not just a dot at end
                file_matches.append(full_path)
            else:
                folder_matches.append(full_path)
        
        # Construct result text
        if results:
            result_text = (f"{len(results)} matches for '{search_text}' in {total_files} files searched "
                          f"({total_folders} folders)")
            parent_item.setData(0, Qt.UserRole, "found")
            
            # Add folder matches if any
            if folder_matches:
                folder_group = QTreeWidgetItem(parent_item)
                folder_group.setText(0, f"Folders ({len(folder_matches)})")
                folder_group.setExpanded(True)
                
                for folder_path in sorted(folder_matches):
                    item = QTreeWidgetItem(folder_group)
                    item.setText(0, folder_path)
                    item.setData(0, Qt.UserRole, "found")
                    item.setData(0, Qt.UserRole + 1, folder_path)
                    item.setToolTip(0, folder_path)
            
            # Add file matches if any
            if file_matches:
                file_group = QTreeWidgetItem(parent_item)
                file_group.setText(0, f"Files ({len(file_matches)})")
                file_group.setExpanded(True)
                
                for file_path in sorted(file_matches):
                    item = QTreeWidgetItem(file_group)
                    item.setText(0, file_path)
                    item.setData(0, Qt.UserRole, "found")
                    item.setData(0, Qt.UserRole + 1, file_path)
                    item.setToolTip(0, file_path)
        else:
            result_text = f"No matches for '{search_text}' in {total_files} files ({total_folders} folders)"
            parent_item.setData(0, Qt.UserRole, "not_found")

        parent_item.setText(0, result_text)
        parent_item.setToolTip(0, f"Search performed at {timestamp}")
        parent_item.setExpanded(True)
        
        # Apply color based on result status
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        color = QColor(theme['search_results_found'] if results else theme['search_results_not_found'])
        parent_item.setForeground(0, color)
        
        # Insert at the beginning of the list
        self.remote_results.insertTopLevelItem(0, parent_item)
        
        # Limit history to last 20 searches
        while self.remote_results.topLevelItemCount() > 20:
            self.remote_results.takeTopLevelItem(self.remote_results.topLevelItemCount() - 1)

        # If we have results, adjust column width to content
        if results:
            self.remote_results.resizeColumnToContents(0)
        
    def update_search_progress(self, workers: List[Process]):
        try:
            while True:
                try:
                    progress = self.progress_queue.get_nowait()
                    self.local_results.clear()
                    
                    if progress.is_complete and all(not w.is_alive() for w in workers):
                        self.search_timer.stop()
                        self.search_progress.hide()
                        if progress.files_found > 0:
                            root = QTreeWidgetItem([f"Found {progress.files_found} matches in {progress.folders_searched} folders"])
                            root.setData(0, Qt.UserRole, "found")
                            self.local_results.addTopLevelItem(root)
                        else:
                            self.local_results.addTopLevelItem(QTreeWidgetItem(["No matches found"]))
                        break
                    else:
                        status = f"Searching... ({progress.folders_searched} folders scanned, {progress.files_found} matches)"
                        if progress.current_path:
                            status += f"\nCurrent: {progress.current_path}"
                        self.local_results.addTopLevelItem(QTreeWidgetItem([status]))
                        
                except Empty:
                    break
                    
        except Exception as e:
            logging.error(f"Error updating search progress: {e}")
            self.search_timer.stop()
            self.search_progress.hide()

    def find_matches(self, search_text, model):
        matches = []
        
        def search_recursive(parent):
            for row in range(parent.rowCount()):
                item = parent.child(row)
                if search_text.lower() in item.text().lower():
                    matches.append((item.text(), model.indexFromItem(item)))
                if item.hasChildren():
                    search_recursive(item)

        search_recursive(model.invisibleRootItem())
        return matches

    def show_matches(self, matches, results_widget):
        results_widget.clear()
        root = QTreeWidgetItem([f"Found {len(matches)} matches"])
        root.setData(0, Qt.UserRole, "found")
        
        for name, _ in matches:
            child = QTreeWidgetItem([name])
            root.addChild(child)
        
        results_widget.addTopLevelItem(root)
        root.setExpanded(True)
        results_widget.setVisible(True)

    def navigate_to_local_result(self, item, column):
        if not item.parent() or not item.parent().parent():  # Skip root and category items
            return
            
        path = item.text(0)
        model = self.local_tree.model()
        self.expand_to_path(path, self.local_tree, model)

    def navigate_to_remote_result(self, item, column):
        """Navigate to clicked search result in remote tree"""
        if not item.parent() or not item.parent().parent():  # Skip root and category items
            return

        # Get the full path from the item (column 0 contains the path)
        full_path = item.text(0)
        if not full_path:
            return

        # Split into drive and path components
        if ':' in full_path:
            drive, path = full_path.split(':', 1)
            drive = drive + ':'
            path = path.strip('/')  # Remove leading/trailing slashes
            components = path.split('/')
        else:
            return  # No drive letter found

        # Get root index
        current_index = QModelIndex()
        model = self.remote_tree.model()

        # Find the drive
        drive_index = None
        for row in range(model.rowCount(current_index)):
            child_index = model.index(row, 0, current_index)
            if model.data(child_index, Qt.DisplayRole) == drive:
                drive_index = child_index
                break

        if not drive_index:
            return  # Drive not found

        # Start from drive and navigate through each component
        current_index = drive_index
        self.remote_tree.expand(current_index)

        for component in components:
            found = False
            for row in range(model.rowCount(current_index)):
                child_index = model.index(row, 0, current_index)
                if model.data(child_index, Qt.DisplayRole) == component:
                    current_index = child_index
                    self.remote_tree.expand(current_index)
                    found = True
                    break
            if not found:
                break
        
        # Select the final item (the file/folder itself)
        if current_index.isValid():
            self.remote_tree.setCurrentIndex(current_index)
            self.remote_tree.scrollTo(current_index)
            self.remote_tree.setFocus()
            
            # Ensure the file is selected and visible
            rect = self.remote_tree.visualRect(current_index)
            if not rect.isEmpty():
                self.remote_tree.scrollTo(current_index, QAbstractItemView.EnsureVisible)
            
    def expand_to_path(self, path: str, tree_view: QTreeView, model: QStandardItemModel):
        path_parts = Path(path).parts
        current_index = model.index(0, 0, QModelIndex())
        
        for part in path_parts:
            while current_index.isValid():
                item = model.itemFromIndex(current_index)
                if item.text() == part:
                    tree_view.expand(current_index)
                    tree_view.setCurrentIndex(current_index)
                    tree_view.scrollTo(current_index)
                    current_index = model.index(0, 0, current_index)
                    break
                current_index = current_index.siblingAtRow(current_index.row() + 1)

    def navigate_to_result(self, item, column):
        if item.parent() is None:  # This is a root item (search summary)
            item.setExpanded(not item.isExpanded())
        else:  # This is a child item (actual result)
            full_path = item.text(0)
            for _, index in self.find_partial_matches(full_path)[0]:
                if self.get_full_path(self.model.itemFromIndex(index)) == full_path:
                    self.navigate_to_index(index)
                    break

    def navigate_to_index(self, index, tree_view):
        tree_view.setCurrentIndex(index)
        tree_view.scrollTo(index)
        parent = index.parent()
        while parent.isValid():
            tree_view.expand(parent)
            parent = parent.parent()

    def init_models(self):
        self.local_model = LocalFileSystemModel()
        self.remote_model = RemoteFileSystemModel()

    def load_initial_data(self):
        """Load initial directory data"""
        logging.info("Loading initial data for file explorer")
        try:
            # Load local directory model
            self.local_model.load_directory(QDir.homePath())
            
            # Load remote metadata if available
            if hasattr(self, 'metadata_dir'):
                self.remote_model.load_data(self.metadata_dir)
                
            logging.info("File explorer data load complete")
        except Exception as e:
            logging.error(f"Error loading file explorer data: {e}", exc_info=True)


    def on_item_clicked(self, index):
        item = self.local_model.itemFromIndex(index)
        if item and item.hasChildren():
            self.local_model.fetchMore(index)

    def on_local_item_clicked(self, index):
        item = self.local_model.itemFromIndex(index)
        filepath = item.data(Qt.UserRole)
        if os.path.isdir(filepath):
            self.local_model.load_directory(filepath)

    def on_remote_item_clicked(self, index):
        item = self.remote_model.itemFromIndex(index)
        metadata = item.data(Qt.UserRole)
        if metadata:
            dialog = MetadataDialog(metadata, self)
            dialog.exec_()

    def show_local_context_menu(self, position):
        index = self.local_tree.indexAt(position)
        if not index.isValid():
            return
            
        item = self.local_model.itemFromIndex(index)
        filepath = item.data(Qt.UserRole)
        
        menu = QMenu(self)
        backup_action = menu.addAction("Backup")
        
        action = menu.exec_(self.local_tree.viewport().mapToGlobal(position))
        if action == backup_action:
            self.backup_item(filepath)

    def show_remote_context_menu(self, position):
        index = self.remote_tree.indexAt(position)
        if not index.isValid():
            return
            
        item = self.remote_model.itemFromIndex(index)
        metadata = item.data(Qt.UserRole)
        
        menu = QMenu(self)
        restore_action = menu.addAction("Restore")
        
        if metadata and 'versions' in metadata:
            versions_menu = menu.addMenu("Versions")
            for version in metadata['versions']:
                timestamp = version.get('timestamp', 'Unknown')
                version_action = versions_menu.addAction(f"Restore version from {timestamp}")
                version_action.setData(version)
        
        action = menu.exec_(self.remote_tree.viewport().mapToGlobal(position))
        if action == restore_action:
            self.restore_item(metadata['ClientFullNameAndPathAsPosix'])
        elif action and action.parent() == versions_menu:
            version_data = action.data()
            self.restore_file_version(metadata['ClientFullNameAndPathAsPosix'], version_data)

    def apply_theme(self):
        theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
        self.setStyleSheet(theme["stylesheet"])
        self.results_panel.setItemDelegate(SearchResultDelegate(self.theme_manager))

    def on_theme_changed(self):
        self.apply_theme()

    def on_item_expanded(self, index):
        if index.model() == self.local_model:
            self.local_model.fetchMore(index)

    def show_metadata(self, index):
        """Show metadata dialog for selected remote file"""
        item = self.remote_model.itemFromIndex(index)
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

    def find_exact_match(self, search_text, model):
        def search_recursive(parent):
            for row in range(parent.rowCount()):
                item = parent.child(row)
                if item.text().lower() == search_text.lower():
                    return model.indexFromItem(item)
                if item.hasChildren():
                    result = search_recursive(item)
                    if result.isValid():
                        return result
            return QModelIndex()

        return search_recursive(model.invisibleRootItem())

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
        
        return full_path

    def show_partial_matches(self, search_text, match_data):
        matches, folders_searched, files_searched = match_data
        self.add_to_search_history(search_text, [m[0] for m in matches], folders_searched, files_searched)
        self.update_results_panel()

    def show_context_menu(self, position):
        """Enhanced context menu with file/folder awareness"""
        # First verify we have settings path
        if not hasattr(self, 'settings_path') or not self.settings_path:
            logging.error("Settings path not initialized")
            StormcloudMessageBox.critical(self, "Error", "Settings path not configured")
            return

        # Read settings with proper error handling
        settings = self.read_settings()
        if not settings:
            logging.error("Failed to read settings file")
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
        """Add a file to the remote tree with proper path handling"""
        parts = path.strip('/').split('/')
        parent = self.root
        
        # Build the path one component at a time
        for i, part in enumerate(parts[:-1]):  # Process directory components
            found = None
            for row in range(parent.rowCount()):
                if parent.child(row).text() == part:
                    found = parent.child(row)
                    break
                    
            if not found:
                found = QStandardItem(part)
                found.setIcon(self.get_folder_icon())
                # Store full path up to this point in metadata
                dir_metadata = {
                    'ClientFullNameAndPathAsPosix': '/'.join(parts[:i+1])
                }
                found.setData(dir_metadata, Qt.UserRole)
                parent.appendRow(found)
            parent = found
            
        # Add the file itself
        file_item = QStandardItem(parts[-1])
        file_item.setData(metadata, Qt.UserRole)
        file_item.setIcon(self.get_file_icon(parts[-1]))
        parent.appendRow(file_item)

    def load_data(self):
        self.local_model.load_top_level_dirs()
        if hasattr(self, 'metadata_dir'):
            self.remote_model.load_data(self.metadata_dir)

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
                settings = {}
                current_section = None
                
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                        
                    if ':' in line and not line.startswith(' '):
                        key, value = [x.strip() for x in line.split(':', 1)]
                        if value:
                            settings[key] = value
                        else:
                            current_section = key
                            settings[key] = {}
                    elif current_section and line.startswith('-'):
                        settings[current_section] = settings.get(current_section, [])
                        settings[current_section].append(line.lstrip('- ').strip())
                    
                required_keys = ['API_KEY', 'AGENT_ID']
                if not all(key in settings for key in required_keys):
                    logging.error(f'Missing required settings keys: {[key for key in required_keys if key not in settings]}')
                    return None
                    
                logging.info('Successfully loaded all required settings')
                return settings
                    
        except Exception as e:
            logging.error(f'Error reading settings: {str(e)}')
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
                                                    settings['AGENT_ID']):
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
                                            , settings['AGENT_ID']):
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
            if restore_utils.restore_file(file_path, settings['API_KEY'], settings['AGENT_ID'], version_id):
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

    def start_operation(self, operation_type: str, path: str):
        settings = self.read_settings()
        if not settings:
            return
            
        settings['user_email'] = self.user_email
        
        if self.history_manager:
            try:
                operation_id = self.history_manager.start_operation(
                    operation_type,
                    InitiationSource.USER,
                    self.user_email
                )
                settings['operation_id'] = operation_id
            except ValueError as e:
                logging.error(f"Failed to start operation: {e}")
                StormcloudMessageBox.critical(self, "Error", str(e))
                return
            
        settings['settings_path'] = self.settings_path
        self.progress_widget.start_operation(operation_type, path, settings)

    def closeEvent(self, event):
        """Handle cleanup."""
        try:
            # Filesystem index cleanup is handled by process registry
            if hasattr(self, 'background_op'):
                self.background_op.stop()
        except Exception as e:
            logging.error(f"Error during FileExplorerPanel cleanup: {e}")
        finally:
            super().closeEvent(event)

class FileSystemModel(QStandardItemModel):
    def __init__(self):
        super().__init__()
        self.setHorizontalHeaderLabels(['Backed Up Files'])
        self.root = self.invisibleRootItem()

    def add_file(self, path, metadata):
        """Add a file to the remote tree with proper path handling"""
        parts = path.strip('/').split('/')
        parent = self.root
        
        # Build the path one component at a time
        for i, part in enumerate(parts[:-1]):  # Process directory components
            found = None
            for row in range(parent.rowCount()):
                if parent.child(row).text() == part:
                    found = parent.child(row)
                    break
                    
            if not found:
                found = QStandardItem(part)
                found.setIcon(self.get_folder_icon())
                # Store full path up to this point in metadata
                dir_metadata = {
                    'ClientFullNameAndPathAsPosix': '/'.join(parts[:i+1])
                }
                found.setData(dir_metadata, Qt.UserRole)
                parent.appendRow(found)
            parent = found
            
        # Add the file itself
        file_item = QStandardItem(parts[-1])
        file_item.setData(metadata, Qt.UserRole)
        file_item.setIcon(self.get_file_icon(parts[-1]))
        parent.appendRow(file_item)

    def get_file_icon(self, filename):
        # Implement logic to return appropriate file icon based on file type
        # You can use QIcon.fromTheme() or create custom icons
        return QIcon.fromTheme("text-x-generic")

    def get_folder_icon(self):
        # Return a folder icon
        return QIcon.fromTheme("folder")

class LocalFileSystemModel(QStandardItemModel):
    """Model representing local filesystem for UI display.

    Key Functions:
    - Provides hierarchical view of local drives/folders
    - Handles dynamic loading of directory contents
    - Manages drag-drop operations

    Implementation Details:
    - Qt model/view architecture
    - Asynchronous directory loading
    - Windows API for drive enumeration
    - Permission handling
    - Custom icon management

    Application Integration:
    - Used by FileExplorerPanel
    - Coordinates with filesystem indexing
    - Supports backup operations
    """

    def __init__(self):
        super().__init__()
        self.setHorizontalHeaderLabels(['Local Files'])
        self._is_loading = False
        self.invisibleRootItem().setData("root", Qt.UserRole)
        self._init_icons()
        self._processed_paths = set()
        self._drag_in_progress = False
        self.load_top_level_dirs()

    def _init_icons(self):
        icon_provider = QFileIconProvider()
        self.folder_icon = icon_provider.icon(QFileIconProvider.Folder)
        self.drive_icon = icon_provider.icon(QFileIconProvider.Drive)
        self.file_icon = icon_provider.icon(QFileIconProvider.File)

    def load_top_level_dirs(self):
        """Single method to initialize drive listing"""
        if self._is_loading:
            logging.debug("Skipping load_top_level_dirs - already loading")
            return

        try:
            self._is_loading = True
            logging.debug("Beginning load_top_level_dirs")
            self.beginResetModel()
            self.clear()
            self.setHorizontalHeaderLabels(['Local Files'])
            
            added_drives = set()
            bitmask = win32api.GetLogicalDrives()
            
            for letter in range(65, 91):
                if bitmask & (1 << (letter - 65)):
                    drive = f"{chr(letter)}:\\"
                    if (drive not in added_drives and 
                        win32file.GetDriveType(drive) in (win32file.DRIVE_FIXED, win32file.DRIVE_REMOVABLE)):
                        logging.debug(f"Processing drive {drive}")
                        item = QStandardItem(drive)
                        item.setData(drive, Qt.UserRole)
                        item.setIcon(self.drive_icon)
                        if QDir(drive).isReadable():
                            logging.debug(f"Drive {drive} is readable, adding placeholder")
                            item.appendRow(QStandardItem(""))
                        self.invisibleRootItem().appendRow(item)
                        added_drives.add(drive)
                        logging.debug(f"Added drive {drive} to model")
                QApplication.processEvents()
                
        except Exception as e:
            logging.error(f"Error loading drives: {e}")
        finally:
            logging.debug("Completing load_top_level_dirs")
            self.endResetModel()
            self._is_loading = False

    def init_drives(self):
        QTimer.singleShot(0, self._async_load_drives)

    def itemFlags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def load_data(self):
        if self._is_loading:
            return
            
        self._is_loading = True
        try:
            self.beginResetModel()
            self.clear()
            self.setHorizontalHeaderLabels(['Local Files'])
            
            added_drives = set()  # Track added drives to prevent duplicates
            bitmask = win32api.GetLogicalDrives()
            
            for letter in range(65, 91):
                if bitmask & (1 << (letter - 65)):
                    drive = f"{chr(letter)}:\\"
                    if (drive not in added_drives and 
                        win32file.GetDriveType(drive) in (win32file.DRIVE_FIXED, win32file.DRIVE_REMOVABLE)):
                        item = QStandardItem(drive)
                        item.setData(drive, Qt.UserRole)
                        item.setIcon(self.drive_icon)
                        if QDir(drive).isReadable():
                            item.appendRow(QStandardItem(""))
                        self.invisibleRootItem().appendRow(item)
                        added_drives.add(drive)
                        logging.info(f"Added drive {drive}")
                QApplication.processEvents()
                
        except Exception as e:
            logging.error(f"Error loading drives: {e}")
        finally:
            self.endResetModel()
            self._is_loading = False

    def _async_load_drives(self):
        try:
            self.beginResetModel()
            self.clear()
            self.setHorizontalHeaderLabels(['Local Files'])
            
            added_drives = set()
            bitmask = win32api.GetLogicalDrives()
            
            for letter in range(65, 91):
                if bitmask & (1 << (letter - 65)):
                    drive = f"{chr(letter)}:\\"
                    if (drive not in added_drives and 
                        win32file.GetDriveType(drive) in (win32file.DRIVE_FIXED, win32file.DRIVE_REMOVABLE)):
                        item = QStandardItem(drive)
                        item.setData(drive, Qt.UserRole)
                        item.setIcon(self.drive_icon)
                        if QDir(drive).isReadable():
                            item.appendRow(QStandardItem(""))
                        self.invisibleRootItem().appendRow(item)
                        added_drives.add(drive)
                        logging.info(f"Added drive {drive}")
                QApplication.processEvents()
                
        except Exception as e:
            logging.error(f"Error loading drives: {e}")
        finally:
            self.endResetModel()

    def fetchMore(self, parent):
        if not parent.isValid():
            return

        item = self.itemFromIndex(parent)
        path = item.data(Qt.UserRole)
        
        try:
            if item.rowCount() == 1 and item.child(0).text() == "":
                item.removeRow(0)
            
            dir = QDir(path)
            dir.setFilter(QDir.AllEntries | QDir.Hidden | QDir.NoDotAndDotDot)
            entries = dir.entryInfoList()
            
            batch_size = 50
            for i in range(0, len(entries), batch_size):
                batch = entries[i:i + batch_size]
                for entry in batch:
                    abs_path = entry.absoluteFilePath()
                    if abs_path not in self._processed_paths:
                        self._processed_paths.add(abs_path)
                        child = QStandardItem(entry.fileName())
                        child.setData(abs_path, Qt.UserRole)
                        
                        if entry.isDir():
                            child.setIcon(self.folder_icon)
                            if QDir(abs_path).isReadable():
                                child.appendRow(QStandardItem(""))
                        else:
                            child.setIcon(self.file_icon)
                            
                        item.appendRow(child)
                QApplication.processEvents()
                
        except Exception as e:
            logging.error(f"Error in fetchMore for {path}: {e}")

    def canFetchMore(self, parent):
        if not parent.isValid():
            return False
        item = self.itemFromIndex(parent)
        path = item.data(Qt.UserRole)
        return item.rowCount() == 1 and item.child(0).text() == ""

    def hasChildren(self, parent=QModelIndex()):
        if not parent.isValid():
            return True
        item = self.itemFromIndex(parent)
        path = item.data(Qt.UserRole)
        
        if item.rowCount() == 1:
            readable = QDir(path).exists() and QDir(path).isReadable()
            has_placeholder = item.child(0).text() == ""
            return readable
        
        return item.rowCount() > 0

    def mimeData(self, indexes):
        logging.debug("=== mimeData called ===")
        logging.debug(f"Creating mime data for {len(indexes)} indexes")
        self._log_tree_state("During mimeData creation")
        return super().mimeData(indexes)

    def canDropMimeData(self, data, action, row, column, parent):
        logging.debug("=== canDropMimeData called ===")
        logging.debug(f"Action: {action}, Row: {row}, Column: {column}")
        self._log_tree_state("During canDropMimeData")
        return super().canDropMimeData(data, action, row, column, parent)

    def dropMimeData(self, data, action, row, column, parent):
        self._drag_in_progress = True
        try:
            return super().dropMimeData(data, action, row, column, parent)
        finally:
            self._drag_in_progress = False

    def removeRows(self, row, count, parent=QModelIndex()):
        """Override removeRows to preserve placeholder state"""
        logging.debug(f"=== removeRows called ===")
        logging.debug(f"Row: {row}, Count: {count}")
        
        if not parent.isValid():
            return super().removeRows(row, count, parent)
            
        parent_item = self.itemFromIndex(parent)
        if not parent_item:
            return super().removeRows(row, count, parent)
            
        path = parent_item.data(Qt.UserRole)
        needs_placeholder = False
        
        # Only restore placeholder if this is during drag-drop
        if self._drag_in_progress and QDir(path).exists() and QDir(path).isReadable():
            needs_placeholder = parent_item.rowCount() <= count
            
        result = super().removeRows(row, count, parent)
        
        # Restore placeholder if needed
        if needs_placeholder and parent_item.rowCount() == 0:
            parent_item.appendRow(QStandardItem(""))
            logging.debug(f"Restored placeholder for {path}")
            
        return result

    def _log_tree_state(self, context):
        logging.debug(f"\n=== Tree State: {context} ===")
        root = self.invisibleRootItem()
        for row in range(root.rowCount()):
            item = root.child(row)
            self._log_item_state(item, depth=0, max_depth=1)

    def _log_item_state(self, item, depth=0, max_depth=1):
        path = item.data(Qt.UserRole)
        indent = "  " * depth
        
        if depth < max_depth:
            for row in range(item.rowCount()):
                self._log_item_state(item.child(row), depth + 1, max_depth)
    
    def itemFromIndex(self, index):
        item = super().itemFromIndex(index)
        return item

    def get_drive_icon(self):
        if QIcon.fromTheme("drive-harddisk").isNull():
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setPen(QPen(Qt.darkGray))
            painter.setBrush(QBrush(Qt.lightGray))
            painter.drawRect(2, 2, 12, 12)
            painter.end()
            return QIcon(pixmap)
        return QIcon.fromTheme("drive-harddisk")

    def get_file_icon(self, filename):
        try:
            return QIcon.fromTheme("text-x-generic", QIcon())
        except:
            return QIcon()
        
    def get_folder_icon(self):
        try:
            return QIcon.fromTheme("folder", QIcon())
        except:
            return QIcon()

class RemoteFileSystemModel(QStandardItemModel):
    """Model representing remote backup storage hierarchy.

    Key Functions:
    - Displays backed up files/folders
    - Loads metadata for remote files
    - Manages file version information

    Implementation Details:
    - Qt model/view framework
    - JSON metadata parsing
    - Custom icon system
    - Hierarchical data organization

    Application Integration:
    - Used by FileExplorerPanel
    - Supports restore operations
    - Shows backup status
    """

    def __init__(self):
        super().__init__()
        self.setHorizontalHeaderLabels(['Remote Files'])
        self.root = self.invisibleRootItem()
        self._is_loading = False

    def load_data(self, metadata_dir):
        if self._is_loading:
            return

        try:
            self._is_loading = True
            logging.info("=== Starting metadata load ===")
            self.beginResetModel()
            
            metadata_files = sorted(
                [f for f in os.listdir(metadata_dir) 
                 if f.startswith('file_metadata_') and f.endswith('.json')],
                reverse=True
            )
            
            if not metadata_files:
                logging.info("No metadata files found")
                return

            json_path = os.path.join(metadata_dir, metadata_files[0])
            with open(json_path, 'r') as file:
                data = json.load(file)
                logging.info(f"Loading {len(data)} items from {json_path}")
                
                # Track unique paths
                paths_added = set()
                
                # Create directories first
                directories = set()
                for item in data:
                    path = item['ClientFullNameAndPathAsPosix']
                    if path in paths_added:
                        logging.info(f"Duplicate path detected during load: {path}")
                    paths_added.add(path)
                    
                    parts = path.strip('/').split('/')
                    current = ""
                    for part in parts[:-1]:
                        current = f"{current}/{part}" if current else part
                        directories.add(current)
                
                logging.info(f"=== Metadata load complete: {len(paths_added)} unique paths ===")
                
                for directory in sorted(directories):
                    self._create_directory_path(directory)
                
                # Add files
                for item in data:
                    self._add_file(item['ClientFullNameAndPathAsPosix'], item)
                    
            logging.info(f"Loaded metadata from {json_path}")

        except Exception as e:
            logging.error(f"Error loading metadata: {str(e)}")
        finally:
            self.endResetModel()
            self._is_loading = False

    def _ensure_directory_exists(self, path_parts):
        """Ensure directory structure exists, create if needed"""
        parent = self.root
        current_path = ""
        
        for part in path_parts[:-1]:  # Skip the last part (filename)
            current_path = f"{current_path}/{part}" if current_path else part
            
            # Look for existing directory at this level
            found = None
            for row in range(parent.rowCount()):
                if parent.child(row).text() == part:
                    found = parent.child(row)
                    break
            
            if not found:
                # Create new directory item
                dir_item = QStandardItem(part)
                dir_item.setIcon(QIcon.fromTheme("folder"))
                dir_metadata = {
                    'ClientFullNameAndPathAsPosix': current_path,
                    'is_directory': True
                }
                dir_item.setData(dir_metadata, Qt.UserRole)
                parent.appendRow(dir_item)
                parent = dir_item
            else:
                parent = found
                
        return parent

    def _create_directory_path(self, path):
        parts = path.strip('/').split('/')
        parent = self.root
        
        for part in parts:
            found = None
            for row in range(parent.rowCount()):
                if parent.child(row).text() == part:
                    found = parent.child(row)
                    break
                    
            if not found:
                new_dir = QStandardItem(part)
                new_dir.setIcon(QIcon.fromTheme("folder"))
                parent.appendRow(new_dir)
                parent = new_dir
            else:
                parent = found

    def _add_file(self, path, metadata):
        parts = path.strip('/').split('/')
        parent = self.root
        
        logging.info(f"foobar tarfun: {parts}")
        logging.info(f"foobar tarfun: {parent}")
        logging.info(f"foobar tarfun: {path}")
        logging.info(f"foobar tarfun: {metadata}")
        
        for part in parts[:-1]:
            for row in range(parent.rowCount()):
                if parent.child(row).text() == part:
                    parent = parent.child(row)
                    break
                    
        file_item = QStandardItem(parts[-1])
        file_item.setData(metadata, Qt.UserRole)
        file_item.setIcon(QIcon.fromTheme("text-x-generic"))
        parent.appendRow(file_item)

    def get_file_icon(self, filename):
        try:
            return QIcon.fromTheme("text-x-generic", QIcon())
        except:
            return QIcon()
        
    def get_folder_icon(self):
        try:
            return QIcon.fromTheme("folder", QIcon())
        except:
            return QIcon()

class BackgroundOperation:
    """Manager for background backup/restore operations.

    Key Functions:
    - Handles backup/restore processes
    - Tracks operation progress
    - Manages file processing queues

    Implementation Details:
    - Multiprocessing for operations
    - Queue-based progress updates
    - Windows API integration
    - Error handling system

    Application Integration:
    - Used by FileExplorerPanel
    - Updates HistoryManager
    - Reports to progress widget
    """

    def __init__(self, operation_type, paths, settings):
        self.operation_type = operation_type
        self.paths = paths if isinstance(paths, list) else [paths]
        self.settings = settings.copy()
        self.queue = Queue()
        self.process = None
        self.total_files = 0
        self.processed_files = 0
        self.manager = Manager()
        self.should_stop = self.manager.Value('b', False)
        self.user_email = settings.get('user_email')
        self.auth_tokens = settings.get('auth_tokens')  # Get auth tokens from settings

        self.operation_id = self.settings.get('operation_id') or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.settings['operation_id'] = self.operation_id
        self.start_time = datetime.now()
        self.settings['operation_start_time'] = self.start_time

    def start(self):
        """Start the background operation"""
        if self.operation_type == 'backup':
            self.process = Process(target=BackgroundOperation._backup_worker, 
                                 args=(self.paths, self.settings, self.queue, self.should_stop))
        else:
            self.process = Process(target=BackgroundOperation._restore_worker, 
                                 args=(self.paths, self.settings, self.queue, self.should_stop))
        
                # Ensure process starts safely
        if __name__ == "__main__":
            multiprocessing.freeze_support()
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
                
                # Update file status in history if record_file is True
                if self.operation_id and update.get('record_file', True):
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
        """Worker process with authentication handling"""
        if __name__ == "__main__":
            multiprocessing.freeze_support()
            
        try:
            operation_id = settings['operation_id']
            
            # Initialize authentication context
            backup_utils.initialize_auth_context(
                api_key=settings['API_KEY'],
                agent_id=settings['AGENT_ID'],
                auth_tokens=settings.get('auth_tokens')
            )
            
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
                                dbconn,
                                True
                            )
                            success_count += 1 if success else 0
                            fail_count += 0 if success else 1
                            processed += 1
                            
                            # Use consistent operation_id and ensure record_file is True
                            queue.put({
                                'type': 'file_progress',
                                'filepath': path,
                                'success': success,
                                'total_files': total_files,
                                'processed_files': processed,
                                'operation_id': operation_id,
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
                                'operation_id': operation_id,
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
                                        dbconn,
                                        True
                                    )
                                    success_count += 1 if success else 0
                                    fail_count += 0 if success else 1
                                    processed += 1
                                    
                                    # Ensure record_file is True for directory contents
                                    queue.put({
                                        'type': 'file_progress',
                                        'filepath': normalized_path,
                                        'success': success,
                                        'total_files': total_files,
                                        'processed_files': processed,
                                        'operation_id': operation_id,
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
                                        'operation_id': operation_id,
                                        'record_file': True,
                                        'parent_folder': path
                                    })
                                    
            finally:
                if dbconn:
                    dbconn.close()
            
            # Send final completion status
            if not should_stop.value:
                successful = fail_count == 0 and success_count > 0
                queue.put({
                    'type': 'operation_complete',
                    'success_count': success_count,
                    'fail_count': fail_count,
                    'total': total_files,
                    'operation_id': operation_id,
                    'status': OperationStatus.SUCCESS if successful else OperationStatus.FAILED
                })
            
        except Exception as e:
            logging.error(f"Backup worker failed: {e}")
            # Use consistent operation_id for failure
            queue.put({
                'type': 'operation_failed',
                'error': str(e),
                'operation_id': operation_id
            })

    @staticmethod
    def _restore_worker(paths, settings, queue, should_stop):
        """Worker process for restore operations with enhanced logging"""
        if __name__ == "__main__":
            multiprocessing.freeze_support()
        
        try:
            operation_id = settings['operation_id']
            logging.info(f"Starting restore operation {operation_id} for paths: {paths}")
            
            # Count files that match our restore paths
            total_files = 0
            success_count = 0
            fail_count = 0
            
            metadata_dir = os.path.join(os.getenv('APPDATA'), 'Stormcloud', 'file_explorer', 'manifest')
            metadata_files = sorted([f for f in os.listdir(metadata_dir) 
                                   if f.startswith('file_metadata_') and f.endswith('.json')],
                                  reverse=True)
            
            if not metadata_files:
                raise Exception("No metadata files found")
                
            # Load the most recent metadata file
            json_path = os.path.join(metadata_dir, metadata_files[0])
            with open(json_path, 'r') as f:
                metadata = json.load(f)
            
            restore_files = []
            
            for item in metadata:
                file_path = item['ClientFullNameAndPathAsPosix']
                file_size = item.get('FileSize', 0)  # Get size from metadata
                
                for restore_path in paths:
                    if file_path.startswith(restore_path):
                        restore_files.append((file_path, file_size))
            
                total_files = len(restore_files)
            
            logging.info(f"Found {total_files} backed up files to restore")
            queue.put({'type': 'total_files', 'value': total_files})
            
            processed = 0
            for path, file_size in restore_files:
                if should_stop.value:
                    logging.info("Restore operation cancelled by user")
                    break
                    
                if os.path.isfile(path):
                    try:
                        logging.info(f"Attempting to restore file: {path}")
                        
                        # Use chunked restore for large files
                        if file_size > 300 * 1024 * 1024:  # 300MB
                            success = restore_utils.restore_large_file(
                                path,
                                settings['API_KEY'],
                                settings['AGENT_ID'],
                                lambda p: queue.put({
                                    'type': 'chunk_progress',
                                    'filepath': path,
                                    'progress': p
                                }),
                                should_stop
                            )
                        else:
                            success = restore_utils.restore_file(
                                path,
                                settings['API_KEY'],
                                settings['AGENT_ID']
                            )
                        
                        success_count += 1 if success else 0
                        fail_count += 0 if success else 1
                        processed += 1
                        
                        result_msg = "successfully" if success else "failed to"
                        logging.info(f"{result_msg.capitalize()} restored file: {path}")
                        
                        queue.put({
                            'type': 'file_progress',
                            'filepath': path,
                            'success': success,
                            'total_files': total_files,
                            'processed_files': processed,
                            'operation_id': operation_id,
                            'record_file': True,
                            'parent_folder': os.path.dirname(path),
                            'user_email': settings.get('user_email')
                        })
                        
                    except Exception as e:
                        error_msg = str(e)
                        logging.error(f"Failed to restore file {path}: {error_msg}")
                        fail_count += 1
                        queue.put({
                            'type': 'file_progress',
                            'filepath': path,
                            'success': False,
                            'error': error_msg,
                            'total_files': total_files,
                            'processed_files': processed,
                            'operation_id': operation_id,
                            'record_file': True,
                            'parent_folder': os.path.dirname(path),
                            'user_email': settings.get('user_email')
                        })
                        
                else:  # Directory
                    logging.info(f"Processing directory: {path}")
                    for root, _, files in os.walk(path):
                        if should_stop.value:
                            break
                        for file in files:
                            if should_stop.value:
                                break
                                
                            file_path = os.path.join(root, file)
                            try:
                                normalized_path = file_path.replace('\\', '/')
                                logging.info(f"Attempting to restore file: {normalized_path}")
                                
                                success = restore_utils.restore_file(
                                    normalized_path,
                                    settings['API_KEY'],
                                    settings['AGENT_ID']
                                )
                                success_count += 1 if success else 0
                                fail_count += 0 if success else 1
                                processed += 1
                                
                                result_msg = "successfully" if success else "failed to"
                                logging.info(f"{result_msg.capitalize()} restored file: {normalized_path}")
                                
                                queue.put({
                                    'type': 'file_progress',
                                    'filepath': normalized_path,
                                    'success': success,
                                    'total_files': total_files,
                                    'processed_files': processed,
                                    'operation_id': operation_id,
                                    'record_file': True,
                                    'parent_folder': path,
                                    'user_email': settings.get('user_email')
                                })
                                
                            except Exception as e:
                                error_msg = str(e)
                                logging.error(f"Failed to restore file {file_path}: {error_msg}")
                                fail_count += 1
                                queue.put({
                                    'type': 'file_progress',
                                    'filepath': normalized_path,
                                    'success': False,
                                    'error': error_msg,
                                    'total_files': total_files,
                                    'processed_files': processed,
                                    'operation_id': operation_id,
                                    'record_file': True,
                                    'parent_folder': path,
                                    'user_email': settings.get('user_email')
                                })
            
            # Send final completion status
            if not should_stop.value:
                successful = fail_count == 0 and success_count > 0
                logging.info(f"Restore operation completed. Success: {success_count}, Failed: {fail_count}, Total: {total_files}")
                queue.put({
                    'type': 'operation_complete',
                    'success_count': success_count,
                    'fail_count': fail_count,
                    'total': total_files,
                    'operation_id': operation_id,
                    'status': OperationStatus.SUCCESS if successful else OperationStatus.FAILED,
                    'user_email': settings.get('user_email')
                })
                    
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Restore worker failed: {error_msg}", exc_info=True)
            queue.put({
                'type': 'operation_failed',
                'error': error_msg,
                'operation_id': operation_id,
                'user_email': settings.get('user_email')
            })

class OperationProgressWidget(QWidget):
    """Progress display for file operations.

    Key Functions:
    - Shows operation progress
    - Displays current file status
    - Allows operation cancellation

    Implementation Details:
    - Qt progress interface
    - Theme-aware display
    - Operation status tracking

    Application Integration:
    - Used by FileExplorerPanel
    - Updates operation status
    - Theme system integration
    """

    operation_completed = pyqtSignal(dict)  # Emits final status when complete
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_manager = parent.theme_manager if parent else None
        self.history_manager = None
        self._user_email = None
        self.init_ui()
        self.background_op = None
        self.timer = None

    @property
    def user_email(self) -> Optional[str]:
        return self._user_email

    @user_email.setter
    def user_email(self, email: Optional[str]):
        self._user_email = email

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
        """Start a new operation with non-blocking progress updates"""
        # Store the user email but don't update history manager
        self._user_email = settings.get('user_email')
        
        self.background_op = BackgroundOperation(operation_type, paths, settings)
        self.background_op.start()
        
        if self.history_manager:
            # Remove this line - don't update history_manager's email here
            # self.history_manager.current_user_email = settings.get('user_email')
            pass
        
        self.operation_id = settings.get('operation_id')
        self.operation_label.setText(f"Operation: {operation_type.capitalize()}")
        self.progress_bar.setValue(0)
        self.current_file_label.setText("Preparing...")
        self.setVisible(True)
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_progress)
        self.timer.start(100)

    def update_progress(self):
        """Process progress updates from the background operation with enhanced logging"""
        if not self.background_op:
            return
                
        try:
            # logging.debug("Checking for progress updates...")
            while True:
                try:
                    update = self.background_op.queue.get_nowait()
                    logging.debug(f"Received update: {update.get('type')}")
                    
                    if update['type'] == 'total_files':
                        logging.info(f"Setting total files to process: {update['value']}")
                        self.file_count_label.setText(f"Files: 0/{update['value']}")
                        
                    elif update['type'] == 'file_progress':
                        file_path = update.get('filepath', '')
                        success = update.get('success', False)
                        error_msg = update.get('error')
                        
                        if self.operation_id and update.get('record_file', True):
                            status = OperationStatus.SUCCESS if success else OperationStatus.FAILED
                            logging.info(f"Recording file status - Path: {file_path}, Status: {status}")
                            self.history_manager.add_file_to_operation(
                                self.operation_id,
                                file_path,
                                status,
                                error_msg
                            )
                        
                        # Update progress percentage
                        if update.get('total_files', 0) > 0:
                            total_files = update.get('total_files', 0)
                            processed_files = update.get('processed_files', 0)
                            percentage = (processed_files / total_files) * 100
                            self.progress_bar.setValue(int(percentage))
                            self.file_count_label.setText(f"Files: {processed_files}/{total_files}")
                            logging.info(f"Progress update: {processed_files}/{total_files} files ({percentage:.1f}%)")
                        
                        # Update current file label
                        if 'filepath' in update:
                            file_name = os.path.basename(file_path)
                            self.current_file_label.setText(f"Processing: {file_name}")
                            if error_msg:
                                logging.error(f"Error processing {file_name}: {error_msg}")
                                
                    elif update['type'] == 'operation_complete':
                        logging.info("Operation completed successfully")
                        logging.info(f"Final stats - Success: {update.get('success_count', 0)}, "
                                   f"Failed: {update.get('fail_count', 0)}, "
                                   f"Total: {update.get('total', 0)}")
                                   
                        if self.history_manager:
                            final_status = OperationStatus.SUCCESS if update['fail_count'] == 0 else OperationStatus.FAILED
                            self.history_manager.complete_operation(
                                update.get('operation_id'),
                                final_status
                            )
                        
                        self.operation_completed.emit({
                            'success_count': update.get('success_count', 0),
                            'fail_count': update.get('fail_count', 0),
                            'total': update.get('total', 0),
                            'operation_type': self.background_op.operation_type
                        })
                        self.cleanup()
                        break
                        
                    elif update['type'] == 'operation_failed':
                        logging.error(f"Operation failed: {update.get('error', 'Unknown error')}")
                        if self.history_manager:
                            self.history_manager.complete_operation(
                                update.get('operation_id'),
                                OperationStatus.FAILED,
                                update.get('error')
                            )
                        
                        self.operation_completed.emit({
                            'error': update.get('error', 'Operation failed'),
                            'operation_type': self.background_op.operation_type
                        })
                        self.cleanup()
                        break
                        
                except Empty:
                    break
                        
        except Exception as e:
            logging.error(f"Error updating progress: {e}", exc_info=True)
            self.cleanup()
        
    def cancel_operation(self):
        """Cancel the current operation"""
        if self.background_op:
            operation_type = self.background_op.operation_type
            operation_id = self.background_op.operation_id
            user_email = self.user_email  # Get current user's email
            
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
                        
                        # Update the operation's status with user email
                        self.history_manager.complete_operation(
                            operation_id,
                            final_status,
                            "Operation cancelled by user",
                            user_email  # Pass user email
                        )
                    else:
                        # No files completed, mark as failed
                        self.history_manager.complete_operation(
                            operation_id,
                            OperationStatus.FAILED,
                            "Operation cancelled by user before any files were processed",
                            user_email  # Pass user email
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

class PreviewButtonDelegate(QStyledItemDelegate):
    """Custom delegate for file preview buttons.

    Key Functions:
    - Renders preview buttons
    - Handles preview interactions
    - Manages preview state

    Implementation Details:
    - Custom Qt delegate
    - Preview functionality
    - Theme integration

    Application Integration:
    - Used in file explorer views
    - Manages file previews
    - Theme coordination
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pressed = None
        
    def createEditor(self, parent, option, index):
        return None
        
    def paint(self, painter, option, index):
        # First draw the default item
        super().paint(painter, option, index)
        
        # Debug logging
        metadata = index.data(Qt.UserRole)
        
        if not metadata or not isinstance(metadata, dict):
            return
                
        filepath = metadata.get('ClientFullNameAndPathAsPosix')
        
        if not filepath:
            return
                
        # Log before checking if previewable    
        if not restore_utils.is_previewable_file(filepath):
            return

        # Draw the preview button
        button_rect = self.get_button_rect(option.rect)
        
        if option.state & QStyle.State_MouseOver and self._pressed == index:
            button_color = QColor("#1967d2")  # Darker blue when pressed
        elif option.state & QStyle.State_MouseOver:
            button_color = QColor("#1a73e8")  # Normal blue
        else:
            button_color = QColor("#4285F4")  # Light blue
            
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(button_color)
        painter.drawRoundedRect(button_rect, 3, 3)
        
        # Draw text
        painter.setPen(Qt.white)
        painter.drawText(button_rect, Qt.AlignCenter, "Preview")
        painter.restore()
        
    def editorEvent(self, event, model, option, index):
        if not index.isValid():
            return False
            
        metadata = index.data(Qt.UserRole)
        if not metadata or not isinstance(metadata, dict):
            return False
            
        filepath = metadata.get('ClientFullNameAndPathAsPosix')
        if not filepath or not restore_utils.is_previewable_file(filepath):
            return False
            
        button_rect = self.get_button_rect(option.rect)
        
        if event.type() == QEvent.MouseButtonPress:
            if button_rect.contains(event.pos()):
                self._pressed = index
                return True
                
        elif event.type() == QEvent.MouseButtonRelease:
            if self._pressed == index and button_rect.contains(event.pos()):
                self._pressed = None
                self.preview_file(index)
                return True
            self._pressed = None
            
        return False
        
    def get_button_rect(self, item_rect):
        button_width = 60
        button_height = 24
        return QRect(
            item_rect.right() - button_width - 5,
            item_rect.center().y() - button_height // 2,
            button_width,
            button_height
        )
        
    def preview_file(self, index):
        metadata = index.data(Qt.UserRole)
        filepath = metadata.get('ClientFullNameAndPathAsPosix')  # e.g. "C:/Users/Tyler/Documents/Dark_Age/about_us.txt"
        
        # Extract just the relative portion from the full path
        if ':' in filepath:
            relative_path = filepath.split(':', 1)[1]  # "/Users/Tyler/Documents/Dark_Age/about_us.txt"
        else:
            relative_path = filepath
            
        # Calculate preview path using just the relative portion
        preview_dir = os.path.join(os.getenv('APPDATA'), 'Stormcloud', 'restore_preview')
        preview_path = os.path.join(preview_dir, relative_path.lstrip('/').lstrip('\\'))
        
        # Show progress indicator
        tree_view = self.parent()
        panel = tree_view.window().findChild(FileExplorerPanel)
        if not panel:
            logging.error("Could not find FileExplorerPanel")
            return
        
        if hasattr(tree_view, 'remote_progress'):
            tree_view.remote_progress.setVisible(True)
            tree_view.remote_progress.setRange(0, 0)  # Indeterminate
            
        try:
            settings = panel.read_settings()
            if not settings:
                return
            
            success = restore_utils.restore_file(
                filepath,  # Use original path for restore request
                settings['API_KEY'],
                settings['AGENT_ID'],
                preview_path=preview_path  # Use cleaned preview path for saving
            )
            
            if success:
                if os.path.exists(preview_path):
                    if os.name == 'nt':  # Windows
                        os.startfile(preview_path)
                    else:
                        subprocess.run(['xdg-open', preview_path])
                        
            else:
                logging.error(f"Failed to preview file: {preview_path}")
                
        except Exception as e:
            logging.error(f"Error previewing file: {e}", exc_info=True)
        finally:
            if hasattr(tree_view, 'remote_progress'):
                tree_view.remote_progress.setVisible(False)
# -----------

# Ensure spawn is used for multiprocessing
multiprocessing.set_start_method("spawn", force=True)

def main():
    """Main entry point."""
    
    logging.basicConfig(
        filename='%s_%s.log' % ("sc_app", datetime.now().strftime("%Y-%m-%d")),
        filemode='a',
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.DEBUG,
        force=True
    )

    # Multiprocessing freeze support for Windows
    multiprocessing.freeze_support()

    """Ensure only one instance of the application is running."""
    mutex_name = "Global\\StormcloudAppMutex"
    try:
        logging.debug("Attempting to create single-instance mutex...")
        mutex = win32event.CreateMutex(None, False, mutex_name)
        last_error = win32api.GetLastError()

        if last_error == winerror.ERROR_ALREADY_EXISTS:
            logging.error("Another instance of the application is already running.")
            sys.exit(1)
        else:
            logging.info("No existing instance found. Continuing application startup.")
    except Exception as e:
        logging.exception("Exception occurred while creating mutex:")
        sys.exit(1)

    # Start the application
    app = QApplication(sys.argv)
    window = StormcloudApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()