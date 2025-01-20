import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import unittest
import yaml

from base64 import b64encode
from cryptography.fernet import Fernet
from datetime import datetime, timedelta
from multiprocessing import Queue, Event
from pathlib import Path
from queue import Queue, Empty
from unittest.mock import patch, MagicMock, mock_open

from application_backup_manager import (LoginDialog, StormcloudApp
					, ThemeManager, LocalFileSystemModel
					, RemoteFileSystemModel, BackgroundOperation
					, FileExplorerPanel, OperationProgressWidget
					, FilesystemIndexer, FilesystemIndex)

import backup_utils
import restore_utils

from PyQt5.QtWidgets import (QApplication, QMainWindow
							 , QPushButton, QLabel
							 , QLineEdit, QTreeView
							 , QProgressBar)
from PyQt5.QtGui import (QStandardItem, QColor, QDropEvent)
from PyQt5.QtCore import (Qt, QPoint, QMimeData, QDir)
from PyQt5.QtTest import QTest

# helper classes from application
# -----------------------
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

import restore_utils
import backup_utils
import network_utils

from client_db_utils import get_or_create_hash_db
from stormcloud import save_file_metadata, read_yaml_settings_file

# Imports from application
from application_backup_manager import (InitiationSource, OperationStatus
                                        , FileOperationRecord, FileRecord
                                        , HistoryEvent, Operation
                                        , OperationEvent, SearchProgress
                                        , Transaction)

class QtTestCase(unittest.TestCase):
    """Base class for tests requiring Qt"""
    
    @classmethod
    def setUpClass(cls):
        """Set up Qt application"""
        # Create QApplication if it doesn't exist
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    @classmethod
    def tearDownClass(cls):
        """Clean up Qt application"""
        if hasattr(cls, 'app'):
            cls.app.quit()

class NonQtTestCase(unittest.TestCase):
    """Base class for tests not requiring Qt"""
    pass

class TestResult:
    """Standardized test result structure for dashboard integration"""
    def __init__(self, test_id, component, subcomponent, test_name):
        self.test_id = test_id
        self.component = component
        self.subcomponent = subcomponent
        self.test_name = test_name
        self.start_time = datetime.now()
        self.end_time = None
        self.status = None
        self.error_message = None
        self.stack_trace = None
        
    def complete(self, status, error_message=None, stack_trace=None):
        self.end_time = datetime.now()
        self.status = status
        self.error_message = error_message
        self.stack_trace = stack_trace
        
    def to_dict(self):
        return {
            "test_id": self.test_id,
            "component": self.component,
            "subcomponent": self.subcomponent,
            "test_name": self.test_name,
            "status": self.status,
            "execution_time": self.start_time.isoformat(),
            "duration": (self.end_time - self.start_time).total_seconds() * 1000 if self.end_time else None,
            "error_message": self.error_message,
            "stack_trace": self.stack_trace,
            "environment": {
                "python_version": platform.python_version(),
                "os_version": platform.platform(),
                "dependencies": self.get_dependencies()
            }
        }
        
    @staticmethod
    def get_dependencies():
        """Get versions of key dependencies"""
        return [
            f"PyQt5=={PyQt5.__version__}",
            f"cryptography=={cryptography.__version__}"
        ]

class TestAuthenticationBase(unittest.TestCase):
    """Base class for authentication tests with common setup"""
    
    def setUp(self):
        """Set up test environment with mocked components"""
        # Create temporary test directory
        self.test_dir = os.path.join(os.getcwd(), 'test_data')
        os.makedirs(self.test_dir, exist_ok=True)
        
        # Mock appdata path
        self.mock_appdata = os.path.join(self.test_dir, 'AppData', 'Roaming')
        os.makedirs(self.mock_appdata, exist_ok=True)
        
        # Create mock settings file
        self.mock_settings = {
            'install_path': os.path.join(self.test_dir, 'install'),
            'api_key': 'test_api_key',
            'agent_id': 'test_agent_id'
        }
        os.makedirs(os.path.dirname(os.path.join(self.mock_appdata, 'Stormcloud')), exist_ok=True)
        with open(os.path.join(self.mock_appdata, 'Stormcloud', 'stable_settings.cfg'), 'w') as f:
            json.dump(self.mock_settings, f)
            
        # Mock network utilities
        self.network_patcher = patch('network_utils.authenticate_user')
        self.mock_network = self.network_patcher.start()
        
        # Create test result tracker
        self.test_result = None

    def tearDown(self):
        """Clean up test environment"""
        import shutil
        self.network_patcher.stop()
        shutil.rmtree(self.test_dir)
        
        # Save test result if exists
        if self.test_result:
            # In a real implementation, this would send to a central collector
            print(json.dumps(self.test_result.to_dict(), indent=2))

class TestUserAuthentication(TestAuthenticationBase):
    """Test suite for user authentication functionality"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        
        # Create test directory
        self.test_dir = tempfile.mkdtemp()
        
        # Create mock settings
        self.settings_path = os.path.join(self.test_dir, 'test_settings.cfg')
        with open(self.settings_path, 'w') as f:
            f.write('API_KEY: test_key\n')
            f.write('AGENT_ID: test_agent\n')
            
        # Set up network mock
        self.requests_mock = patch('network_utils.requests').start()
        
        # Create default mock response
        self.default_response = Mock()
        self.default_response.ok = True
        self.default_response.json.return_value = {
            'success': True,
            'data': {
                'access_token': 'test_token',
                'refresh_token': 'test_refresh',
                'user_info': {
                    'email': 'test@example.com',
                    'verified': True
                }
            }
        }
        self.requests_mock.post.return_value = self.default_response
        
        # Initialize test tracking
        self.test_result = None

    def tearDown(self):
        """Clean up test environment"""
        super().tearDown()
        
        # Stop request mocking
        patch.stopall()
        
        # Remove test directory
        try:
            shutil.rmtree(self.test_dir)
        except Exception as e:
            logging.warning(f"Failed to clean up test directory: {e}")

    def test_valid_credentials(self):
        """Test login with valid credentials"""
        self.test_result = TestResult(
            "auth-valid",
            "User Authentication",
            "Valid Login",
            "Valid Credentials Login"
        )
        
        try:
            dialog = LoginDialog(ThemeManager(), self.settings_path)
            
            # Set valid credentials
            dialog.email_input.setText('test@example.com')
            dialog.password_input.setText('valid_password')
            
            # Trigger login
            QTest.mouseClick(dialog.login_button, Qt.LeftButton)
            
            # Verify success
            self.assertTrue(dialog.user_info is not None)
            self.assertEqual(dialog.user_info['email'], 'test@example.com')
            self.assertTrue(dialog.auth_tokens is not None)
            self.assertEqual(dialog.auth_tokens['access_token'], 'test_token')
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_invalid_credentials(self):
        """Test login with invalid credentials"""
        self.test_result = TestResult(
            "auth-invalid",
            "User Authentication",
            "Invalid Credentials",
            "Invalid Credentials Login"
        )
        
        try:
            # Mock invalid credentials response
            self.requests_mock.post.return_value.json.return_value = {
                'success': False,
                'message': 'Invalid credentials'
            }
            
            dialog = LoginDialog(ThemeManager(), self.settings_path)
            
            # Set invalid credentials
            dialog.email_input.setText('test@example.com')
            dialog.password_input.setText('wrong_password')
            
            # Trigger login
            QTest.mouseClick(dialog.login_button, Qt.LeftButton)
            
            # Verify failure
            self.assertTrue(dialog.error_label.isVisible())
            self.assertEqual(dialog.error_label.text(), 'Invalid credentials')
            self.assertFalse(dialog.result())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_empty_credentials(self):
        """Test login attempt with empty credentials"""
        self.test_result = TestResult(
            "auth-empty",
            "User Authentication",
            "Empty Credentials",
            "Empty Credentials Login"
        )
        
        try:
            dialog = LoginDialog(ThemeManager(), self.settings_path)
            
            # Test empty email
            dialog.email_input.setText('')
            dialog.password_input.setText('password')
            QTest.mouseClick(dialog.login_button, Qt.LeftButton)
            
            self.assertTrue(dialog.error_label.isVisible())
            self.assertFalse(dialog.result())
            
            # Test empty password
            dialog.email_input.setText('test@example.com')
            dialog.password_input.setText('')
            QTest.mouseClick(dialog.login_button, Qt.LeftButton)
            
            self.assertTrue(dialog.error_label.isVisible())
            self.assertFalse(dialog.result())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_malformed_credentials(self):
        """Test login with malformed email address"""
        self.test_result = TestResult(
            "auth-malformed",
            "User Authentication",
            "Malformed Email",
            "Malformed Email Login"
        )
        
        try:
            dialog = LoginDialog(ThemeManager(), self.settings_path)
            
            # Test various malformed emails
            malformed_emails = [
                'not_an_email',
                'missing@domain',
                '@missing_user.com',
                'spaces in@email.com'
            ]
            
            for email in malformed_emails:
                dialog.email_input.setText(email)
                dialog.password_input.setText('password')
                QTest.mouseClick(dialog.login_button, Qt.LeftButton)
                
                self.assertTrue(dialog.error_label.isVisible())
                self.assertFalse(dialog.result())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_network_timeout(self):
        """Test handling of network timeout during login"""
        self.test_result = TestResult(
            "auth-timeout",
            "User Authentication",
            "Network Timeout",
            "Login Network Timeout"
        )
        
        try:
            # Mock timeout
            self.requests_mock.post.side_effect = requests.Timeout()
            
            dialog = LoginDialog(ThemeManager(), self.settings_path)
            
            # Set credentials
            dialog.email_input.setText('test@example.com')
            dialog.password_input.setText('password')
            
            # Trigger login
            QTest.mouseClick(dialog.login_button, Qt.LeftButton)
            
            # Verify timeout handling
            self.assertTrue(dialog.error_label.isVisible())
            self.assertIn('timeout', dialog.error_label.text().lower())
            self.assertFalse(dialog.result())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_server_error(self):
        """Test handling of server error during login"""
        self.test_result = TestResult(
            "auth-server-error",
            "User Authentication",
            "Server Error",
            "Login Server Error"
        )
        
        try:
            # Mock server error
            self.requests_mock.post.return_value.ok = False
            self.requests_mock.post.return_value.status_code = 500
            self.requests_mock.post.return_value.json.return_value = {
                'success': False,
                'message': 'Internal server error'
            }
            
            dialog = LoginDialog(ThemeManager(), self.settings_path)
            
            # Set credentials
            dialog.email_input.setText('test@example.com')
            dialog.password_input.setText('password')
            
            # Trigger login
            QTest.mouseClick(dialog.login_button, Qt.LeftButton)
            
            # Verify error handling
            self.assertTrue(dialog.error_label.isVisible())
            self.assertIn('server error', dialog.error_label.text().lower())
            self.assertFalse(dialog.result())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise
	
class TestTokenManagement(TestAuthenticationBase):
    """Test suite for token storage and loading functionality"""

    def setUp(self):
        super().setUp()
        self.mock_auth_data = {
            'user_email': 'test@example.com',
            'auth_tokens': {
                'access_token': 'valid_access_token',
                'refresh_token': 'valid_refresh_token',
                'session_id': 'valid_session_id'
            },
            'timestamp': datetime.now().isoformat()
        }

    def test_token_storage(self):
        """Test secure token storage and encryption"""
        self.test_result = TestResult(
            "token-storage",
            "Authentication",
            "Token Management",
            "Token Storage Security"
        )
        
        try:
            with patch('win32api.GetComputerName', return_value='TEST_MACHINE'):
                with patch('win32api.GetUserName', return_value='123'):
                    login_dialog = LoginDialog(MagicMock(), self.mock_settings['install_path'])
                    
                    # Store tokens
                    login_dialog.auth_tokens = self.mock_auth_data['auth_tokens']
                    login_dialog.user_email = self.mock_auth_data['user_email']
                    login_dialog.save_auth_data()
                    
                    # Verify encryption
                    with open(login_dialog.auth_file, 'rb') as f:
                        stored_data = f.read()
                        self.assertNotIn(b'access_token', stored_data)
                        self.assertNotIn(b'refresh_token', stored_data)
                    
                    # Verify loading
                    loaded_data = login_dialog.load_auth_data()
                    self.assertEqual(
                        loaded_data['auth_tokens'],
                        self.mock_auth_data['auth_tokens']
                    )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_token_expiration(self):
        """Test token expiration check"""
        self.test_result = TestResult(
            "token-expiration",
            "Authentication",
            "Token Management",
            "Token Expiration"
        )
        
        try:
            # Create expired token data
            expired_data = self.mock_auth_data.copy()
            expired_data['timestamp'] = (datetime.now() - timedelta(hours=25)).isoformat()
            
            with patch('win32api.GetComputerName', return_value='TEST_MACHINE'):
                with patch('win32api.GetUserName', return_value='123'):
                    login_dialog = LoginDialog(MagicMock(), self.mock_settings['install_path'])
                    
                    # Save expired data
                    login_dialog.auth_tokens = expired_data['auth_tokens']
                    login_dialog.user_email = expired_data['user_email']
                    login_dialog.save_auth_data()
                    
                    # Verify expired data is not loaded
                    loaded_data = login_dialog.load_auth_data()
                    self.assertIsNone(loaded_data)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise
	
class TestAppInitialization(QtTestCase):
    """Test suite for application initialization"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        
        # Create test directory structure
        self.test_dir = tempfile.mkdtemp()
        self.appdata_path = os.path.join(self.test_dir, 'AppData', 'Roaming')
        self.app_dir = os.path.join(self.appdata_path, 'Stormcloud')
        self.install_dir = os.path.join(self.test_dir, 'install')
        
        # Create required directories
        for d in [self.appdata_path, self.app_dir, self.install_dir]:
            os.makedirs(d, exist_ok=True)
            
        # Create stable settings
        self.create_stable_settings()
        
        # Set up network mock
        self.requests_mock = patch('network_utils.requests').start()
        
        # Mock successful authentication
        self.requests_mock.post.return_value.ok = True
        self.requests_mock.post.return_value.json.return_value = {
            'success': True,
            'data': {
                'access_token': 'test_token',
                'user_info': {'email': 'test@example.com'}
            }
        }
        
        # Mock environment variables
        self.environ_mock = patch.dict('os.environ', {'APPDATA': self.appdata_path})
        self.environ_mock.start()
        
        # Initialize test tracking
        self.test_result = None

    def tearDown(self):
        """Clean up test environment"""
        super().tearDown()
        
        # Stop all mocks
        patch.stopall()
        
        # Remove test directory
        try:
            shutil.rmtree(self.test_dir)
        except Exception as e:
            logging.warning(f"Failed to clean up test directory: {e}")

    def create_stable_settings(self):
        """Create test stable settings file"""
        settings_path = os.path.join(self.app_dir, 'stable_settings.cfg')
        with open(settings_path, 'w') as f:
            json.dump({
                'install_path': self.install_dir,
                'version': '1.0.0'
            }, f)

    def create_settings_file(self, settings):
        """Create test settings.cfg file"""
        settings_path = os.path.join(self.install_dir, 'settings.cfg')
        with open(settings_path, 'w') as f:
            for key, value in settings.items():
                f.write(f"{key}: {value}\n")

    def test_startup_sequence(self):
        """Test complete application startup sequence"""
        self.test_result = TestResult(
            "init-startup",
            "App Initialization",
            "Startup Sequence",
            "Complete Startup Sequence"
        )
        
        try:
            # Create full test environment
            test_settings = {
                'API_KEY': 'test_key',
                'AGENT_ID': 'test_agent',
                'BACKUP_MODE': 'Realtime',
                'BACKUP_PATHS': ['C:/test1', 'D:/test2'],
                'RECURSIVE_BACKUP_PATHS': ['E:/test3']
            }
            self.create_settings_file(test_settings)
            
            # Initialize app
            app = StormcloudApp()
            
            # Verify initialization order
            self.assertTrue(hasattr(app, 'install_path'))  # Paths initialized first
            self.assertTrue(hasattr(app, 'process_registry'))  # Registry initialized early
            self.assertTrue(hasattr(app, 'history_manager'))  # Services initialized
            self.assertTrue(hasattr(app, 'filesystem_index'))  # Index initialized
            
            # Verify UI initialization
            self.assertTrue(hasattr(app, 'theme_manager'))
            self.assertTrue(hasattr(app, 'grid_layout'))
            
            # Verify backup paths loaded
            self.assertEqual(len(app.backup_paths), 2)
            self.assertEqual(len(app.recursive_backup_paths), 1)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_configuration_loading(self):
        """Test configuration file loading"""
        self.test_result = TestResult(
            "init-config",
            "App Initialization",
            "Config Load",
            "Configuration Loading"
        )
        
        try:
            # Create test settings
            test_settings = {
                'API_KEY': 'test_key',
                'AGENT_ID': 'test_agent',
                'BACKUP_MODE': 'Realtime'
            }
            self.create_settings_file(test_settings)
            
            # Initialize app
            app = StormcloudApp()
            
            # Verify settings loaded
            self.assertEqual(app.backup_mode, 'Realtime')
            
            # Test schedule loading
            test_settings['BACKUP_SCHEDULE'] = """
            weekly:
              Monday: ["09:00"]
              Friday: ["15:00"]
            monthly:
              1: ["00:00"]
            """
            self.create_settings_file(test_settings)
            
            app = StormcloudApp()
            self.assertIn('Monday', app.backup_schedule['weekly'])
            self.assertIn('1', app.backup_schedule['monthly'])
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_path_initialization(self):
        """Test initialization of application paths"""
        self.test_result = TestResult(
            "init-paths",
            "App Initialization",
            "Path Init",
            "Path Initialization"
        )
        
        try:
            app = StormcloudApp()
            
            # Verify paths
            self.assertEqual(app.appdata_path, self.appdata_path)
            self.assertEqual(app.app_dir, self.app_dir)
            self.assertEqual(app.install_path, self.install_dir)
            
            # Verify directory creation
            self.assertTrue(os.path.exists(app.db_dir))
            self.assertTrue(os.path.isfile(app.filesystem_db_path))
            self.assertTrue(os.path.isfile(app.history_db_path))
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_database_initialization(self):
        """Test database initialization"""
        self.test_result = TestResult(
            "init-db",
            "App Initialization",
            "DB Init",
            "Database Initialization"
        )
        
        try:
            app = StormcloudApp()
            
            # Verify filesystem database
            with sqlite3.connect(app.filesystem_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='filesystem_index'
                """)
                self.assertIsNotNone(cursor.fetchone())
            
            # Verify history database
            with sqlite3.connect(app.history_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='operations'
                """)
                self.assertIsNotNone(cursor.fetchone())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_service_initialization(self):
        """Test core services initialization"""
        self.test_result = TestResult(
            "init-services",
            "App Initialization",
            "Service Init",
            "Service Initialization"
        )
        
        try:
            app = StormcloudApp()
            
            # Verify core services
            self.assertIsNotNone(app.process_registry)
            self.assertIsNotNone(app.history_manager)
            self.assertIsNotNone(app.theme_manager)
            self.assertIsNotNone(app.filesystem_index)
            
            # Verify theme initialization
            self.assertEqual(app.theme_manager.current_theme, "Dark Age Classic Dark")
            
            # Verify process registry
            self.assertEqual(app.process_registry.active_process_count, 0)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_error_recovery(self):
        """Test error recovery during initialization"""
        self.test_result = TestResult(
            "init-recovery",
            "App Initialization",
            "Error Recovery",
            "Initialization Error Recovery"
        )
        
        try:
            # Test missing stable settings
            os.remove(os.path.join(self.app_dir, 'stable_settings.cfg'))
            with self.assertRaises(SystemExit):
                StormcloudApp()
            
            # Test corrupted settings file
            self.create_stable_settings()
            with open(os.path.join(self.install_dir, 'settings.cfg'), 'w') as f:
                f.write("corrupted: {invalid: json}")
            
            with self.assertRaises(SystemExit):
                StormcloudApp()
            
            # Test missing directories
            shutil.rmtree(self.app_dir)
            app = StormcloudApp()
            self.assertTrue(os.path.exists(app.app_dir))
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise
	
class TestSettingsManagement(QtTestCase):
    """Test suite for settings management functionality"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        
        # Create test directory structure
        self.test_dir = tempfile.mkdtemp()
        self.appdata_path = os.path.join(self.test_dir, 'AppData', 'Roaming')
        self.app_dir = os.path.join(self.appdata_path, 'Stormcloud')
        self.install_dir = os.path.join(self.test_dir, 'install')
        
        # Create required directories
        for d in [self.appdata_path, self.app_dir, self.install_dir]:
            os.makedirs(d, exist_ok=True)
            
        # Set default settings
        self.default_settings = {
            'API_KEY': 'test_key',
            'AGENT_ID': 'test_agent',
            'BACKUP_MODE': 'Realtime',
            'BACKUP_PATHS': [],
            'RECURSIVE_BACKUP_PATHS': []
        }
        
        # Mock environment variables
        self.environ_mock = patch.dict('os.environ', {'APPDATA': self.appdata_path})
        self.environ_mock.start()
        
        # Initialize test tracking
        self.test_result = None


    def tearDown(self):
        """Clean up test environment"""
        super().tearDown()
        patch.stopall()
        
        try:
            shutil.rmtree(self.test_dir)
        except Exception as e:
            logging.warning(f"Failed to clean up test directory: {e}")

    def create_settings_file(self, settings, version='1.0.0'):
        """Create settings files with specified version"""
        # Create stable settings
        stable_settings = {
            'install_path': self.install_dir,
            'version': version
        }
        with open(os.path.join(self.app_dir, 'stable_settings.cfg'), 'w') as f:
            json.dump(stable_settings, f)
            
        # Create main settings
        settings_path = os.path.join(self.install_dir, 'settings.cfg')
        with open(settings_path, 'w') as f:
            yaml.dump(settings, f)
        
        return settings_path

    def test_settings_parsing(self):
        """Test settings file parsing"""
        self.test_result = TestResult(
            "settings-parse",
            "Settings Management",
            "Parsing",
            "Settings Parsing"
        )
        
        try:
            # Create test settings
            test_settings = self.default_settings.copy()
            test_settings.update({
                'BACKUP_SCHEDULE': {
                    'weekly': {'Monday': ['09:00']},
                    'monthly': {'1': ['00:00']}
                }
            })
            
            settings_path = self.create_settings_file(test_settings)
            
            # Parse settings
            settings = read_yaml_settings_file(settings_path)
            
            # Verify parsing
            self.assertEqual(settings['API_KEY'], 'test_key')
            self.assertEqual(settings['BACKUP_MODE'], 'Realtime')
            self.assertIn('weekly', settings['BACKUP_SCHEDULE'])
            self.assertIn('Monday', settings['BACKUP_SCHEDULE']['weekly'])
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_settings_validation(self):
        """Test validation of settings"""
        self.test_result = TestResult(
            "settings-validate",
            "Settings Management",
            "Validation",
            "Settings Validation"
        )
        
        try:
            # Test missing required fields
            invalid_settings = self.default_settings.copy()
            del invalid_settings['API_KEY']
            settings_path = self.create_settings_file(invalid_settings)
            
            with self.assertRaises(ValueError):
                read_yaml_settings_file(settings_path)
                
            # Test invalid backup mode
            invalid_settings = self.default_settings.copy()
            invalid_settings['BACKUP_MODE'] = 'Invalid'
            settings_path = self.create_settings_file(invalid_settings)
            
            with self.assertRaises(ValueError):
                read_yaml_settings_file(settings_path)
                
            # Test invalid schedule format
            invalid_settings = self.default_settings.copy()
            invalid_settings['BACKUP_SCHEDULE'] = {'invalid': 'format'}
            settings_path = self.create_settings_file(invalid_settings)
            
            with self.assertRaises(ValueError):
                read_yaml_settings_file(settings_path)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_settings_persistence(self):
        """Test settings persistence to file"""
        self.test_result = TestResult(
            "settings-persist",
            "Settings Management",
            "Persistence",
            "Settings Persistence"
        )
        
        try:
            # Create initial settings
            initial_settings = self.default_settings.copy()
            settings_path = self.create_settings_file(initial_settings)
            
            # Modify settings
            app = StormcloudApp()
            app.backup_mode = 'Scheduled'
            app.save_backup_mode()
            
            # Verify persistence
            reloaded_settings = read_yaml_settings_file(settings_path)
            self.assertEqual(reloaded_settings['BACKUP_MODE'], 'Scheduled')
            
            # Test atomic writes
            for i in range(10):  # Simulate concurrent writes
                app.backup_mode = f'Mode{i}'
                app.save_backup_mode()
                
            final_settings = read_yaml_settings_file(settings_path)
            self.assertEqual(final_settings['BACKUP_MODE'], 'Mode9')
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_settings_update(self):
        """Test updating individual settings"""
        self.test_result = TestResult(
            "settings-update",
            "Settings Management",
            "Updates",
            "Settings Updates"
        )
        
        try:
            # Create initial settings
            settings_path = self.create_settings_file(self.default_settings)
            app = StormcloudApp()
            
            # Test backup mode update
            app.backup_mode = 'Scheduled'
            app.save_backup_settings()
            
            # Test schedule update
            app.backup_schedule = {
                'weekly': {'Monday': ['09:00']},
                'monthly': {}
            }
            app.save_backup_settings()
            
            # Test path update
            app.backup_paths = ['C:/test1']
            app.recursive_backup_paths = ['D:/test2']
            app.update_settings_file()
            
            # Verify all updates
            settings = read_yaml_settings_file(settings_path)
            self.assertEqual(settings['BACKUP_MODE'], 'Scheduled')
            self.assertIn('Monday', settings['BACKUP_SCHEDULE']['weekly'])
            self.assertIn('C:/test1', settings['BACKUP_PATHS'])
            self.assertIn('D:/test2', settings['RECURSIVE_BACKUP_PATHS'])
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_invalid_settings(self):
        """Test handling of invalid settings file"""
        self.test_result = TestResult(
            "settings-invalid",
            "Settings Management",
            "Invalid Settings",
            "Invalid Settings Handling"
        )
        
        try:
            # Test corrupted YAML
            with open(os.path.join(self.install_dir, 'settings.cfg'), 'w') as f:
                f.write("invalid: {yaml: syntax")
            
            with self.assertRaises(ValueError):
                read_yaml_settings_file(self.install_dir)
            
            # Test missing file
            os.remove(os.path.join(self.install_dir, 'settings.cfg'))
            with self.assertRaises(FileNotFoundError):
                read_yaml_settings_file(self.install_dir)
            
            # Test empty file
            with open(os.path.join(self.install_dir, 'settings.cfg'), 'w') as f:
                f.write("")
            
            with self.assertRaises(ValueError):
                read_yaml_settings_file(self.install_dir)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_settings_migration(self):
        """Test settings file migration"""
        self.test_result = TestResult(
            "settings-migrate",
            "Settings Management",
            "Migration",
            "Settings Migration"
        )
        
        try:
            # Create old version settings
            old_settings = {
                'API_KEY': 'test_key',
                'AGENT_ID': 'test_agent',
                'backup_mode': 'Realtime',  # Old format
                'paths': ['C:/test']  # Old format
            }
            settings_path = self.create_settings_file(old_settings, version='0.9.0')
            
            # Load and migrate
            app = StormcloudApp()
            
            # Verify migration
            settings = read_yaml_settings_file(settings_path)
            self.assertEqual(settings['BACKUP_MODE'], 'Realtime')
            self.assertIn('C:/test', settings['BACKUP_PATHS'])
            self.assertNotIn('paths', settings)
            self.assertNotIn('backup_mode', settings)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise
	
class TestThemeSystem(QtTestCase):
    """Test suite for theme management system"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        
        # Create test directory structure
        self.test_dir = tempfile.mkdtemp()
        self.appdata_path = os.path.join(self.test_dir, 'AppData', 'Roaming')
        self.app_dir = os.path.join(self.appdata_path, 'Stormcloud')
        self.themes_dir = os.path.join(self.app_dir, 'themes')
        
        # Create directories
        os.makedirs(self.themes_dir, exist_ok=True)
        
        # Initialize theme manager
        self.theme_manager = ThemeManager()
        
        # Set test theme data
        self.test_theme = {
            "app_background": "#202124",
            "panel_background": "#333333",
            "text_primary": "#e8eaed",
            "accent_color": "#4285F4",
            "stylesheet": """
                QWidget {
                    background-color: #202124;
                    color: #e8eaed;
                }
            """
        }
        
        # Initialize test tracking
        self.test_result = None

    def tearDown(self):
        """Clean up test environment"""
        super().tearDown()
        try:
            shutil.rmtree(self.test_dir)
        except Exception as e:
            logging.warning(f"Failed to clean up test directory: {e}")
            
    def create_theme_file(self, theme_name, theme_data):
        """Create a theme file"""
        theme_path = os.path.join(self.themes_dir, f"{theme_name}.json")
        with open(theme_path, 'w') as f:
            json.dump(theme_data, f, indent=2)
        return theme_path

    def test_theme_loading(self):
        """Test loading of theme definitions"""
        self.test_result = TestResult(
            "theme-load",
            "Core Application",
            "Theme System",
            "Theme Loading"
        )
        
        try:
            dark_theme = self.theme_manager.get_theme("Dark Age Classic Dark")
            light_theme = self.theme_manager.get_theme("Light")
            
            # Verify theme structure
            self.assertIn("app_background", dark_theme)
            self.assertIn("panel_background", dark_theme)
            self.assertIn("text_primary", dark_theme)
            self.assertIn("accent_color", dark_theme)
            
            # Verify specific color values
            self.assertEqual(dark_theme["app_background"], "#202124")
            self.assertEqual(light_theme["app_background"], "#f8f9fa")
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_theme_update(self):
        """Test theme update mechanism"""
        self.test_result = TestResult(
            "theme-update",
            "Theme System",
            "Theme Update",
            "Theme Update Mechanism"
        )
        
        try:
            # Create test app
            app = StormcloudApp()
            
            # Create test widgets
            widgets = [QWidget() for _ in range(3)]
            for i, widget in enumerate(widgets):
                widget.setObjectName(f"TestWidget{i}")
                widget.show()  # Must show for style updates to apply
            
            # Register widgets for theme updates
            for widget in widgets:
                app.theme_manager.register_widget(widget)
            
            # Update theme
            new_theme = self.test_theme.copy()
            new_theme['app_background'] = '#111111'
            app.theme_manager.themes['TestTheme'] = new_theme
            app.theme_manager.set_theme('TestTheme')
            
            # Verify all widgets updated
            for widget in widgets:
                self.assertIn('#111111', widget.styleSheet())
            
            # Test dynamic updates
            new_theme['app_background'] = '#222222'
            app.theme_manager.themes['TestTheme'] = new_theme
            app.theme_manager.update_widgets()
            
            for widget in widgets:
                self.assertIn('#222222', widget.styleSheet())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_theme_validation(self):
        """Test theme validation"""
        self.test_result = TestResult(
            "theme-validate",
            "Theme System",
            "Theme Validation",
            "Theme Validation"
        )
        
        try:
            # Test missing required fields
            invalid_theme = self.test_theme.copy()
            del invalid_theme['stylesheet']
            
            with self.assertRaises(ValueError):
                self.theme_manager.validate_theme(invalid_theme)
            
            # Test invalid color format
            invalid_theme = self.test_theme.copy()
            invalid_theme['app_background'] = 'not-a-color'
            
            with self.assertRaises(ValueError):
                self.theme_manager.validate_theme(invalid_theme)
            
            # Test invalid stylesheet
            invalid_theme = self.test_theme.copy()
            invalid_theme['stylesheet'] = 'Invalid { css:'
            
            with self.assertRaises(ValueError):
                self.theme_manager.validate_theme(invalid_theme)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_theme_switching(self):
        """Test theme switching functionality"""
        self.test_result = TestResult(
            "theme-switch",
            "Theme System",
            "Theme Switching",
            "Theme Switching Functionality"
        )
        
        try:
            # Create test app
            app = StormcloudApp()
            initial_theme = app.theme_manager.current_theme
            
            # Create test widget
            test_widget = QWidget()
            test_widget.setObjectName("TestWidget")
            
            # Switch theme
            app.change_theme("Light")
            
            # Verify theme change
            self.assertEqual(app.theme_manager.current_theme, "Light")
            self.assertNotEqual(
                app.theme_manager.get_theme("Light"), 
                app.theme_manager.get_theme(initial_theme)
            )
            
            # Verify widget update
            widget_style = test_widget.styleSheet()
            current_theme = app.theme_manager.get_theme("Light")
            self.assertIn(current_theme["app_background"], widget_style)
            
            # Test theme-specific elements
            elements = [
                app.window().findChild(QTreeView),
                app.window().findChild(QListWidget),
                app.window().findChild(QLabel)
            ]
            
            for element in elements:
                if element:
                    style = element.styleSheet()
                    self.assertIn(current_theme["text_primary"], style)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_theme_persistence(self):
        """Test theme persistence across sessions"""
        self.test_result = TestResult(
            "theme-persist",
            "Theme System",
            "Theme Persistence",
            "Theme Persistence Across Sessions"
        )
        
        try:
            # Create theme storage file
            theme_storage = os.path.join(self.app_dir, 'theme_settings.json')
            
            # Create first session
            app1 = StormcloudApp()
            app1.theme_manager.set_theme("Light")
            
            # Save theme settings
            with open(theme_storage, 'w') as f:
                json.dump({
                    'current_theme': app1.theme_manager.current_theme,
                    'custom_themes': {}
                }, f)
            
            # Create second session
            app2 = StormcloudApp()
            
            # Verify theme persistence
            self.assertEqual(app2.theme_manager.current_theme, "Light")
            
            # Test custom theme persistence
            custom_theme = self.test_theme.copy()
            custom_theme['name'] = 'CustomTest'
            
            app2.theme_manager.themes['CustomTest'] = custom_theme
            app2.theme_manager.set_theme('CustomTest')
            
            # Save again
            with open(theme_storage, 'w') as f:
                json.dump({
                    'current_theme': app2.theme_manager.current_theme,
                    'custom_themes': {'CustomTest': custom_theme}
                }, f)
            
            # Create third session
            app3 = StormcloudApp()
            
            # Verify custom theme persistence
            self.assertEqual(app3.theme_manager.current_theme, 'CustomTest')
            self.assertIn('CustomTest', app3.theme_manager.themes)
            self.assertEqual(
                app3.theme_manager.get_theme('CustomTest')['app_background'],
                custom_theme['app_background']
            )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_custom_theme_handling(self):
        """Test handling of custom themes"""
        self.test_result = TestResult(
            "theme-custom",
            "Core Application",
            "Theme System",
            "Custom Theme Handling"
        )
        
        try:
            custom_theme = {
                "app_background": "#000000",
                "panel_background": "#111111",
                "text_primary": "#FFFFFF",
                "accent_color": "#FF0000"
            }
            
            with patch.dict(self.theme_manager.themes, {"Custom": custom_theme}):
                theme = self.theme_manager.get_theme("Custom")
                self.assertEqual(theme["app_background"], "#000000")
                self.assertEqual(theme["accent_color"], "#FF0000")
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_theme_fallback(self):
        """Test theme fallback mechanism"""
        self.test_result = TestResult(
            "theme-fallback",
            "Core Application",
            "Theme System",
            "Theme Fallback"
        )
        
        try:
            # Request non-existent theme
            theme = self.theme_manager.get_theme("NonExistentTheme")
            
            # Should fall back to dark theme
            self.assertEqual(
                theme["app_background"],
                self.theme_manager.get_theme("Dark Age Classic Dark")["app_background"]
            )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise
	
class TestLocalFileSystem(QtTestCase):
    """Test suite for local file system operations"""

    def setUp(self):
        self.test_dir = Path(os.getcwd()) / 'test_data' / 'local_fs'
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        # Create test file structure
        (self.test_dir / 'folder1').mkdir()
        (self.test_dir / 'folder1' / 'file1.txt').write_text('test content')
        (self.test_dir / 'folder1' / 'subfolder').mkdir()
        (self.test_dir / 'folder2').mkdir()
        (self.test_dir / 'folder2' / 'file2.txt').write_text('test content')
        (self.test_dir / 'test.txt').write_text('root file')

        self.model = LocalFileSystemModel()

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_directory_enumeration(self):
        """Test directory content enumeration"""
        self.test_result = TestResult(
            "dir-enum",
            "File System",
            "Local File System",
            "Directory Enumeration"
        )
        
        try:
            self.model.load_directory(str(self.test_dir))
            root_item = self.model.invisibleRootItem()
            
            # Verify structure
            self.assertEqual(root_item.rowCount(), 3)  # 2 folders + 1 file
            
            # Verify folders
            folder_names = set()
            for row in range(root_item.rowCount()):
                item = root_item.child(row)
                if item.hasChildren():
                    folder_names.add(item.text())
            
            self.assertIn('folder1', folder_names)
            self.assertIn('folder2', folder_names)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_file_metadata(self):
        """Test file metadata reading"""
        self.test_result = TestResult(
            "file-metadata",
            "File System",
            "Local File System",
            "File Metadata Reading"
        )
        
        try:
            file_path = self.test_dir / 'folder1' / 'file1.txt'
            self.model.load_directory(str(file_path.parent))
            root_item = self.model.invisibleRootItem()
            
            # Find file item
            file_item = None
            for row in range(root_item.rowCount()):
                item = root_item.child(row)
                if item.text() == 'file1.txt':
                    file_item = item
                    break
            
            self.assertIsNotNone(file_item)
            self.assertEqual(file_item.data(Qt.UserRole), str(file_path))
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_permission_handling(self):
        """Test handling of file system permissions"""
        self.test_result = TestResult(
            "permission-handle",
            "File System",
            "Local File System",
            "Permission Handling"
        )
        
        try:
            restricted_dir = self.test_dir / 'restricted'
            restricted_dir.mkdir()
            
            # Make directory unreadable
            os.chmod(restricted_dir, 0o000)
            
            try:
                self.model.load_directory(str(restricted_dir))
                # Should handle permission error gracefully
                root_item = self.model.invisibleRootItem()
                self.assertEqual(root_item.rowCount(), 0)
                
            finally:
                # Restore permissions for cleanup
                os.chmod(restricted_dir, 0o755)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_path_normalization(self):
        """Test path normalization handling"""
        self.test_result = TestResult(
            "path-norm",
            "File System",
            "Local File System",
            "Path Normalization"
        )
        
        try:
            # Test various path formats
            paths = [
                str(self.test_dir / 'folder1'),
                str(self.test_dir / 'folder1/'),
                str(self.test_dir / 'folder1\\'),
                str(self.test_dir / 'folder1').replace('/', '\\'),
            ]
            
            normalized_paths = set()
            for path in paths:
                self.model.load_directory(path)
                root_item = self.model.invisibleRootItem()
                if root_item.rowCount() > 0:
                    item = root_item.child(0)
                    normalized_paths.add(item.data(Qt.UserRole))
            
            # All paths should normalize to same format
            self.assertEqual(len(normalized_paths), 1)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_special_characters(self):
        """Test handling of special characters in paths"""
        self.test_result = TestResult(
            "special-chars",
            "File System",
            "Local File System",
            "Special Character Handling"
        )
        
        try:
            special_names = [
                'test space.txt',
                'test#hash.txt',
                'test&amp.txt',
                'test[bracket].txt',
                'test$dollar.txt'
            ]
            
            # Create test files
            for name in special_names:
                (self.test_dir / name).write_text('test')
            
            self.model.load_directory(str(self.test_dir))
            root_item = self.model.invisibleRootItem()
            
            # Verify all files loaded
            found_names = set()
            for row in range(root_item.rowCount()):
                item = root_item.child(row)
                found_names.add(item.text())
            
            for name in special_names:
                self.assertIn(name, found_names)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_long_paths(self):
        """Test handling of long file paths"""
        self.test_result = TestResult(
            "long-paths",
            "File System",
            "Local File System",
            "Long Path Handling"
        )
        
        try:
            # Create deeply nested structure
            current_dir = self.test_dir
            nested_dirs = []
            
            # Create path exceeding 260 characters (Windows MAX_PATH)
            while len(str(current_dir)) < 270:
                current_dir = current_dir / 'nested_folder'
                nested_dirs.append(current_dir)
                current_dir.mkdir(exist_ok=True)
            
            # Add test file at deepest level
            test_file = current_dir / 'test.txt'
            test_file.write_text('test')
            
            # Test loading each level
            for dir_path in nested_dirs:
                self.model.load_directory(str(dir_path))
                root_item = self.model.invisibleRootItem()
                self.assertTrue(root_item.rowCount() > 0)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise
	
class TestRemoteFileSystem(QtTestCase):
    """Test suite for remote file system operations"""

    def setUp(self):
        self.test_dir = os.path.join(os.getcwd(), 'test_data', 'remote_fs')
        os.makedirs(self.test_dir, exist_ok=True)
        
        # Sample metadata
        self.test_metadata = [
            {
                'ClientFullNameAndPathAsPosix': '/folder1/file1.txt',
                'FileSize': 1024,
                'LastModified': '2025-01-01T10:00:00Z',
                'versions': [
                    {'version_id': 'v1', 'timestamp': '2025-01-01T10:00:00Z'},
                    {'version_id': 'v2', 'timestamp': '2025-01-01T11:00:00Z'}
                ]
            },
            {
                'ClientFullNameAndPathAsPosix': '/folder1/subfolder/file2.txt',
                'FileSize': 2048,
                'LastModified': '2025-01-01T12:00:00Z',
                'versions': [
                    {'version_id': 'v1', 'timestamp': '2025-01-01T12:00:00Z'}
                ]
            }
        ]
        
        # Create test metadata file
        self.metadata_path = os.path.join(self.test_dir, 'file_metadata_20250101_100000.json')
        with open(self.metadata_path, 'w') as f:
            json.dump(self.test_metadata, f)
            
        self.model = RemoteFileSystemModel()

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_remote_listing(self):
        """Test remote file listing functionality"""
        self.test_result = TestResult(
            "remote-list",
            "File System",
            "Remote File System",
            "Remote File Listing"
        )
        
        try:
            self.model.load_data(self.test_dir)
            root = self.model.invisibleRootItem()
            
            # Verify folder structure
            folder1 = None
            for row in range(root.rowCount()):
                item = root.child(row)
                if item.text() == 'folder1':
                    folder1 = item
                    break
                    
            self.assertIsNotNone(folder1)
            self.assertTrue(folder1.hasChildren())
            
            # Verify subfolder
            subfolder = None
            for row in range(folder1.rowCount()):
                item = folder1.child(row)
                if item.text() == 'subfolder':
                    subfolder = item
                    break
                    
            self.assertIsNotNone(subfolder)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_remote_metadata(self):
        """Test remote file metadata handling"""
        self.test_result = TestResult(
            "remote-metadata",
            "File System",
            "Remote File System",
            "Remote File Metadata"
        )
        
        try:
            self.model.load_data(self.test_dir)
            root = self.model.invisibleRootItem()
            
            # Find test file
            file_item = self._find_item_by_path(root, '/folder1/file1.txt')
            self.assertIsNotNone(file_item)
            
            # Verify metadata
            metadata = file_item.data(Qt.UserRole)
            self.assertEqual(metadata['FileSize'], 1024)
            self.assertEqual(len(metadata['versions']), 2)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_remote_path_handling(self):
        """Test remote path handling"""
        self.test_result = TestResult(
            "remote-paths",
            "File System",
            "Remote File System",
            "Remote Path Handling"
        )
        
        try:
            # Test different path formats
            test_paths = [
                '/folder1/file1.txt',
                'folder1/file1.txt',
                'folder1\\file1.txt',
                '\\folder1\\file1.txt'
            ]
            
            for path in test_paths:
                self.test_metadata[0]['ClientFullNameAndPathAsPosix'] = path
                
                with open(self.metadata_path, 'w') as f:
                    json.dump(self.test_metadata, f)
                    
                self.model.load_data(self.test_dir)
                root = self.model.invisibleRootItem()
                
                # Should normalize and find the file
                file_item = self._find_item_by_path(root, '/folder1/file1.txt')
                self.assertIsNotNone(file_item)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_remote_permissions(self):
        """Test remote file permissions verification"""
        self.test_result = TestResult(
            "remote-perms",
            "File System",
            "Remote File System",
            "Remote Permission Verification"
        )
        
        try:
            # Add permission metadata
            self.test_metadata[0]['Permissions'] = {
                'read': True,
                'write': False,
                'delete': False
            }
            
            with open(self.metadata_path, 'w') as f:
                json.dump(self.test_metadata, f)
                
            self.model.load_data(self.test_dir)
            root = self.model.invisibleRootItem()
            
            file_item = self._find_item_by_path(root, '/folder1/file1.txt')
            self.assertIsNotNone(file_item)
            
            metadata = file_item.data(Qt.UserRole)
            self.assertTrue(metadata['Permissions']['read'])
            self.assertFalse(metadata['Permissions']['write'])
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_connection_handling(self):
        """Test remote connection error handling"""
        self.test_result = TestResult(
            "remote-connection",
            "File System",
            "Remote File System",
            "Connection Handling"
        )
        
        try:
            # Simulate connection error
            with patch('builtins.open', side_effect=ConnectionError("Network error")):
                self.model.load_data(self.test_dir)
                root = self.model.invisibleRootItem()
                
                # Should handle error gracefully
                self.assertEqual(root.rowCount(), 0)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_timeout_handling(self):
        """Test remote operation timeout handling"""
        self.test_result = TestResult(
            "remote-timeout",
            "File System",
            "Remote File System",
            "Timeout Handling"
        )
        
        try:
            # Simulate timeout
            with patch('builtins.open', side_effect=TimeoutError("Operation timed out")):
                self.model.load_data(self.test_dir)
                root = self.model.invisibleRootItem()
                
                # Should handle timeout gracefully
                self.assertEqual(root.rowCount(), 0)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def _find_item_by_path(self, root_item, path):
        """Helper to find item by path"""
        parts = path.strip('/').split('/')
        current = root_item
        
        for part in parts:
            found = None
            for row in range(current.rowCount()):
                item = current.child(row)
                if item.text() == part:
                    found = item
                    break
            if not found:
                return None
            current = found
            
        return current
	
class TestFileIndexing(QtTestCase):
    """Test suite for filesystem indexing functionality"""

    def setUp(self):
        """Set up test environment with clean database and file structure"""
        # Create temporary test directory
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, 'test_index.db')
        
        # Create handler for IPC
        self.status_queue = multiprocessing.Queue()
        self.shutdown_event = multiprocessing.Event()
        
        # Initialize filesystem indexer
        self.indexer = FilesystemIndexer(
            self.db_path,
            self.status_queue,
            self.shutdown_event
        )
        
        # Create test file structure
        self.test_files = self._create_test_files()
        
        # Initialize database
        self._init_db()
        
        # Set up test tracking
        self.test_result = None

    def tearDown(self):
        """Clean up test environment"""
        try:
            # Signal indexer to stop
            if hasattr(self, 'shutdown_event'):
                self.shutdown_event.set()
            
            # Wait for indexer to finish
            if hasattr(self, 'indexer') and self.indexer.is_alive():
                self.indexer.join(timeout=2)
                if self.indexer.is_alive():
                    self.indexer.terminate()
            
            # Close queue
            if hasattr(self, 'status_queue'):
                self.status_queue.close()
                self.status_queue.join_thread()
            
            # Remove test directory and contents
            shutil.rmtree(self.test_dir, ignore_errors=True)
            
        except Exception as e:
            logging.warning(f"Cleanup failed: {e}")

    def test_index_creation(self):
        """Test index database creation and initialization"""
        self.test_result = TestResult(
            "index-create",
            "File System",
            "File Indexing",
            "Index Creation"
        )
        
        try:
            self.indexer._init_db()
            
            # Verify database structure
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='filesystem_index'
                """)
                self.assertIsNotNone(cursor.fetchone())
                
                # Verify index exists
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='index' AND tbl_name='filesystem_index'
                """)
                self.assertIsNotNone(cursor.fetchone())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_index_updates(self):
        """Test index update functionality"""
        self.test_result = TestResult(
            "index-update",
            "File System",
            "File Indexing",
            "Index Updates"
        )
        
        try:
            # Create test files
            test_files = [
                os.path.join(self.temp_dir, 'file1.txt'),
                os.path.join(self.temp_dir, 'file2.txt')
            ]
            for file_path in test_files:
                with open(file_path, 'w') as f:
                    f.write('test')
            
            # Mock drive scanning
            with patch.object(self.indexer, '_get_local_drives', return_value=[self.temp_dir]):
                self.indexer._sync_filesystem()
            
            # Verify files indexed
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM filesystem_index")
                count = cursor.fetchone()[0]
                self.assertEqual(count, len(test_files))
                
            # Add new file
            new_file = os.path.join(self.temp_dir, 'file3.txt')
            with open(new_file, 'w') as f:
                f.write('test')
                
            # Resync and verify update
            with patch.object(self.indexer, '_get_local_drives', return_value=[self.temp_dir]):
                self.indexer._sync_filesystem()
                
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM filesystem_index")
                count = cursor.fetchone()[0]
                self.assertEqual(count, len(test_files) + 1)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_search_functionality(self):
        """Test file search capabilities"""
        self.test_result = TestResult(
            "index-search",
            "File System",
            "File Indexing",
            "Search Functionality"
        )
        
        try:
            # Create test files with specific naming
            test_files = {
                'test_document.txt': 'test content',
                'another_test.txt': 'more content',
                'unrelated.txt': 'other content'
            }
            
            for name, content in test_files.items():
                path = os.path.join(self.temp_dir, name)
                with open(path, 'w') as f:
                    f.write(content)
            
            # Index the files
            with patch.object(self.indexer, '_get_local_drives', return_value=[self.temp_dir]):
                self.indexer._sync_filesystem()
            
            # Create FilesystemIndex instance for searching
            index = FilesystemIndex(self.db_path)
            
            # Test search
            results, truncated, stats = index.search('test')
            self.assertEqual(len(results), 2)  # Should find test_document.txt and another_test.txt
            
            # Test search with limit
            results, truncated, stats = index.search('test', max_results=1)
            self.assertEqual(len(results), 1)
            self.assertTrue(truncated)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_large_directory(self):
        """Test handling of large directory structures"""
        self.test_result = TestResult(
            "large-dir",
            "File System",
            "File Indexing",
            "Large Directory Handling"
        )
        
        try:
            # Create large directory structure
            large_dir = os.path.join(self.temp_dir, 'large_dir')
            os.makedirs(large_dir)
            
            # Create 1000 files across 10 subdirectories
            for i in range(10):
                subdir = os.path.join(large_dir, f'dir_{i}')
                os.makedirs(subdir)
                for j in range(100):
                    with open(os.path.join(subdir, f'file_{j}.txt'), 'w') as f:
                        f.write('test content')
            
            # Index the files
            with patch.object(self.indexer, '_get_local_drives', return_value=[large_dir]):
                self.indexer._sync_filesystem()
            
            # Verify all files indexed
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM filesystem_index")
                count = cursor.fetchone()[0]
                self.assertEqual(count, 1010)  # 1000 files + 10 directories
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_index_persistence(self):
        """Test index persistence across sessions"""
        self.test_result = TestResult(
            "index-persist",
            "File System",
            "File Indexing",
            "Index Persistence"
        )
        
        try:
            # Create and index test files
            test_file = os.path.join(self.temp_dir, 'persist_test.txt')
            with open(test_file, 'w') as f:
                f.write('test content')
                
            with patch.object(self.indexer, '_get_local_drives', return_value=[self.temp_dir]):
                self.indexer._sync_filesystem()
            
            # Create new indexer instance
            new_indexer = FilesystemIndexer(self.db_path, Queue(), Event())
            
            # Verify index persisted
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT path FROM filesystem_index")
                paths = [row[0] for row in cursor.fetchall()]
                self.assertIn(test_file, paths)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_index_recovery(self):
        """Test index recovery from corruption"""
        self.test_result = TestResult(
            "index-recovery",
            "File System",
            "File Indexing",
            "Index Recovery"
        )
        
        try:
            # Create initial index
            test_file = os.path.join(self.temp_dir, 'recovery_test.txt')
            with open(test_file, 'w') as f:
                f.write('test content')
                
            with patch.object(self.indexer, '_get_local_drives', return_value=[self.temp_dir]):
                self.indexer._sync_filesystem()
            
            # Corrupt the database
            with open(self.db_path, 'wb') as f:
                f.write(b'corrupted data')
            
            # Create new indexer - should handle corruption and rebuild
            new_indexer = FilesystemIndexer(self.db_path, Queue(), Event())
            new_indexer._init_db()
            
            with patch.object(new_indexer, '_get_local_drives', return_value=[self.temp_dir]):
                new_indexer._sync_filesystem()
            
            # Verify index rebuilt successfully
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT path FROM filesystem_index")
                paths = [row[0] for row in cursor.fetchall()]
                self.assertIn(test_file, paths)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_update_detection(self):
        """Test detection of filesystem changes"""
        self.test_result = TestResult(
            "index-updates",
            "Filesystem Index",
            "Updates",
            "Change Detection"
        )
        
        try:
            # Initialize database and start indexing
            self._init_test_db()
            self.filesystem_index.start_indexing()
            
            # Wait for initial indexing
            time.sleep(0.5)
            
            # Create a new file
            new_file = os.path.join(self.test_dir, 'dir1', 'newfile.txt')
            with open(new_file, 'w') as f:
                f.write('new content')
            
            # Wait for change detection
            time.sleep(0.5)
            
            # Verify new file is indexed
            results, _, _ = self.filesystem_index.search('newfile.txt')
            self.assertTrue(
                any(result['path'] == new_file for result in results),
                "Newly added file not found in index"
            )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_file_search(self):
        """Test file search functionality"""
        self.test_result = TestResult(
            "index-search",
            "File Indexing",
            "Search",
            "File Search"
        )
        
        try:
            # Start indexing and wait for completion
            self.indexer.start()
            self.assertTrue(self._wait_for_indexing())
            
            # Test exact filename search
            for test_file in self.test_files:
                filename = os.path.basename(test_file)
                results, truncated, stats = FilesystemIndex(self.db_path).search(filename)
                
                self.assertGreater(len(results), 0)
                self.assertTrue(
                    any(r['path'] == test_file for r in results),
                    f"File not found: {test_file}"
                )
            
            # Test partial name search
            results, truncated, stats = FilesystemIndex(self.db_path).search('file')
            self.assertEqual(
                len(results),
                len(self.test_files),
                "Not all test files found in partial search"
            )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_indexing_initialization(self):
        """Test index initialization"""
        self.test_result = TestResult(
            "index-init",
            "Filesystem Index",
            "Initialization",
            "Index Initialization"
        )
        
        try:
            # Ensure database is initialized
            self._init_test_db()
            
            # Start indexing
            self.filesystem_index.start_indexing()
            
            # Wait briefly for indexing to start
            time.sleep(0.1)
            
            # Verify database exists and has correct schema
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Check table exists
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='filesystem_index'
                """)
                self.assertIsNotNone(cursor.fetchone())
                
                # Check index exists
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='index' AND name='idx_path'
                """)
                self.assertIsNotNone(cursor.fetchone())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def _init_db(self):
        """Initialize test database with required schema"""
        with sqlite3.connect(self.db_path) as conn:
            # Create main filesystem index table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS filesystem_index (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    parent_path TEXT NOT NULL,
                    is_directory BOOLEAN NOT NULL,
                    last_modified DATETIME NOT NULL,
                    created DATETIME NOT NULL,
                    indexed_at DATETIME NOT NULL
                )
            """)
            
            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_path ON filesystem_index(path)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON filesystem_index(name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_parent ON filesystem_index(parent_path)")
            
            conn.commit()

    def _wait_for_indexing(self, timeout=5):
        """Wait for indexer to process files"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                msg_type, data = self.status_queue.get_nowait()
                if msg_type == 'sync_complete':
                    return True
            except Empty:
                time.sleep(0.1)
        return False

    def test_index_initialization(self):
        """Test index initialization"""
        self.test_result = TestResult(
            "index-init",
            "File Indexing",
            "Initialization",
            "Index Initialization"
        )
        
        try:
            # Verify database exists
            self.assertTrue(os.path.exists(self.db_path))
            
            # Check database schema
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Verify tables exist
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='filesystem_index'
                """)
                self.assertIsNotNone(cursor.fetchone())
                
                # Verify indexes exist
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='index' AND name IN ('idx_path', 'idx_name', 'idx_parent')
                """)
                indexes = cursor.fetchall()
                self.assertEqual(len(indexes), 3)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_file_indexing(self):
        """Test file indexing process"""
        self.test_result = TestResult(
            "index-process",
            "File Indexing",
            "Processing",
            "File Indexing Process"
        )
        
        try:
            # Start indexing
            self.indexer.start()
            
            # Wait for indexing to complete
            self.assertTrue(
                self._wait_for_indexing(),
                "Indexing timed out"
            )
            
            # Verify all test files were indexed
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for test_file in self.test_files:
                    cursor.execute(
                        "SELECT path FROM filesystem_index WHERE path = ?",
                        (test_file,)
                    )
                    self.assertIsNotNone(
                        cursor.fetchone(),
                        f"File not indexed: {test_file}"
                    )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def _create_test_files(self):
        """Create a test file hierarchy"""
        test_files = []
        
        # Create directory structure
        dirs = [
            os.path.join(self.test_dir, 'dir1'),
            os.path.join(self.test_dir, 'dir1', 'subdir1'),
            os.path.join(self.test_dir, 'dir2')
        ]
        
        for d in dirs:
            os.makedirs(d)
            
        # Create test files with content
        files = [
            ('dir1/file1.txt', 'content1'),
            ('dir1/subdir1/file2.txt', 'content2'),
            ('dir2/file3.txt', 'content3'),
        ]
        
        for rel_path, content in files:
            full_path = os.path.join(self.test_dir, rel_path.replace('/', os.sep))
            with open(full_path, 'w') as f:
                f.write(content)
            test_files.append(full_path)
            
        return test_files
    
class TestBackupOperations(QtTestCase):
    """Test suite for backup operations"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        
        # Create test files
        self.test_files = {
            'small.txt': b'test content',
            'medium.txt': os.urandom(1024 * 1024),  # 1MB
            'large.txt': os.urandom(5 * 1024 * 1024)  # 5MB
        }
        
        for name, content in self.test_files.items():
            path = os.path.join(self.temp_dir, name)
            with open(path, 'wb') as f:
                f.write(content)
                
        # Mock settings
        self.settings = {
            'API_KEY': 'test_key',
            'AGENT_ID': 'test_agent',
            'settings_path': self.temp_dir,
            'operation_id': 'test_op_123'
        }

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_single_file_backup(self):
        """Test backup of a single file"""
        self.test_result = TestResult(
            "backup-single",
            "Backup Operations",
            "Single File Backup",
            "Single File Backup"
        )
        
        try:
            file_path = os.path.join(self.temp_dir, 'small.txt')
            
            # Mock backup API call
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.return_value = True
                
                op = BackgroundOperation('backup', file_path, self.settings)
                op.start()
                
                # Process all updates
                while True:
                    try:
                        update = op.queue.get_nowait()
                        if update.get('type') == 'operation_complete':
                            self.assertEqual(update['success_count'], 1)
                            break
                    except Empty:
                        continue
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_directory_backup(self):
        """Test backup of entire directory"""
        self.test_result = TestResult(
            "backup-dir",
            "Backup Operations",
            "Directory Backup",
            "Directory Backup"
        )
        
        try:
            # Create test directory structure
            test_dir = os.path.join(self.temp_dir, 'test_dir')
            os.makedirs(test_dir)
            
            for name, content in self.test_files.items():
                path = os.path.join(test_dir, name)
                with open(path, 'wb') as f:
                    f.write(content)
            
            # Mock backup API call
            with patch('backup_utils.process_file', return_value=True):
                op = BackgroundOperation('backup', test_dir, self.settings)
                op.start()
                
                # Process updates
                success_count = 0
                while True:
                    try:
                        update = op.queue.get_nowait()
                        if update.get('type') == 'operation_complete':
                            success_count = update['success_count']
                            break
                    except Empty:
                        continue
                
                self.assertEqual(success_count, len(self.test_files))
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_large_file_handling(self):
        """Test backup of large files"""
        self.test_result = TestResult(
            "backup-large",
            "Backup Operations",
            "Large File Handling",
            "Large File Backup"
        )
        
        try:
            file_path = os.path.join(self.temp_dir, 'large.txt')
            
            # Mock chunked upload API
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.return_value = True
                
                op = BackgroundOperation('backup', file_path, self.settings)
                op.start()
                
                # Monitor progress updates
                progress_updates = []
                while True:
                    try:
                        update = op.queue.get_nowait()
                        if update.get('type') == 'file_progress':
                            progress_updates.append(update.get('progress', 0))
                        elif update.get('type') == 'operation_complete':
                            break
                    except Empty:
                        continue
                
                # Verify progress reporting
                self.assertTrue(len(progress_updates) > 1)
                self.assertTrue(all(0 <= p <= 100 for p in progress_updates))
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_incremental_backup(self):
        """Test incremental backup functionality"""
        self.test_result = TestResult(
            "backup-incremental",
            "Backup Operations",
            "Incremental Backup",
            "Incremental Backup"
        )
        
        try:
            file_path = os.path.join(self.temp_dir, 'incremental.txt')
            
            # Create initial file
            with open(file_path, 'w') as f:
                f.write('initial content')
                
            # Mock first backup
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.return_value = True
                initial_hash = hashlib.sha256(b'initial content').hexdigest()
                
                op = BackgroundOperation('backup', file_path, self.settings)
                op.start()
                self._wait_for_completion(op)
            
            # Modify file
            with open(file_path, 'w') as f:
                f.write('modified content')
                
            # Mock incremental backup
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.return_value = True
                new_hash = hashlib.sha256(b'modified content').hexdigest()
                
                op = BackgroundOperation('backup', file_path, self.settings)
                op.start()
                self._wait_for_completion(op)
                
                # Verify hash comparison was made
                mock_backup.assert_called_with(
                    file_path,
                    self.settings['API_KEY'],
                    self.settings['AGENT_ID'],
                    any,  # Hash DB connection
                    True  # Force flag
                )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_backup_verification(self):
        """Test backup verification process"""
        self.test_result = TestResult(
            "backup-verify",
            "Backup Operations",
            "Backup Verification",
            "Backup Verification"
        )
        
        try:
            file_path = os.path.join(self.temp_dir, 'verify.txt')
            with open(file_path, 'w') as f:
                f.write('test content')
                
            # Mock successful backup with verification
            with patch('backup_utils.process_file') as mock_backup, \
                 patch('backup_utils.verify_backup') as mock_verify:
                mock_backup.return_value = True
                mock_verify.return_value = True
                
                op = BackgroundOperation('backup', file_path, self.settings)
                op.start()
                
                completion = self._wait_for_completion(op)
                self.assertEqual(completion['success_count'], 1)
                
                # Mock failed verification
                mock_verify.return_value = False
                
                op = BackgroundOperation('backup', file_path, self.settings)
                op.start()
                
                completion = self._wait_for_completion(op)
                self.assertEqual(completion['fail_count'], 1)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_backup_recovery(self):
        """Test backup operation recovery"""
        self.test_result = TestResult(
            "backup-recovery",
            "Backup Operations",
            "Backup Recovery",
            "Backup Recovery"
        )
        
        try:
            file_path = os.path.join(self.temp_dir, 'recovery.txt')
            with open(file_path, 'w') as f:
                f.write('test content')
                
            # Mock failed backup with retry
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.side_effect = [ConnectionError(), True]  # Fail first, succeed on retry
                
                op = BackgroundOperation('backup', file_path, self.settings)
                op.start()
                
                completion = self._wait_for_completion(op)
                self.assertEqual(completion['success_count'], 1)
                self.assertEqual(mock_backup.call_count, 2)  # Verify retry occurred
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def _wait_for_completion(self, operation):
        """Helper to wait for operation completion"""
        while True:
            try:
                update = operation.queue.get_nowait()
                if update.get('type') == 'operation_complete':
                    return update
            except Empty:
                continue
	
class TestRestoreOperations(QtTestCase):
    """Test suite for restore operations"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.settings = {
            'API_KEY': 'test_key',
            'AGENT_ID': 'test_agent',
            'settings_path': self.temp_dir,
            'operation_id': 'test_op_123'
        }

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_single_file_restore(self):
        """Test restore of a single file"""
        self.test_result = TestResult(
            "restore-single",
            "Restore Operations",
            "Single File Restore",
            "Single File Restore"
        )
        
        try:
            file_path = '/test/path/file.txt'
            
            with patch('restore_utils.restore_file') as mock_restore:
                mock_restore.return_value = True
                
                op = BackgroundOperation('restore', file_path, self.settings)
                op.start()
                
                completion = self._wait_for_completion(op)
                self.assertEqual(completion['success_count'], 1)
                mock_restore.assert_called_once()
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_directory_restore(self):
        """Test restore of entire directory"""
        self.test_result = TestResult(
            "restore-dir",
            "Restore Operations",
            "Directory Restore",
            "Directory Restore"
        )
        
        try:
            test_files = [
                '/test/dir/file1.txt',
                '/test/dir/file2.txt',
                '/test/dir/subdir/file3.txt'
            ]
            
            with patch('restore_utils.restore_file') as mock_restore:
                mock_restore.return_value = True
                
                op = BackgroundOperation('restore', '/test/dir', self.settings)
                op._get_directory_files = MagicMock(return_value=test_files)
                op.start()
                
                completion = self._wait_for_completion(op)
                self.assertEqual(completion['success_count'], len(test_files))
                self.assertEqual(mock_restore.call_count, len(test_files))
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_version_selection(self):
        """Test restore of specific file version"""
        self.test_result = TestResult(
            "restore-version",
            "Restore Operations",
            "Version Selection",
            "Version Selection"
        )
        
        try:
            file_path = '/test/path/file.txt'
            version_id = 'v1_123'
            
            with patch('restore_utils.restore_file') as mock_restore:
                mock_restore.return_value = True
                
                settings = self.settings.copy()
                settings['version_id'] = version_id
                
                op = BackgroundOperation('restore', file_path, settings)
                op.start()
                
                completion = self._wait_for_completion(op)
                self.assertEqual(completion['success_count'], 1)
                
                mock_restore.assert_called_with(
                    file_path,
                    self.settings['API_KEY'],
                    self.settings['AGENT_ID'],
                    version_id
                )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_partial_restore(self):
        """Test partial restore functionality"""
        self.test_result = TestResult(
            "restore-partial",
            "Restore Operations",
            "Partial Restore",
            "Partial Restore"
        )
        
        try:
            test_files = [
                '/test/dir/file1.txt',
                '/test/dir/file2.txt',
                '/test/dir/file3.txt'
            ]
            
            with patch('restore_utils.restore_file') as mock_restore:
                # Simulate mixed success/failure
                mock_restore.side_effect = [True, False, True]
                
                op = BackgroundOperation('restore', '/test/dir', self.settings)
                op._get_directory_files = MagicMock(return_value=test_files)
                op.start()
                
                completion = self._wait_for_completion(op)
                self.assertEqual(completion['success_count'], 2)
                self.assertEqual(completion['fail_count'], 1)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_restore_verification(self):
        """Test restore verification process"""
        self.test_result = TestResult(
            "restore-verify",
            "Restore Operations",
            "Restore Verification",
            "Restore Verification"
        )
        
        try:
            file_path = '/test/path/file.txt'
            
            with patch('restore_utils.restore_file') as mock_restore, \
                 patch('restore_utils.verify_restore') as mock_verify:
                
                mock_restore.return_value = True
                mock_verify.return_value = True
                
                op = BackgroundOperation('restore', file_path, self.settings)
                op.start()
                
                completion = self._wait_for_completion(op)
                self.assertEqual(completion['success_count'], 1)
                mock_verify.assert_called_once()
                
                # Test failed verification
                mock_verify.return_value = False
                
                op = BackgroundOperation('restore', file_path, self.settings)
                op.start()
                
                completion = self._wait_for_completion(op)
                self.assertEqual(completion['fail_count'], 1)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_restore_recovery(self):
        """Test restore operation recovery"""
        self.test_result = TestResult(
            "restore-recovery",
            "Restore Operations",
            "Restore Recovery",
            "Restore Recovery"
        )
        
        try:
            file_path = '/test/path/file.txt'
            
            with patch('restore_utils.restore_file') as mock_restore:
                # Simulate failure then success
                mock_restore.side_effect = [ConnectionError(), True]
                
                op = BackgroundOperation('restore', file_path, self.settings)
                op.start()
                
                completion = self._wait_for_completion(op)
                self.assertEqual(completion['success_count'], 1)
                self.assertEqual(mock_restore.call_count, 2)  # Verify retry occurred
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def _wait_for_completion(self, operation):
        """Helper to wait for operation completion"""
        while True:
            try:
                update = operation.queue.get_nowait()
                if update.get('type') == 'operation_complete':
                    return update
            except Empty:
                continue
	
class TestProgressTracking(QtTestCase):
    """Test suite for operation progress tracking"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.progress_widget = OperationProgressWidget(MagicMock())
        self.settings = {
            'API_KEY': 'test_key',
            'AGENT_ID': 'test_agent',
            'settings_path': self.temp_dir,
            'operation_id': 'test_op_123'
        }

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_progress_calculation(self):
        """Test progress percentage calculation"""
        self.test_result = TestResult(
            "progress-calc",
            "Progress Tracking",
            "Progress Calculation",
            "Progress Calculation"
        )
        
        try:
            test_files = [f'file{i}.txt' for i in range(10)]
            
            with patch('backup_utils.process_file', return_value=True):
                op = BackgroundOperation('backup', test_files, self.settings)
                
                # Track progress updates
                progress_values = []
                
                def track_progress():
                    while True:
                        try:
                            update = op.queue.get_nowait()
                            if update.get('type') == 'file_progress':
                                progress = update.get('progress')
                                if progress is not None:
                                    progress_values.append(progress)
                            elif update.get('type') == 'operation_complete':
                                break
                        except Empty:
                            continue
                
                op.start()
                track_progress()
                
                # Verify progress values
                self.assertTrue(all(0 <= p <= 100 for p in progress_values))
                self.assertEqual(progress_values[-1], 100)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_progress_reporting(self):
        """Test progress update reporting"""
        self.test_result = TestResult(
            "progress-report",
            "Progress Tracking",
            "Progress Reporting",
            "Progress Reporting"
        )
        
        try:
            with patch('backup_utils.process_file', return_value=True):
                op = BackgroundOperation('backup', 'test.txt', self.settings)
                self.progress_widget.start_operation('backup', 'test.txt', self.settings)
                
                # Process updates
                op.start()
                while True:
                    try:
                        update = op.queue.get_nowait()
                        if update.get('type') == 'operation_complete':
                            break
                    except Empty:
                        continue
                
                # Verify widget state
                self.assertEqual(self.progress_widget.progress_bar.value(), 100)
                self.assertFalse(self.progress_widget.isVisible())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_cancellation_handling(self):
        """Test operation cancellation tracking"""
        self.test_result = TestResult(
            "progress-cancel",
            "Progress Tracking",
            "Cancellation Handling",
            "Cancellation Handling"
        )
        
        try:
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.return_value = True
                
                op = BackgroundOperation('backup', 'test.txt', self.settings)
                self.progress_widget.start_operation('backup', 'test.txt', self.settings)
                
                op.start()
                self.progress_widget.cancel_operation()
                
                # Verify cancellation state
                self.assertFalse(self.progress_widget.isVisible())
                self.assertIsNone(self.progress_widget.background_op)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_pause_resume(self):
        """Test pause/resume functionality"""
        self.test_result = TestResult(
            "progress-pause",
            "Progress Tracking",
            "Pause/Resume",
            "Pause/Resume"
        )
        
        try:
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.return_value = True
                
                op = BackgroundOperation('backup', 'test.txt', self.settings)
                self.progress_widget.start_operation('backup', 'test.txt', self.settings)
                
                # Track operation state
                states = []
                
                def track_state():
                    while True:
                        try:
                            update = op.queue.get_nowait()
                            states.append(update.get('type'))
                            if update.get('type') == 'operation_complete':
                                break
                        except Empty:
                            continue
                
                op.start()
                track_state()
                
                # Verify state transitions
                self.assertIn('operation_started', states)
                self.assertIn('operation_complete', states)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_error_reporting(self):
        """Test error status reporting"""
        self.test_result = TestResult(
            "progress-error",
            "Progress Tracking",
            "Error Reporting",
            "Error Reporting"
        )
        
        try:
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.side_effect = Exception("Test error")
                
                op = BackgroundOperation('backup', 'test.txt', self.settings)
                self.progress_widget.start_operation('backup', 'test.txt', self.settings)
                
                op.start()
                
                # Process updates until completion
                while True:
                    try:
                        update = op.queue.get_nowait()
                        if update.get('type') == 'operation_failed':
                            error_msg = update.get('error')
                            self.assertEqual(error_msg, "Test error")
                            break
                    except Empty:
                        continue
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_completion_verification(self):
        """Test operation completion verification"""
        self.test_result = TestResult(
            "progress-complete",
            "Progress Tracking",
            "Completion Verification",
            "Completion Verification"
        )
        
        try:
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.return_value = True
                
                op = BackgroundOperation('backup', 'test.txt', self.settings)
                self.progress_widget.start_operation('backup', 'test.txt', self.settings)
                
                completion_signal_received = False
                
                def on_complete(result):
                    nonlocal completion_signal_received
                    completion_signal_received = True
                    self.assertEqual(result['success_count'], 1)
                
                self.progress_widget.operation_completed.connect(on_complete)
                
                op.start()
                
                # Process updates until completion
                while True:
                    try:
                        update = op.queue.get_nowait()
                        if update.get('type') == 'operation_complete':
                            break
                    except Empty:
                        continue
                
                self.assertTrue(completion_signal_received)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise
	
# Required for Qt Tests
app = QApplication([])

class TestFileExplorer(QtTestCase):
    """Test suite for file explorer UI functionality"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.theme_manager = ThemeManager()
        self.settings_path = os.path.join(self.temp_dir, 'settings.cfg')
        
        # Create test settings file
        with open(self.settings_path, 'w') as f:
            f.write("API_KEY: test_key\nAGENT_ID: test_agent")
        
        # Create test directory structure
        os.makedirs(os.path.join(self.temp_dir, 'folder1'))
        os.makedirs(os.path.join(self.temp_dir, 'folder1', 'subfolder'))
        with open(os.path.join(self.temp_dir, 'folder1', 'test.txt'), 'w') as f:
            f.write('test content')
            
        self.explorer = FileExplorerPanel(
            self.temp_dir,
            self.theme_manager,
            self.settings_path,
            user_email='test@example.com'
        )

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_navigation(self):
        """Test file system navigation"""
        self.test_result = TestResult(
            "explorer-nav",
            "User Interface",
            "File Explorer",
            "Navigation"
        )
        
        try:
            # Get local tree view
            local_tree = self.explorer.local_tree
            
            # Expand root item
            root_index = local_tree.model().index(0, 0)
            local_tree.expandRecursively(root_index)
            
            # Find and click folder1
            folder1_index = None
            model = local_tree.model()
            for row in range(model.rowCount(root_index)):
                index = model.index(row, 0, root_index)
                if model.data(index) == 'folder1':
                    folder1_index = index
                    break
            
            self.assertIsNotNone(folder1_index)
            local_tree.setCurrentIndex(folder1_index)
            QTest.mouseClick(local_tree.viewport(), Qt.LeftButton,
                           pos=local_tree.visualRect(folder1_index).center())
            
            # Verify subfolder is visible
            found_subfolder = False
            for row in range(model.rowCount(folder1_index)):
                index = model.index(row, 0, folder1_index)
                if model.data(index) == 'subfolder':
                    found_subfolder = True
                    break
            
            self.assertTrue(found_subfolder)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_selection(self):
        """Test file selection handling"""
        self.test_result = TestResult(
            "explorer-select",
            "User Interface",
            "File Explorer",
            "Selection Handling"
        )
        
        try:
            local_tree = self.explorer.local_tree
            model = local_tree.model()
            
            # Find test file
            test_file_index = self._find_item_by_path(
                local_tree,
                os.path.join(self.temp_dir, 'folder1', 'test.txt')
            )
            
            self.assertIsNotNone(test_file_index)
            
            # Select file
            local_tree.setCurrentIndex(test_file_index)
            QTest.mouseClick(local_tree.viewport(), Qt.LeftButton,
                           pos=local_tree.visualRect(test_file_index).center())
            
            # Verify selection
            self.assertEqual(local_tree.currentIndex(), test_file_index)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_drag_drop(self):
        """Test drag and drop operations"""
        self.test_result = TestResult(
            "explorer-dragdrop",
            "User Interface",
            "File Explorer",
            "Drag and Drop"
        )
        
        try:
            # Set up source and target
            source_tree = self.explorer.local_tree
            target_tree = self.explorer.remote_tree
            
            # Find test file
            source_index = self._find_item_by_path(
                source_tree,
                os.path.join(self.temp_dir, 'folder1', 'test.txt')
            )
            
            self.assertIsNotNone(source_index)
            
            # Create drag event
            mime_data = QMimeData()
            mime_data.setText(source_index.data())
            
            # Create drop event
            drop_event = QDropEvent(
                QPoint(0, 0),
                Qt.CopyAction,
                mime_data,
                Qt.LeftButton,
                Qt.NoModifier
            )
            
            # Simulate drop
            target_tree.dropEvent(drop_event)
            
            # Verify operation started
            self.assertTrue(self.explorer.progress_widget.isVisible())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_context_menus(self):
        """Test context menu functionality"""
        self.test_result = TestResult(
            "explorer-context",
            "User Interface",
            "File Explorer",
            "Context Menus"
        )
        
        try:
            local_tree = self.explorer.local_tree
            
            # Find test file
            test_file_index = self._find_item_by_path(
                local_tree,
                os.path.join(self.temp_dir, 'folder1', 'test.txt')
            )
            
            self.assertIsNotNone(test_file_index)
            
            # Right click on file
            local_tree.setCurrentIndex(test_file_index)
            QTest.mouseClick(local_tree.viewport(), Qt.RightButton,
                           pos=local_tree.visualRect(test_file_index).center())
            
            # Verify context menu appears
            context_menu = QApplication.activePopupWidget()
            self.assertIsNotNone(context_menu)
            
            # Verify menu actions
            actions = [action.text() for action in context_menu.actions()]
            self.assertIn('Backup', actions)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_keyboard_shortcuts(self):
        """Test keyboard shortcut handling"""
        self.test_result = TestResult(
            "explorer-shortcuts",
            "User Interface",
            "File Explorer",
            "Keyboard Shortcuts"
        )
        
        try:
            local_tree = self.explorer.local_tree
            
            # Find and select test file
            test_file_index = self._find_item_by_path(
                local_tree,
                os.path.join(self.temp_dir, 'folder1', 'test.txt')
            )
            
            self.assertIsNotNone(test_file_index)
            local_tree.setCurrentIndex(test_file_index)
            
            # Test Enter key
            QTest.keyClick(local_tree, Qt.Key_Return)
            
            # Test Delete key
            with patch('os.remove') as mock_remove:
                QTest.keyClick(local_tree, Qt.Key_Delete)
                self.assertFalse(mock_remove.called)  # Should show confirmation dialog
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_accessibility(self):
        """Test accessibility features"""
        self.test_result = TestResult(
            "explorer-access",
            "User Interface",
            "File Explorer",
            "Accessibility Features"
        )
        
        try:
            local_tree = self.explorer.local_tree
            
            # Test keyboard navigation
            first_index = local_tree.model().index(0, 0)
            local_tree.setCurrentIndex(first_index)
            
            # Tab navigation
            QTest.keyClick(local_tree, Qt.Key_Tab)
            self.assertTrue(self.explorer.remote_tree.hasFocus())
            
            # Arrow key navigation
            QTest.keyClick(local_tree, Qt.Key_Down)
            current_index = local_tree.currentIndex()
            self.assertNotEqual(current_index, first_index)
            
            # Test screen reader accessibility
            self.assertIsNotNone(local_tree.accessibleName())
            self.assertIsNotNone(local_tree.accessibleDescription())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def _find_item_by_path(self, tree_view, path):
        """Helper to find tree item by path"""
        model = tree_view.model()
        parts = path.split(os.sep)
        current_index = model.index(0, 0)  # Start at root
        
        for part in parts:
            found = False
            for row in range(model.rowCount(current_index)):
                index = model.index(row, 0, current_index)
                if model.data(index) == part:
                    current_index = index
                    found = True
                    break
            if not found:
                return None
                
        return current_index
	
# Required for Qt Tests
app = QApplication([])

class TestProgressDisplay(QtTestCase):
    """Test suite for operation progress display"""

    def setUp(self):
        self.theme_manager = ThemeManager()
        parent_mock = MagicMock()
        parent_mock.theme_manager = self.theme_manager
        self.progress_widget = OperationProgressWidget(parent_mock)
        
        # Mock settings
        self.settings = {
            'API_KEY': 'test_key',
            'AGENT_ID': 'test_agent',
            'operation_id': 'test_op_123',
            'user_email': 'test@example.com'
        }

    def test_progress_updates(self):
        """Test progress bar updates"""
        self.test_result = TestResult(
            "progress-updates",
            "User Interface",
            "Progress Display",
            "Progress Updates"
        )
        
        try:
            # Start mock operation
            self.progress_widget.start_operation('backup', 'test.txt', self.settings)
            
            # Initial state
            self.assertTrue(self.progress_widget.isVisible())
            self.assertEqual(self.progress_widget.progress_bar.value(), 0)
            
            # Update progress
            test_values = [25, 50, 75, 100]
            for value in test_values:
                self.progress_widget.progress_bar.setValue(value)
                self.assertEqual(self.progress_widget.progress_bar.value(), value)
            
            # Complete operation
            self.progress_widget.cleanup()
            self.assertFalse(self.progress_widget.isVisible())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_status_messages(self):
        """Test status message display"""
        self.test_result = TestResult(
            "progress-messages",
            "User Interface",
            "Progress Display",
            "Status Messages"
        )
        
        try:
            self.progress_widget.start_operation('backup', 'test.txt', self.settings)
            
            # Test operation label
            self.assertEqual(
                self.progress_widget.operation_label.text(),
                "Operation: Backup"
            )
            
            # Test file label
            test_path = "long/path/to/test.txt"
            self.progress_widget.current_file_label.setText(f"Processing: {test_path}")
            self.assertTrue(
                self.progress_widget.current_file_label.text().endswith(test_path)
            )
            
            # Test file count
            self.progress_widget.file_count_label.setText("Files: 5/10")
            self.assertEqual(
                self.progress_widget.file_count_label.text(),
                "Files: 5/10"
            )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_error_display(self):
        """Test error message display"""
        self.test_result = TestResult(
            "progress-error",
            "User Interface",
            "Progress Display",
            "Error Display"
        )
        
        try:
            self.progress_widget.start_operation('backup', 'test.txt', self.settings)
            
            # Simulate error
            error_msg = "Test error message"
            self.progress_widget.on_operation_error(error_msg)
            
            # Verify error state
            self.assertTrue(hasattr(self.progress_widget, 'error_label'))
            self.assertTrue(self.progress_widget.error_label.isVisible())
            self.assertTrue(error_msg in self.progress_widget.error_label.text())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_cancellation_ui(self):
        """Test cancellation button functionality"""
        self.test_result = TestResult(
            "progress-cancel-ui",
            "User Interface",
            "Progress Display",
            "Cancellation UI"
        )
        
        try:
            self.progress_widget.start_operation('backup', 'test.txt', self.settings)
            
            # Verify cancel button exists and is enabled
            self.assertTrue(hasattr(self.progress_widget, 'cancel_button'))
            self.assertTrue(self.progress_widget.cancel_button.isEnabled())
            
            # Test cancellation
            cancel_clicked = False
            
            def on_cancel():
                nonlocal cancel_clicked
                cancel_clicked = True
            
            self.progress_widget.cancel_button.clicked.connect(on_cancel)
            QTest.mouseClick(self.progress_widget.cancel_button, Qt.LeftButton)
            
            self.assertTrue(cancel_clicked)
            self.assertFalse(self.progress_widget.isVisible())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_progress_persistence(self):
        """Test progress state persistence"""
        self.test_result = TestResult(
            "progress-persist",
            "User Interface",
            "Progress Display",
            "Progress Persistence"
        )
        
        try:
            # Start operation
            self.progress_widget.start_operation('backup', 'test.txt', self.settings)
            
            # Set initial progress
            self.progress_widget.progress_bar.setValue(50)
            initial_value = self.progress_widget.progress_bar.value()
            
            # Hide and show widget
            self.progress_widget.hide()
            self.progress_widget.show()
            
            # Verify progress persisted
            self.assertEqual(self.progress_widget.progress_bar.value(), initial_value)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_multiple_operations(self):
        """Test handling of multiple operations"""
        self.test_result = TestResult(
            "progress-multiple",
            "User Interface",
            "Progress Display",
            "Multiple Operations"
        )
        
        try:
            # Start first operation
            self.progress_widget.start_operation('backup', 'test1.txt', self.settings)
            self.progress_widget.progress_bar.setValue(50)
            
            # Start second operation
            new_settings = self.settings.copy()
            new_settings['operation_id'] = 'test_op_456'
            self.progress_widget.start_operation('backup', 'test2.txt', new_settings)
            
            # Verify second operation state
            self.assertEqual(self.progress_widget.progress_bar.value(), 0)
            self.assertTrue('test2.txt' in self.progress_widget.current_file_label.text())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_theme_integration(self):
        """Test theme system integration"""
        self.test_result = TestResult(
            "progress-theme",
            "User Interface",
            "Progress Display",
            "Theme Integration"
        )
        
        try:
            # Start operation
            self.progress_widget.start_operation('backup', 'test.txt', self.settings)
            
            # Test theme change
            self.theme_manager.set_theme("Light")
            
            # Verify theme applied
            theme = self.theme_manager.get_theme("Light")
            
            # Check progress bar colors
            progress_bar = self.progress_widget.progress_bar
            style = progress_bar.styleSheet()
            self.assertIn(theme['accent_color'], style)
            
            # Check label colors
            operation_label = self.progress_widget.operation_label
            self.assertIn(theme['text_primary'], operation_label.styleSheet())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise
	
# Required for Qt Tests
app = QApplication([])

class TestThemeIntegration(QtTestCase):
    """Test suite for theme system integration"""

    def setUp(self):
        self.theme_manager = ThemeManager()
        self.mock_parent = MagicMock()
        self.mock_parent.theme_manager = self.theme_manager

    def test_theme_application(self):
        """Test theme application across components"""
        self.test_result = TestResult(
            "theme-apply",
            "User Interface",
            "Theme Integration",
            "Theme Application"
        )
        
        try:
            # Create test window with various components
            window = QMainWindow()
            window.setObjectName("TestWindow")
            
            # Add test components
            button = QPushButton("Test Button", window)
            button.setObjectName("TestButton")
            
            label = QLabel("Test Label", window)
            label.setObjectName("TestLabel")
            
            input_field = QLineEdit(window)
            input_field.setObjectName("TestInput")
            
            # Apply dark theme
            theme = self.theme_manager.get_theme("Dark Age Classic Dark")
            window.setStyleSheet(theme["stylesheet"])
            
            # Verify colors
            self.assertEqual(
                window.palette().color(window.backgroundRole()).name(),
                theme["app_background"]
            )
            
            self.assertEqual(
                button.palette().color(button.foregroundRole()).name(),
                theme["button_text"]
            )
            
            self.assertEqual(
                label.palette().color(label.foregroundRole()).name(),
                theme["text_primary"]
            )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_component_styling(self):
        """Test individual component style application"""
        self.test_result = TestResult(
            "theme-styling",
            "User Interface",
            "Theme Integration",
            "Component Styling"
        )
        
        try:
            # Test login dialog styling
            dialog = LoginDialog(self.theme_manager, "test_path")
            
            # Verify input field styling
            email_input = dialog.email_input
            password_input = dialog.password_input
            
            theme = self.theme_manager.get_theme(self.theme_manager.current_theme)
            
            # Check input background colors
            self.assertEqual(
                email_input.palette().color(email_input.backgroundRole()).name(),
                theme["input_background"]
            )
            
            # Check border colors
            self.assertIn(
                f"border: 1px solid {theme['input_border']}", 
                email_input.styleSheet()
            )
            
            # Check error label styling
            error_label = dialog.error_label
            self.assertIn(
                theme["payment_failed"],
                error_label.styleSheet()
            )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_dynamic_updates(self):
        """Test dynamic theme updates"""
        self.test_result = TestResult(
            "theme-dynamic",
            "User Interface",
            "Theme Integration",
            "Dynamic Updates"
        )
        
        try:
            # Create file explorer with initial theme
            explorer = FileExplorerPanel(
                "test_dir",
                self.theme_manager,
                "test_path",
                user_email="test@example.com"
            )
            
            initial_theme = self.theme_manager.current_theme
            initial_style = explorer.styleSheet()
            
            # Change theme
            new_theme = "Light" if initial_theme == "Dark Age Classic Dark" else "Dark Age Classic Dark"
            self.theme_manager.set_theme(new_theme)
            
            # Verify update
            self.assertNotEqual(explorer.styleSheet(), initial_style)
            
            # Check specific elements
            theme = self.theme_manager.get_theme(new_theme)
            
            # Verify tree view colors
            local_tree = explorer.local_tree
            self.assertEqual(
                local_tree.palette().color(local_tree.backgroundRole()).name(),
                theme["panel_background"]
            )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_custom_themes(self):
        """Test custom theme handling"""
        self.test_result = TestResult(
            "theme-custom",
            "User Interface",
            "Theme Integration",
            "Custom Themes"
        )
        
        try:
            # Create custom theme
            custom_theme = {
                "app_background": "#000000",
                "panel_background": "#111111",
                "text_primary": "#FFFFFF",
                "text_secondary": "#AAAAAA",
                "accent_color": "#FF0000",
                "accent_color_hover": "#FF3333",
                "button_text": "#FFFFFF",
                "input_background": "#222222",
                "input_border": "#333333",
                "stylesheet": """
                    QWidget { 
                        background-color: #000000; 
                        color: #FFFFFF; 
                    }
                    QPushButton { 
                        background-color: #FF0000; 
                        color: #FFFFFF; 
                    }
                """
            }
            
            # Add custom theme
            with patch.dict(self.theme_manager.themes, {'Custom': custom_theme}):
                self.theme_manager.set_theme('Custom')
                
                # Test application
                window = QMainWindow()
                window.setStyleSheet(custom_theme["stylesheet"])
                
                # Verify colors
                self.assertEqual(
                    window.palette().color(window.backgroundRole()).name(),
                    custom_theme["app_background"]
                )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_default_fallbacks(self):
        """Test theme fallback mechanism"""
        self.test_result = TestResult(
            "theme-fallback",
            "User Interface",
            "Theme Integration",
            "Default Fallbacks"
        )
        
        try:
            # Request non-existent theme
            theme = self.theme_manager.get_theme("NonexistentTheme")
            
            # Should fall back to dark theme
            self.assertEqual(
                theme["app_background"],
                self.theme_manager.get_theme("Dark Age Classic Dark")["app_background"]
            )
            
            # Test partial theme
            partial_theme = {
                "app_background": "#000000"
                # Missing other required colors
            }
            
            with patch.dict(self.theme_manager.themes, {'Partial': partial_theme}):
                theme = self.theme_manager.get_theme('Partial')
                
                # Should have fallback values for missing colors
                self.assertTrue(all(key in theme for key in [
                    "text_primary",
                    "accent_color",
                    "button_text",
                    "input_background"
                ]))
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_transition_effects(self):
        """Test theme transition effects"""
        self.test_result = TestResult(
            "theme-transition",
            "User Interface",
            "Theme Integration",
            "Transition Effects"
        )
        
        try:
            # Create animated button
            from sc_app import AnimatedButton
            button = AnimatedButton("Test")
            
            # Test color transition
            initial_color = button._current_color
            
            # Simulate hover
            button.enterEvent(None)
            
            # Verify animation properties
            self.assertTrue(hasattr(button, 'color_animation'))
            self.assertEqual(button.color_animation.duration(), 300)
            
            # Verify final color different from initial
            self.assertNotEqual(button._target_color, initial_color)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

class TestScheduleManagement(QtTestCase):
    """Test suite for backup schedule management"""

    def setUp(self):
        self.theme_manager = ThemeManager()
        self.calendar = BackupScheduleCalendar(self.theme_manager)
        self.test_schedule = {
            'weekly': {
                'Monday': [QTime(9, 0), QTime(17, 0)],
                'Friday': [QTime(12, 0)]
            },
            'monthly': {
                '1': [QTime(0, 0)],
                'Last day': [QTime(23, 0)]
            }
        }

    def test_schedule_creation(self):
        """Test schedule creation and validation"""
        self.test_result = TestResult(
            "schedule-create",
            "Schedule Management",
            "Schedule Creation",
            "Schedule Creation"
        )
        
        try:
            # Add weekly backup
            self.calendar.day_combo.setCurrentText('Monday')
            self.calendar.weekly_time_edit.setTime(QTime(9, 0))
            self.calendar.add_weekly_backup()
            
            # Verify schedule
            self.assertIn('Monday', self.calendar.schedule['weekly'])
            self.assertEqual(len(self.calendar.schedule['weekly']['Monday']), 1)
            
            # Add monthly backup
            self.calendar.day_of_month_combo.setCurrentText('1st')
            self.calendar.monthly_time_edit.setTime(QTime(0, 0))
            self.calendar.add_monthly_backup()
            
            self.assertIn('1', self.calendar.schedule['monthly'])
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

class TestErrorLogging(NonQtTestCase):
    """Test suite for error logging functionality"""

    def setUp(self):
        """Set up test environment with isolated logging"""
        # Create temporary directory for logs
        self.log_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.log_dir, 'test.log')
        
        # Store original logging configuration
        self.original_handlers = logging.getLogger().handlers.copy()
        logging.getLogger().handlers.clear()
        
        # Configure logging for tests
        self.log_handler = logging.FileHandler(self.log_path)
        self.log_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        )
        logging.getLogger().addHandler(self.log_handler)
        logging.getLogger().setLevel(logging.DEBUG)

    def tearDown(self):
        """Clean up logging configuration and temporary files"""
        # Close and remove our test handler
        self.log_handler.close()
        logging.getLogger().removeHandler(self.log_handler)
        
        # Restore original logging configuration
        logging.getLogger().handlers = self.original_handlers
        
        # Clean up temporary directory
        try:
            shutil.rmtree(self.log_dir)
        except Exception as e:
            print(f"Warning: Failed to clean up log directory: {e}")

    def read_log_content(self):
        """Helper to read and return log file contents"""
        try:
            with open(self.log_path, 'r') as f:
                return f.read()
        except Exception as e:
            self.fail(f"Failed to read log file: {e}")

    def test_operation_logging(self):
        """Test operation error logging"""
        self.test_result = TestResult(
            "error-op-log",
            "Error Logging",
            "Operation Logging",
            "Operation Error Logging"
        )
        
        try:
            # Simulate operation error
            test_error = "Test operation error"
            try:
                raise ValueError(test_error)
            except Exception as e:
                logging.error(f"Operation failed: {e}", exc_info=True)
            
            # Verify log content
            log_content = self.read_log_content()
            
            # Check for required elements
            self.assertIn("Operation failed", log_content)
            self.assertIn("ValueError", log_content)
            self.assertIn(test_error, log_content)
            self.assertIn("Traceback", log_content)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_file_logging(self):
        """Test file operation logging"""
        self.test_result = TestResult(
            "error-file-log",
            "Error Logging",
            "File Logging",
            "File Operation Logging"
        )
        
        try:
            # Simulate file operation error with non-existent path
            test_path = os.path.join(self.log_dir, 'nonexistent', 'file.txt')
            
            try:
                with open(test_path, 'r') as f:
                    f.read()
            except Exception as e:
                logging.error(f"File operation failed: {e}")
            
            # Verify log content
            log_content = self.read_log_content()
            self.assertIn("File operation failed", log_content)
            self.assertIn("FileNotFoundError", log_content)
            self.assertIn(test_path, log_content)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_log_rotation(self):
        """Test log file rotation"""
        self.test_result = TestResult(
            "error-rotation",
            "Error Logging",
            "Log Rotation",
            "Log File Rotation"
        )
        
        try:
            # Configure rotation handler
            max_bytes = 1024  # Small size to trigger rotation
            backup_count = 3
            rotate_handler = logging.handlers.RotatingFileHandler(
                self.log_path,
                maxBytes=max_bytes,
                backupCount=backup_count
            )
            rotate_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            
            # Replace existing handler with rotation handler
            logging.getLogger().removeHandler(self.log_handler)
            logging.getLogger().addHandler(rotate_handler)
            
            # Generate enough logs to trigger rotation
            for i in range(1000):
                logging.error(f"Test log entry {i}")
            
            # Verify rotation occurred
            log_files = [f for f in os.listdir(self.log_dir) if f.endswith('.log')]
            self.assertGreater(len(log_files), 1)
            self.assertLessEqual(len(log_files), backup_count + 1)
            
            # Verify each rotated file contains logged data
            for log_file in log_files:
                with open(os.path.join(self.log_dir, log_file), 'r') as f:
                    content = f.read()
                    self.assertIn("Test log entry", content)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise
        finally:
            # Restore original handler
            logging.getLogger().removeHandler(rotate_handler)
            logging.getLogger().addHandler(self.log_handler)

class TestSecurity(NonQtTestCase):
    """Test suite for security features"""

    def setUp(self):
        logging.info("Setting up TestSecurity")
        self.temp_dir = tempfile.mkdtemp()
        self.test_data = {
            'access_token': 'test_token_123',
            'refresh_token': 'refresh_456',
            'user_email': 'test@example.com'
        }
        self.test_key = b64encode(b'test_key'.ljust(32, b'0'))
        self.cipher_suite = Fernet(self.test_key)

    def tearDown(self):
        logging.info("Tearing down TestSecurity")
        shutil.rmtree(self.temp_dir)

    def _normalize_path(self, path):
        """Platform-independent path normalization"""
        return os.path.normpath(path).replace('\\', '/')
        
    def _is_safe_path(self, path):
        """Check if a path is safe to access"""
        normalized = self._normalize_path(path)
        
        # List of forbidden patterns/paths
        forbidden_patterns = [
            '../', '..\\'  # Directory traversal
            '/etc/', '\etc\\', 
            '/var/', '\var\\',
            '/root/', '\root\\',
            '/sys/', '\sys\\',
            'C:\\Windows\\', 'C:/Windows/',
            'C:\\Program Files', 'C:/Program Files'
        ]
        
        return not any(pattern in normalized for pattern in forbidden_patterns)

    def test_path_validation(self):
        """Test file path validation and sanitization"""
        logging.info("Testing path validation")
        try:
            test_paths = {
                '../../../etc/passwd': False,  # Directory traversal
                'C:\\Windows\\System32\\config': False,  # System directory
                '/var/log/syslog': False,  # System logs
                'user/documents/file.txt': True,  # Valid path
                'C:\\Users\\Public\\Documents\\test.txt': True  # Valid Windows path
            }

            for path, should_allow in test_paths.items():
                is_allowed = self._is_safe_path(path)
                self.assertEqual(
                    is_allowed, 
                    should_allow,
                    f"Path validation failed for {path}"
                )
        except Exception as e:
            logging.error(f"Path validation test failed: {e}")
            raise

    def test_permission_validation(self):
        """Test file permission validation"""
        logging.info("Testing permission validation")
        
        if os.name == 'nt':  # Windows
            import win32security
            import ntsecuritycon as con
            
            try:
                # Create test file
                test_file = os.path.join(self.temp_dir, 'test.txt')
                with open(test_file, 'w') as f:
                    f.write('test content')
                logging.info(f"Created test file: {test_file}")

                # Get current user's SID
                current_user = win32security.GetTokenInformation(
                    win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY),
                    win32security.TokenUser
                )[0]

                # Get current security descriptor
                security = win32security.GetFileSecurity(
                    test_file, 
                    win32security.DACL_SECURITY_INFORMATION
                )

                # Create new DACL
                dacl = win32security.ACL()
                
                # Test readable permission
                dacl.AddAccessAllowedAce(
                    win32security.ACL_REVISION,
                    con.FILE_GENERIC_READ,
                    current_user
                )
                security.SetSecurityDescriptorDacl(1, dacl, 0)
                win32security.SetFileSecurity(
                    test_file, 
                    win32security.DACL_SECURITY_INFORMATION,
                    security
                )
                
                self.assertTrue(os.access(test_file, os.R_OK))
                self.assertFalse(os.access(test_file, os.W_OK))
                logging.info("Verified read-only permissions")

                # Test no permissions
                dacl = win32security.ACL()
                security.SetSecurityDescriptorDacl(1, dacl, 0)
                win32security.SetFileSecurity(
                    test_file, 
                    win32security.DACL_SECURITY_INFORMATION,
                    security
                )
                
                # Need to close any open handles before checking permissions
                import gc
                gc.collect()
                
                self.assertFalse(os.access(test_file, os.R_OK))
                self.assertFalse(os.access(test_file, os.W_OK))
                logging.info("Verified restricted permissions")

            except Exception as e:
                logging.error(f"Permission validation test failed: {e}")
                raise
                
            finally:
                # Restore permissions for cleanup
                try:
                    dacl = win32security.ACL()
                    dacl.AddAccessAllowedAce(
                        win32security.ACL_REVISION,
                        con.FILE_ALL_ACCESS,
                        current_user
                    )
                    security.SetSecurityDescriptorDacl(1, dacl, 0)
                    win32security.SetFileSecurity(
                        test_file, 
                        win32security.DACL_SECURITY_INFORMATION,
                        security
                    )
                except Exception as e:
                    logging.warning(f"Failed to restore permissions during cleanup: {e}")

        else:  # Unix/Linux
            try:
                # Create test file
                test_file = os.path.join(self.temp_dir, 'test.txt')
                with open(test_file, 'w') as f:
                    f.write('test content')
                logging.info(f"Created test file: {test_file}")

                # Test readable permission
                os.chmod(test_file, 0o444)  # Read-only for everyone
                self.assertTrue(os.access(test_file, os.R_OK))
                self.assertFalse(os.access(test_file, os.W_OK))
                logging.info("Verified read-only permissions")

                # Test restricted permissions
                os.chmod(test_file, 0o000)  # No permissions
                self.assertFalse(os.access(test_file, os.R_OK))
                self.assertFalse(os.access(test_file, os.W_OK))
                logging.info("Verified restricted permissions")

            except Exception as e:
                logging.error(f"Permission validation test failed: {e}")
                raise
                
            finally:
                # Restore permissions for cleanup
                try:
                    os.chmod(test_file, 0o644)
                except Exception as e:
                    logging.warning(f"Failed to restore permissions during cleanup: {e}")

    def test_token_encryption(self):
        """Test encryption and decryption of auth tokens"""
        logging.info("Testing token encryption")
        try:
            # Encrypt test data
            encrypted = self.cipher_suite.encrypt(
                json.dumps(self.test_data).encode()
            )
            logging.info("Successfully encrypted test data")

            # Verify encryption masks sensitive data
            encrypted_str = str(encrypted)
            self.assertNotIn('test_token_123', encrypted_str)
            self.assertNotIn('refresh_456', encrypted_str)
            logging.info("Verified sensitive data is masked")

            # Test decryption
            decrypted = json.loads(
                self.cipher_suite.decrypt(encrypted).decode()
            )
            self.assertEqual(decrypted['access_token'], self.test_data['access_token'])
            self.assertEqual(decrypted['refresh_token'], self.test_data['refresh_token'])
            logging.info("Successfully decrypted and verified data")

        except Exception as e:
            logging.error(f"Token encryption test failed: {e}")
            raise

class TestHistoryTracking(NonQtTestCase):
    """Test suite for operation history tracking"""

    def setUp(self):
        """Set up test environment"""
        logging.info("Setting up TestHistoryTracking")
        
        # Create temporary test directory
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, 'test_history.db')
        
        # Initialize history manager with test database
        self.history_manager = HistoryManager(self.db_path)
        
        # Set test variables
        self.test_user_email = "test@example.com"
        self.system_email = "System"
        
        # Initialize tracking
        self.test_result = None
        
        # Initialize database
        self._init_db()

    def tearDown(self):
        """Clean up test environment"""
        try:
            shutil.rmtree(self.test_dir)
        except Exception as e:
            logging.warning(f"Failed to clean up test directory: {e}")
            
    def _init_db(self):
        """Initialize test database with required schema"""
        with sqlite3.connect(self.db_path) as conn:
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
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_records (
                    id INTEGER PRIMARY KEY,
                    operation_id TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    FOREIGN KEY (operation_id) REFERENCES operations(operation_id)
                )
            """)
            
            conn.commit()

    def test_operation_recording(self):
        """Test operation recording and retrieval"""
        self.test_result = TestResult(
            "history-record",
            "History Tracking",
            "Recording",
            "Operation Recording"
        )
        
        try:
            # Create test operation
            operation_id = self._create_test_operation()
            
            # Retrieve operation
            operation = self.history_manager.get_operation(operation_id)
            
            # Verify operation details
            self.assertIsNotNone(operation)
            self.assertEqual(operation.user_email, self.test_user_email)
            self.assertEqual(operation.status, OperationStatus.SUCCESS)
            self.assertEqual(len(operation.files), 3)
            
            # Verify file records
            success_files = [f for f in operation.files if f.status == OperationStatus.SUCCESS]
            failed_files = [f for f in operation.files if f.status == OperationStatus.FAILED]
            
            self.assertEqual(len(success_files), 2)
            self.assertEqual(len(failed_files), 1)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_history_queries(self):
        """Test history query functionality"""
        self.test_result = TestResult(
            "history-query",
            "History Tracking",
            "Queries",
            "History Queries"
        )
        
        try:
            # Create test operations
            operations = []
            for i in range(5):
                op_id = self._create_test_operation(
                    operation_type='backup',
                    status=OperationStatus.SUCCESS if i % 2 == 0 else OperationStatus.FAILED
                )
                operations.append(op_id)
                time.sleep(0.1)  # Ensure unique timestamps
            
            # Test pagination
            page_1 = self.history_manager.get_history('backup', page=1)
            self.assertEqual(len(page_1), min(len(operations), self.history_manager.page_size))
            
            # Test operation type filtering
            restore_op = self._create_test_operation(operation_type='restore')
            backup_ops = self.history_manager.get_history('backup')
            restore_ops = self.history_manager.get_history('restore')
            
            self.assertEqual(len(backup_ops), len(operations))
            self.assertEqual(len(restore_ops), 1)
            
            # Verify operation order (newest first)
            for i in range(len(backup_ops) - 1):
                self.assertGreaterEqual(
                    backup_ops[i].timestamp,
                    backup_ops[i + 1].timestamp
                )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_operation_attribution(self):
        """Test operation user attribution"""
        self.test_result = TestResult(
            "history-attr",
            "History Tracking",
            "Attribution",
            "Operation Attribution"
        )
        
        try:
            # Test user-initiated operation
            user_op_id = self._create_test_operation(
                source=InitiationSource.USER,
                user_email=self.test_user_email
            )
            
            # Test system operation
            system_op_id = self._create_test_operation(
                source=InitiationSource.REALTIME,
                user_email=self.system_email
            )
            
            # Test scheduled operation
            scheduled_op_id = self._create_test_operation(
                source=InitiationSource.SCHEDULED,
                user_email=self.system_email
            )
            
            # Verify attribution
            user_op = self.history_manager.get_operation(user_op_id)
            system_op = self.history_manager.get_operation(system_op_id)
            scheduled_op = self.history_manager.get_operation(scheduled_op_id)
            
            self.assertEqual(user_op.user_email, self.test_user_email)
            self.assertEqual(system_op.user_email, self.system_email)
            self.assertEqual(scheduled_op.user_email, self.system_email)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise
            
    def _create_test_operation(self, operation_type='backup', source=InitiationSource.USER, 
                             status=OperationStatus.SUCCESS, user_email=None):
        """Create a test operation with optional file records"""
        operation_id = self.history_manager.start_operation(
            operation_type,
            source,
            user_email or self.test_user_email
        )
        
        # Add some test files
        test_files = [
            ("/test/file1.txt", OperationStatus.SUCCESS, None),
            ("/test/file2.txt", OperationStatus.FAILED, "Test error"),
            ("/test/file3.txt", OperationStatus.SUCCESS, None)
        ]
        
        for filepath, file_status, error in test_files:
            self.history_manager.add_file_to_operation(
                operation_id,
                filepath,
                file_status,
                error
            )
        
        self.history_manager.complete_operation(
            operation_id,
            status,
            "Test operation completed"
        )
        
        return operation_id
        
    def test_status_updates(self):
        """Test operation status updates"""
        self.test_result = TestResult(
            "history-status",
            "History Tracking",
            "Status Updates",
            "Status Updates"
        )
        
        try:
            # Start operation
            operation_id = self.history_manager.start_operation(
                'backup',
                InitiationSource.USER,
                self.test_user_email
            )
            
            # Add files with different statuses
            self.history_manager.add_file_to_operation(
                operation_id,
                "/test/success.txt",
                OperationStatus.SUCCESS
            )
            
            self.history_manager.add_file_to_operation(
                operation_id,
                "/test/failed.txt",
                OperationStatus.FAILED,
                "Test failure"
            )
            
            # Complete operation
            self.history_manager.complete_operation(
                operation_id,
                OperationStatus.FAILED,
                "Operation partially failed"
            )
            
            # Verify final status
            operation = self.history_manager.get_operation(operation_id)
            self.assertEqual(operation.status, OperationStatus.FAILED)
            self.assertEqual(len(operation.files), 2)
            
            success_files = [f for f in operation.files if f.status == OperationStatus.SUCCESS]
            failed_files = [f for f in operation.files if f.status == OperationStatus.FAILED]
            
            self.assertEqual(len(success_files), 1)
            self.assertEqual(len(failed_files), 1)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

class TestProcessManagement(NonQtTestCase):
    """Test suite for process management"""

    def setUp(self):
        """Set up test environment"""
        logging.info("Setting up TestProcessManagement")
        self.registry = ProcessRegistry()
        self.test_result = None
        
        # Create directory for test files
        self.test_dir = tempfile.mkdtemp()
        
        # Keep track of created processes for cleanup
        self._test_processes = []

    def tearDown(self):
        """Clean up test environment"""
        # Clean up any remaining test processes
        for proc in self._test_processes:
            try:
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=1)
                    if proc.is_alive():
                        proc.kill()
            except Exception as e:
                logging.warning(f"Failed to clean up process: {e}")
                
        # Clean up test directory
        try:
            shutil.rmtree(self.test_dir)
        except Exception as e:
            logging.warning(f"Failed to clean up test directory: {e}")

    def test_process_registration(self):
        """Test process registration and tracking"""
        self.test_result = TestResult(
            "process-reg",
            "Process Management",
            "Registration",
            "Process Registration"
        )
        
        try:
            # Create and register processes
            processes = [self._create_dummy_process() for _ in range(3)]
            
            for proc in processes:
                proc.start()
                self.registry.register_process(proc)
            
            # Verify registration
            self.assertEqual(
                self.registry.active_process_count,
                len(processes),
                "Not all processes were registered"
            )
            
            # Verify process tracking
            for proc in processes:
                proc.join()
                self.registry.unregister_process(proc)
                
            self.assertEqual(
                self.registry.active_process_count,
                0,
                "Not all processes were unregistered"
            )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_concurrent_registration(self):
        """Test concurrent process registration"""
        self.test_result = TestResult(
            "process-concurrent",
            "Process Management",
            "Concurrency",
            "Concurrent Registration"
        )
        
        try:
            import threading
            
            # Create processes to register
            processes = [self._create_dummy_process() for _ in range(5)]
            register_event = threading.Event()
            
            # Create threads that will register processes concurrently
            def register_process(proc):
                register_event.wait()
                proc.start()
                self.registry.register_process(proc)
                
            threads = [
                threading.Thread(target=register_process, args=(proc,))
                for proc in processes
            ]
            
            # Start threads and trigger concurrent registration
            for thread in threads:
                thread.start()
            register_event.set()
            
            # Wait for threads to complete
            for thread in threads:
                thread.join()
                
            # Verify all processes were registered
            self.assertEqual(
                self.registry.active_process_count,
                len(processes)
            )
            
            # Clean up
            self.registry.cleanup(timeout=1)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_cleanup_handling(self):
        """Test process cleanup functionality"""
        self.test_result = TestResult(
            "process-cleanup",
            "Process Management",
            "Cleanup",
            "Process Cleanup"
        )
        
        try:
            # Create mix of normal and long-running processes
            processes = [
                self._create_dummy_process(0.5),
                self._create_dummy_process(1.0),
                self._create_stubborn_process()
            ]
            
            # Start and register processes
            for proc in processes:
                proc.start()
                self.registry.register_process(proc)
            
            # Verify initial state
            self.assertEqual(self.registry.active_process_count, 3)
            
            # Test cleanup with timeout
            start_time = time.time()
            self.registry.cleanup(timeout=2)
            cleanup_duration = time.time() - start_time
            
            # Verify cleanup completed within timeout
            self.assertLess(
                cleanup_duration,
                3,
                "Cleanup took longer than expected"
            )
            
            # Verify all processes were terminated
            self.assertEqual(
                self.registry.active_process_count,
                0,
                "Not all processes were cleaned up"
            )
            
            # Verify process states
            for proc in processes:
                self.assertFalse(
                    proc.is_alive(),
                    "Process still running after cleanup"
                )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_timeout_handling(self):
        """Test process timeout handling"""
        self.test_result = TestResult(
            "process-timeout",
            "Process Management",
            "Timeout",
            "Process Timeout"
        )
        
        try:
            # Create a stubborn process
            process = self._create_stubborn_process()
            process.start()
            self.registry.register_process(process)
            
            # Verify process is running
            self.assertTrue(process.is_alive())
            self.assertEqual(self.registry.active_process_count, 1)
            
            # Attempt cleanup with short timeout
            start_time = time.time()
            self.registry.cleanup(timeout=1)
            cleanup_duration = time.time() - start_time
            
            # Verify timeout was respected
            self.assertLess(cleanup_duration, 2)
            
            # Verify process was forcefully terminated
            self.assertFalse(process.is_alive())
            self.assertEqual(self.registry.active_process_count, 0)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise
            
    def _create_dummy_process(self, duration=1):
        """Create a dummy process that runs for specified duration"""
        def dummy_worker(duration):
            time.sleep(duration)
            
        proc = Process(target=dummy_worker, args=(duration,))
        self._test_processes.append(proc)
        return proc
        
    def _create_stubborn_process(self):
        """Create a process that ignores normal termination signals"""
        def stubborn_worker():
            try:
                while True:
                    time.sleep(0.1)
            except Exception:
                # Ignore any exceptions to simulate stubborn process
                while True:
                    time.sleep(0.1)
                    
        proc = Process(target=stubborn_worker)
        self._test_processes.append(proc)
        return proc

class TestNetworkOperations(NonQtTestCase):
    """Test suite for network operations"""

    def setUp(self):
        """Set up test environment"""
        # Create test directory
        self.test_dir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.test_dir, 'test_settings.cfg')
        
        # Create test settings
        self.test_settings = {
            'API_KEY': 'test_key',
            'AGENT_ID': 'test_agent',
            'API_URL': 'https://api.test.com'
        }
        
        # Write test settings
        with open(self.settings_path, 'w') as f:
            for key, value in self.test_settings.items():
                f.write(f"{key}: {value}\n")
        
        # Set up test credentials
        self.test_credentials = {
            'email': 'test@example.com',
            'password': 'test_password'
        }
        
        # Set up network mock
        self.requests_mock = patch('network_utils.requests').start()
        
        # Initialize test tracking
        self.test_result = None

    def tearDown(self):
        """Clean up test environment"""
        # Stop request mocking
        patch.stopall()
        
        # Remove test directory
        try:
            shutil.rmtree(self.test_dir)
        except Exception as e:
            logging.warning(f"Failed to clean up test directory: {e}")

    def test_connection_handling(self):
        """Test network connection handling"""
        self.test_result = TestResult(
            "network-conn",
            "Network Operations",
            "Connection Handling",
            "Connection Handling"
        )
        
        try:
            # Test successful connection
            self.requests_mock.post.return_value.ok = True
            self.requests_mock.post.return_value.json.return_value = {
                'success': True,
                'data': {
                    'access_token': 'test_token',
                    'user_info': {'email': self.test_credentials['email']}
                }
            }
            
            response = network_utils.authenticate_user(
                self.test_credentials['email'],
                self.test_credentials['password'],
                self.settings_path
            )
            
            self.assertTrue(response['success'])
            self.assertEqual(
                response['data']['user_info']['email'],
                self.test_credentials['email']
            )
            
            # Test connection error
            self.requests_mock.post.side_effect = requests.ConnectionError()
            
            with self.assertRaises(ConnectionError):
                network_utils.authenticate_user(
                    self.test_credentials['email'],
                    self.test_credentials['password'],
                    self.settings_path
                )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_error_handling(self):
        """Test API error handling"""
        self.test_result = TestResult(
            "network-errors",
            "Network Operations",
            "Error Handling",
            "API Error Handling"
        )
        
        try:
            # Test server error response
            self.requests_mock.post.return_value.ok = False
            self.requests_mock.post.return_value.status_code = 500
            self.requests_mock.post.return_value.json.return_value = {
                'success': False,
                'error': 'Internal server error'
            }
            
            response = network_utils.authenticate_user(
                self.test_credentials['email'],
                self.test_credentials['password'],
                self.settings_path
            )
            
            self.assertFalse(response['success'])
            self.assertIn('error', response)
            
            # Test malformed response
            self.requests_mock.post.return_value.ok = True
            self.requests_mock.post.return_value.json.side_effect = ValueError()
            
            response = network_utils.authenticate_user(
                self.test_credentials['email'],
                self.test_credentials['password'],
                self.settings_path
            )
            
            self.assertFalse(response['success'])
            self.assertIn('error', response)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_retry_mechanism(self):
        """Test network retry mechanism"""
        self.test_result = TestResult(
            "network-retry",
            "Network Operations",
            "Retry Mechanism",
            "Retry Mechanism"
        )
        
        try:
            # Set up mock to fail twice then succeed
            self.requests_mock.post.side_effect = [
                requests.ConnectionError(),
                requests.ConnectionError(),
                Mock(
                    ok=True,
                    json=lambda: {
                        'success': True,
                        'data': {
                            'access_token': 'test_token',
                            'user_info': {'email': self.test_credentials['email']}
                        }
                    }
                )
            ]
            
            # Attempt authentication
            response = network_utils.authenticate_user(
                self.test_credentials['email'],
                self.test_credentials['password'],
                self.settings_path,
                max_retries=3,
                retry_delay=0.1
            )
            
            # Verify success after retries
            self.assertTrue(response['success'])
            self.assertEqual(self.requests_mock.post.call_count, 3)
            
            # Test max retries exceeded
            self.requests_mock.post.reset_mock()
            self.requests_mock.post.side_effect = requests.ConnectionError()
            
            with self.assertRaises(ConnectionError):
                network_utils.authenticate_user(
                    self.test_credentials['email'],
                    self.test_credentials['password'],
                    self.settings_path,
                    max_retries=2,
                    retry_delay=0.1
                )
            
            self.assertEqual(self.requests_mock.post.call_count, 2)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_timeout_handling(self):
        """Test network timeout handling"""
        self.test_result = TestResult(
            "network-timeout",
            "Network Operations",
            "Timeout Handling",
            "Timeout Handling"
        )
        
        try:
            # Test request timeout
            self.requests_mock.post.side_effect = requests.Timeout()
            
            with self.assertRaises(requests.Timeout):
                network_utils.authenticate_user(
                    self.test_credentials['email'],
                    self.test_credentials['password'],
                    self.settings_path,
                    timeout=1
                )
            
            # Verify timeout was respected
            self.requests_mock.post.assert_called_with(
                ANY,  # URL
                json=ANY,
                headers=ANY,
                timeout=1
            )
            
            # Test custom timeout value
            self.requests_mock.post.reset_mock()
            self.requests_mock.post.side_effect = requests.Timeout()
            
            with self.assertRaises(requests.Timeout):
                network_utils.authenticate_user(
                    self.test_credentials['email'],
                    self.test_credentials['password'],
                    self.settings_path,
                    timeout=5
                )
            
            self.requests_mock.post.assert_called_with(
                ANY,  # URL
                json=ANY,
                headers=ANY,
                timeout=5
            )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

class TestEdgeCases(QtTestCase):
    """Test suite for edge cases and boundary conditions"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.theme_manager = ThemeManager()
        self.settings_path = os.path.join(self.temp_dir, 'settings.cfg')
        
        # Initialize test files
        self.zero_byte_file = os.path.join(self.temp_dir, 'zero.txt')
        self.large_file = os.path.join(self.temp_dir, 'large.txt')
        self.special_chars_file = os.path.join(self.temp_dir, 'special_※〒☎.txt')
        
        # Create test files
        open(self.zero_byte_file, 'w').close()  # 0 byte file
        with open(self.large_file, 'wb') as f:
            f.write(os.urandom(1024 * 1024 * 100))  # 100MB file
        with open(self.special_chars_file, 'w') as f:
            f.write('test')

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_zero_byte_handling(self):
        """Test handling of zero-byte files"""
        self.test_result = TestResult(
            "edge-zero-byte",
            "Edge Cases",
            "Zero Byte Files",
            "Zero Byte File Handling"
        )
        
        try:
            # Test backup of zero-byte file
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.return_value = True
                
                op = BackgroundOperation(
                    'backup',
                    self.zero_byte_file,
                    {'API_KEY': 'test', 'AGENT_ID': 'test'}
                )
                op.start()
                
                result = self._wait_for_completion(op)
                self.assertEqual(result['success_count'], 1)
                
            # Test restore of zero-byte file
            with patch('restore_utils.restore_file') as mock_restore:
                mock_restore.return_value = True
                
                op = BackgroundOperation(
                    'restore',
                    self.zero_byte_file,
                    {'API_KEY': 'test', 'AGENT_ID': 'test'}
                )
                op.start()
                
                result = self._wait_for_completion(op)
                self.assertEqual(result['success_count'], 1)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_large_file_handling(self):
        """Test handling of large files"""
        self.test_result = TestResult(
            "edge-large-file",
            "Edge Cases",
            "Large Files",
            "Large File Handling"
        )
        
        try:
            # Test backup with progress tracking
            progress_updates = []
            
            def track_progress(progress):
                progress_updates.append(progress)
            
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.return_value = True
                
                op = BackgroundOperation(
                    'backup',
                    self.large_file,
                    {'API_KEY': 'test', 'AGENT_ID': 'test'}
                )
                op.start()
                
                result = self._wait_for_completion(op)
                self.assertEqual(result['success_count'], 1)
                
                # Verify chunked upload
                self.assertGreater(len(progress_updates), 1)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_special_characters(self):
        """Test handling of special characters in filenames"""
        self.test_result = TestResult(
            "edge-special-chars",
            "Edge Cases",
            "Special Characters",
            "Special Character Handling"
        )
        
        try:
            # Test in file explorer
            explorer = FileExplorerPanel(
                self.temp_dir,
                self.theme_manager,
                self.settings_path
            )
            
            # Find special character file
            local_tree = explorer.local_tree
            special_file_item = self._find_file_item(
                local_tree,
                os.path.basename(self.special_chars_file)
            )
            
            self.assertIsNotNone(special_file_item)
            
            # Test backup operation
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.return_value = True
                
                op = BackgroundOperation(
                    'backup',
                    self.special_chars_file,
                    {'API_KEY': 'test', 'AGENT_ID': 'test'}
                )
                op.start()
                
                result = self._wait_for_completion(op)
                self.assertEqual(result['success_count'], 1)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_concurrent_operations(self):
        """Test handling of concurrent operations"""
        self.test_result = TestResult(
            "edge-concurrent",
            "Edge Cases",
            "Concurrent Operations",
            "Concurrent Operation Handling"
        )
        
        try:
            # Start multiple operations
            operations = []
            for i in range(3):
                file_path = os.path.join(self.temp_dir, f'test{i}.txt')
                with open(file_path, 'w') as f:
                    f.write('test')
                    
                op = BackgroundOperation(
                    'backup',
                    file_path,
                    {'API_KEY': 'test', 'AGENT_ID': 'test'}
                )
                operations.append(op)
                op.start()
            
            # Wait for all completions
            results = []
            for op in operations:
                results.append(self._wait_for_completion(op))
            
            # Verify all completed successfully
            self.assertTrue(all(r['success_count'] == 1 for r in results))
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_resource_limits(self):
        """Test handling of resource limitations"""
        self.test_result = TestResult(
            "edge-resources",
            "Edge Cases",
            "Resource Limits",
            "Resource Limitation Handling"
        )
        
        try:
            # Test memory-constrained operation
            with patch('psutil.virtual_memory') as mock_memory:
                # Simulate low memory
                mock_memory.return_value.available = 1024  # 1KB available
                
                op = BackgroundOperation(
                    'backup',
                    self.large_file,
                    {'API_KEY': 'test', 'AGENT_ID': 'test'}
                )
                op.start()
                
                result = self._wait_for_completion(op)
                self.assertEqual(result['fail_count'], 1)
                self.assertIn('insufficient memory', result.get('error', '').lower())
            
            # Test disk space constraints
            with patch('shutil.disk_usage') as mock_disk:
                # Simulate low disk space
                mock_disk.return_value = (100 * 1024, 99 * 1024, 1024)  # 1KB free
                
                op = BackgroundOperation(
                    'restore',
                    self.large_file,
                    {'API_KEY': 'test', 'AGENT_ID': 'test'}
                )
                op.start()
                
                result = self._wait_for_completion(op)
                self.assertEqual(result['fail_count'], 1)
                self.assertIn('insufficient disk space', result.get('error', '').lower())
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_invalid_states(self):
        """Test handling of invalid application states"""
        self.test_result = TestResult(
            "edge-invalid",
            "Edge Cases",
            "Invalid States",
            "Invalid State Handling"
        )
        
        try:
            # Test invalid settings
            explorer = FileExplorerPanel(
                self.temp_dir,
                self.theme_manager,
                "nonexistent_settings.cfg"
            )
            
            # Should handle missing settings gracefully
            self.assertFalse(explorer.progress_widget.isVisible())
            
            # Test corrupted theme
            with patch.dict(self.theme_manager.themes, {'Corrupted': {}}):
                self.theme_manager.set_theme('Corrupted')
                # Should fall back to default theme
                self.assertNotEqual(
                    explorer.palette().color(explorer.backgroundRole()),
                    QColor(0, 0, 0, 0)
                )
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def _wait_for_completion(self, operation):
        """Helper to wait for operation completion"""
        while True:
            try:
                update = operation.queue.get_nowait()
                if update.get('type') == 'operation_complete':
                    return update
            except Empty:
                continue

    def _find_file_item(self, tree_view, filename):
        """Helper to find file item in tree"""
        model = tree_view.model()
        
        def search(parent):
            for row in range(model.rowCount(parent)):
                index = model.index(row, 0, parent)
                if model.data(index) == filename:
                    return model.itemFromIndex(index)
                if model.hasChildren(index):
                    result = search(index)
                    if result:
                        return result
            return None
            
        return search(QModelIndex())

class TestPerformance(QtTestCase):
    """Test suite for performance measurements"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.theme_manager = ThemeManager()
        self.settings_path = os.path.join(self.temp_dir, 'settings.cfg')
        
        # Create test file structure
        self.create_test_files()
        
        # Performance thresholds
        self.thresholds = {
            'file_load': 1.0,      # 1 second
            'search': 2.0,         # 2 seconds
            'backup': 5.0,         # 5 seconds per file
            'restore': 5.0,        # 5 seconds per file
            'ui_response': 0.1     # 100ms
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def create_test_files(self):
        """Create test file structure"""
        # Create nested directory structure
        for i in range(5):
            dir_path = os.path.join(self.temp_dir, f'dir_{i}')
            os.makedirs(dir_path)
            
            # Create files of different sizes
            for j in range(20):
                file_path = os.path.join(dir_path, f'file_{j}.txt')
                size = 1024 * (2 ** j)  # Exponentially increasing sizes
                with open(file_path, 'wb') as f:
                    f.write(os.urandom(min(size, 1024 * 1024)))  # Cap at 1MB

    def test_file_load_performance(self):
        """Test file loading performance"""
        self.test_result = TestResult(
            "perf-file-load",
            "Performance",
            "File Loading",
            "File Load Performance"
        )
        
        try:
            explorer = FileExplorerPanel(
                self.temp_dir,
                self.theme_manager,
                self.settings_path
            )
            
            # Measure directory load time
            start_time = time.time()
            explorer.local_model.load_directory(self.temp_dir)
            load_time = time.time() - start_time
            
            self.assertLess(load_time, self.thresholds['file_load'])
            
            # Measure memory usage
            process = psutil.Process()
            mem_info = process.memory_info()
            self.assertLess(mem_info.rss / (1024 * 1024), 200)  # Less than 200MB
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_search_performance(self):
        """Test search operation performance"""
        self.test_result = TestResult(
            "perf-search",
            "Performance",
            "Search Operations",
            "Search Performance"
        )
        
        try:
            explorer = FileExplorerPanel(
                self.temp_dir,
                self.theme_manager,
                self.settings_path
            )
            
            # Perform search operation
            start_time = time.time()
            results, truncated, stats = explorer.filesystem_index.search("file")
            search_time = time.time() - start_time
            
            self.assertLess(search_time, self.thresholds['search'])
            self.assertGreater(len(results), 0)
            
            # Test search response time
            response_times = []
            for i in range(10):
                start = time.time()
                explorer.filesystem_index.search(f"file_{i}")
                response_times.append(time.time() - start)
            
            avg_response = sum(response_times) / len(response_times)
            self.assertLess(avg_response, self.thresholds['search'])
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_backup_performance(self):
        """Test backup operation performance"""
        self.test_result = TestResult(
            "perf-backup",
            "Performance",
            "Backup Operations",
            "Backup Performance"
        )
        
        try:
            # Test single large file backup
            large_file = os.path.join(self.temp_dir, 'large_test.dat')
            with open(large_file, 'wb') as f:
                f.write(os.urandom(50 * 1024 * 1024))  # 50MB file
            
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.return_value = True
                
                start_time = time.time()
                op = BackgroundOperation(
                    'backup',
                    large_file,
                    {'API_KEY': 'test', 'AGENT_ID': 'test'}
                )
                op.start()
                result = self._wait_for_completion(op)
                backup_time = time.time() - start_time
                
                self.assertLess(backup_time, self.thresholds['backup'])
                self.assertEqual(result['success_count'], 1)
            
            # Test batch backup performance
            test_files = []
            for i in range(10):
                file_path = os.path.join(self.temp_dir, f'batch_test_{i}.dat')
                with open(file_path, 'wb') as f:
                    f.write(os.urandom(1024 * 1024))  # 1MB each
                test_files.append(file_path)
            
            with patch('backup_utils.process_file') as mock_backup:
                mock_backup.return_value = True
                
                start_time = time.time()
                op = BackgroundOperation(
                    'backup',
                    test_files,
                    {'API_KEY': 'test', 'AGENT_ID': 'test'}
                )
                op.start()
                result = self._wait_for_completion(op)
                batch_time = time.time() - start_time
                
                # Average time per file should be within threshold
                avg_time = batch_time / len(test_files)
                self.assertLess(avg_time, self.thresholds['backup'])
                self.assertEqual(result['success_count'], len(test_files))
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_restore_performance(self):
        """Test restore operation performance"""
        self.test_result = TestResult(
            "perf-restore",
            "Performance",
            "Restore Operations",
            "Restore Performance"
        )
        
        try:
            # Test single large file restore
            file_path = '/test/large_file.dat'
            
            with patch('restore_utils.restore_file') as mock_restore:
                mock_restore.return_value = True
                
                start_time = time.time()
                op = BackgroundOperation(
                    'restore',
                    file_path,
                    {'API_KEY': 'test', 'AGENT_ID': 'test'}
                )
                op.start()
                result = self._wait_for_completion(op)
                restore_time = time.time() - start_time
                
                self.assertLess(restore_time, self.thresholds['restore'])
                self.assertEqual(result['success_count'], 1)
            
            # Test batch restore performance
            test_paths = [f'/test/batch_{i}.dat' for i in range(10)]
            
            with patch('restore_utils.restore_file') as mock_restore:
                mock_restore.return_value = True
                
                start_time = time.time()
                op = BackgroundOperation(
                    'restore',
                    test_paths,
                    {'API_KEY': 'test', 'AGENT_ID': 'test'}
                )
                op.start()
                result = self._wait_for_completion(op)
                batch_time = time.time() - start_time
                
                # Average time per file should be within threshold
                avg_time = batch_time / len(test_paths)
                self.assertLess(avg_time, self.thresholds['restore'])
                self.assertEqual(result['success_count'], len(test_paths))
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_ui_performance(self):
        """Test UI responsiveness"""
        self.test_result = TestResult(
            "perf-ui",
            "Performance",
            "UI Responsiveness",
            "UI Performance"
        )
        
        try:
            explorer = FileExplorerPanel(
                self.temp_dir,
                self.theme_manager,
                self.settings_path
            )
            
            # Test tree view expansion time
            local_tree = explorer.local_tree
            model = local_tree.model()
            root_index = model.index(0, 0)
            
            start_time = time.time()
            local_tree.expand(root_index)
            expand_time = time.time() - start_time
            
            self.assertLess(expand_time, self.thresholds['ui_response'])
            
            # Test search box responsiveness
            response_times = []
            search_box = explorer.local_search
            
            for i in range(5):
                start_time = time.time()
                QTest.keyClicks(search_box, f"test{i}")
                QTest.keyClick(search_box, Qt.Key_Return)
                response_time = time.time() - start_time
                response_times.append(response_time)
                search_box.clear()
            
            avg_response = sum(response_times) / len(response_times)
            self.assertLess(avg_response, self.thresholds['ui_response'])
            
            # Test theme switching performance
            start_time = time.time()
            explorer.theme_manager.set_theme("Light")
            theme_time = time.time() - start_time
            
            self.assertLess(theme_time, self.thresholds['ui_response'])
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def test_memory_usage(self):
        """Test memory usage under load"""
        self.test_result = TestResult(
            "perf-memory",
            "Performance",
            "Memory Usage",
            "Memory Performance"
        )
        
        try:
            # Monitor base memory usage
            process = psutil.Process()
            base_memory = process.memory_info().rss
            
            # Create large file structure
            for i in range(100):
                dir_path = os.path.join(self.temp_dir, f'mem_test_{i}')
                os.makedirs(dir_path)
                for j in range(100):
                    with open(os.path.join(dir_path, f'file_{j}.txt'), 'w') as f:
                        f.write('test' * 100)
            
            explorer = FileExplorerPanel(
                self.temp_dir,
                self.theme_manager,
                self.settings_path
            )
            
            # Load directory structure
            explorer.local_model.load_directory(self.temp_dir)
            
            # Check memory growth
            current_memory = process.memory_info().rss
            memory_growth = (current_memory - base_memory) / (1024 * 1024)  # MB
            
            # Should use less than 200MB additional memory
            self.assertLess(memory_growth, 200)
            
            # Test memory cleanup
            explorer.cleanup()
            final_memory = process.memory_info().rss
            
            # Should release most memory
            self.assertLess(final_memory - base_memory, base_memory * 0.5)
            
            self.test_result.complete('pass')
            
        except Exception as e:
            self.test_result.complete('fail', str(e), traceback.format_exc())
            raise

    def _wait_for_completion(self, operation):
        """Helper to wait for operation completion"""
        while True:
            try:
                update = operation.queue.get_nowait()
                if update.get('type') == 'operation_complete':
                    return update
            except Empty:
                continue

def create_test_suite():
    """Create organized test suite with proper initialization"""
    suite = unittest.TestSuite()
    
    # Non-Qt tests (run first)
    non_qt_tests = [
        TestSecurity,
        TestErrorLogging,
        TestNetworkOperations,
        TestHistoryTracking,
        TestProcessManagement
    ]
    
    # Qt-dependent tests
    qt_tests = [
        TestTokenManagement,
        TestUserAuthentication,
        TestAppInitialization,
        TestSettingsManagement,
        TestThemeSystem,
        TestLocalFileSystem,
        TestRemoteFileSystem,
        TestFileIndexing,
        TestBackupOperations,
        TestRestoreOperations,
        TestProgressTracking,
        TestFileExplorer,
        TestProgressDisplay,
        TestThemeIntegration,
        TestScheduleManagement,
        TestEdgeCases,
        TestPerformance
    ]
    
    # Add non-Qt tests
    for test_class in non_qt_tests:
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(test_class))
    
    # Add Qt tests
    for test_class in qt_tests:
        # Update test class to inherit from QtTestCase
        if not issubclass(test_class, QtTestCase):
            test_class.__bases__ = (QtTestCase,)
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(test_class))
    
    return suite

if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        filename='%s_%s.log' % ("sc_unit_tests", datetime.now().strftime("%Y-%m-%d")),
        filemode='a',
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.DEBUG,
        force=True
    )
    
    try:
        # Run test suite
        suite = create_test_suite()
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        
        # Handle test results
        if not result.wasSuccessful():
            sys.exit(1)
            
    except Exception as e:
        logging.error(f"Test suite failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Ensure Qt application is closed
        app = QApplication.instance()
        if app:
            app.quit()