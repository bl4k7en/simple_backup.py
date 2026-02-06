import pwnagotchi.plugins as plugins
import logging
import os
import subprocess
import time
import tarfile
from datetime import datetime
import threading

class SimpleBackup(plugins.Plugin):
    __author__ = 'bl4k7en'
    __version__ = '1.1'
    __license__ = 'GPL3'
    __description__ = 'Simple and reliable backup plugin for Pwnagotchi'

    def __init__(self):
        self.ready = False
        self.running = False
        self.last_backup = 0
        self.timer_thread = None
        self.stop_timer = False

    def on_loaded(self):
        """Initialize plugin on load"""
        # Set defaults if not configured
        self.options.setdefault('enabled', True)
        self.options.setdefault('interval_hours', 1)
        self.options.setdefault('backup_path', '/home/pi/backups')
        self.options.setdefault('max_backups', 5)
        self.options.setdefault('compress', True)
        self.options.setdefault('backup_on_boot', True)
        
        # Files/directories to backup
        self.backup_items = [
            '/etc/pwnagotchi/config.toml',
            '/etc/pwnagotchi/fingerprint',
            '/etc/pwnagotchi/id_rsa',
            '/etc/pwnagotchi/id_rsa.pub',
            '/etc/ssh/sshd_config',
            '/etc/ssh/ssh_config',
            '/home/pi/.bashrc',
            '/home/pi/.profile',
            '/home/pi/.wpa_sec_uploads',
            '/home/pi/handshakes',
            '/root/.bashrc',
            '/root/.profile',
            '/root/client_secrets.json',
            '/root/settings.yaml',
            '/root/.ssh',
            '/root/peers',
            '/usr/local/share/pwnagotchi/custom-plugins'
        ]
        
        self.ready = True
        logging.info("[BACKUP] Plugin loaded successfully")
        logging.info(f"[BACKUP] Interval: {self.options['interval_hours']} hours")
        logging.info(f"[BACKUP] Location: {self.options['backup_path']}")
        logging.info(f"[BACKUP] Max backups to keep: {self.options['max_backups']}")
        
        # Set initial time BEFORE starting threads
        self.last_backup = time.time()
        
        # Trigger backup on boot if enabled
        if self.options['backup_on_boot']:
            logging.info("[BACKUP] Scheduling boot backup...")
            # Delay boot backup by 30 seconds to let system stabilize
            threading.Timer(30.0, self._create_backup).start()
        
        # Start background timer for regular backups
        self._start_backup_timer()

    def _ensure_backup_dir(self):
        """Create backup directory if it doesn't exist"""
        backup_path = self.options['backup_path']
        try:
            if not os.path.exists(backup_path):
                os.makedirs(backup_path)
                logging.info(f"[BACKUP] Created backup directory: {backup_path}")
            return True
        except Exception as e:
            logging.error(f"[BACKUP] Failed to create backup directory: {e}")
            return False

    def _get_existing_files(self):
        """Get list of files/dirs that actually exist"""
        existing = []
        for item in self.backup_items:
            if os.path.exists(item):
                existing.append(item)
            else:
                logging.debug(f"[BACKUP] Skipping non-existent: {item}")
        return existing

    def _create_backup(self):
        """Create the actual backup file"""
        if self.running:
            logging.info("[BACKUP] Backup already running, skipping")
            return False

        self.running = True
        
        try:
            # Ensure backup directory exists
            if not self._ensure_backup_dir():
                return False

            # Get files that exist
            files_to_backup = self._get_existing_files()
            if not files_to_backup:
                logging.error("[BACKUP] No files found to backup!")
                return False

            # Create backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            hostname = os.uname().nodename
            
            if self.options['compress']:
                backup_file = os.path.join(
                    self.options['backup_path'],
                    f"{hostname}_backup_{timestamp}.tar.gz"
                )
                compression = 'gz'
            else:
                backup_file = os.path.join(
                    self.options['backup_path'],
                    f"{hostname}_backup_{timestamp}.tar"
                )
                compression = ''

            logging.info(f"[BACKUP] Creating backup: {backup_file}")
            logging.info(f"[BACKUP] Backing up {len(files_to_backup)} items...")

            # Create tar archive
            with tarfile.open(backup_file, f'w:{compression}') as tar:
                for item in files_to_backup:
                    try:
                        # Use arcname to preserve directory structure
                        tar.add(item, arcname=item)
                        logging.debug(f"[BACKUP] Added: {item}")
                    except Exception as e:
                        logging.warning(f"[BACKUP] Failed to add {item}: {e}")

            # Verify backup was created
            if os.path.exists(backup_file):
                size_mb = os.path.getsize(backup_file) / (1024 * 1024)
                logging.info(f"[BACKUP] Backup successful! Size: {size_mb:.2f} MB")
                self.last_backup = time.time()
                
                # Cleanup old backups
                self._cleanup_old_backups()
                return True
            else:
                logging.error("[BACKUP] Backup file was not created!")
                return False

        except Exception as e:
            logging.error(f"[BACKUP] Backup failed: {e}")
            return False
        finally:
            self.running = False

    def _cleanup_old_backups(self):
        """Remove old backups if we exceed max_backups - keeps newest first"""
        try:
            backup_path = self.options['backup_path']
            max_backups = self.options['max_backups']
            
            # Get all backup files
            backup_files = []
            for filename in os.listdir(backup_path):
                if filename.endswith('.tar.gz') or filename.endswith('.tar'):
                    filepath = os.path.join(backup_path, filename)
                    backup_files.append((filepath, os.path.getmtime(filepath)))
            
            # Sort by modification time (NEWEST first)
            backup_files.sort(key=lambda x: x[1], reverse=True)
            
            # Delete oldest if we have too many (keep only the newest max_backups)
            if len(backup_files) > max_backups:
                to_delete = len(backup_files) - max_backups
                logging.info(f"[BACKUP] Keeping {max_backups} newest backups, deleting {to_delete} old one(s)")
                
                # Delete from the end of the list (oldest files)
                for i in range(max_backups, len(backup_files)):
                    filepath = backup_files[i][0]
                    try:
                        os.remove(filepath)
                        logging.info(f"[BACKUP] Deleted old backup: {os.path.basename(filepath)}")
                    except Exception as e:
                        logging.error(f"[BACKUP] Failed to delete {filepath}: {e}")
                        
        except Exception as e:
            logging.error(f"[BACKUP] Cleanup error: {e}")

    def _should_backup(self):
        """Check if backup is due based on interval"""
        if self.last_backup == 0:
            return False  # Don't backup immediately on startup
        
        interval_seconds = self.options['interval_hours'] * 3600
        elapsed = time.time() - self.last_backup
        
        return elapsed >= interval_seconds
    
    def _start_backup_timer(self):
        """Start background timer thread for regular backups"""
        def backup_loop():
            logging.info("[BACKUP] Background timer started")
            # Wait 60 seconds before first check to let system stabilize
            time.sleep(60)
            
            while not self.stop_timer:
                try:
                    if self._should_backup():
                        logging.info("[BACKUP] Timer triggered backup")
                        self._create_backup()
                    
                    # Check every 5 minutes if backup is due
                    time.sleep(300)
                except Exception as e:
                    logging.error(f"[BACKUP] Timer error: {e}")
                    time.sleep(60)
        
        self.timer_thread = threading.Thread(target=backup_loop, daemon=True)
        self.timer_thread.start()
    
    def on_unload(self, ui):
        """Stop timer when plugin is unloaded"""
        self.stop_timer = True
        if self.timer_thread:
            self.timer_thread.join(timeout=5)

    def on_webhook(self, path, request):
        """Manual backup trigger via webhook"""
        if path == 'backup':
            logging.info("[BACKUP] Manual backup triggered via webhook")
            success = self._create_backup()
            return "Backup completed successfully!" if success else "Backup failed!"
