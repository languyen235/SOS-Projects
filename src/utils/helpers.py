import logging
import subprocess
import shlex
import os
import time
import sys
from functools import wraps
from pathlib import Path
from typing import List, Callable, TextIO

# Add the parent directory to modules
sys.path.append('/opt/cliosoft/monitoring')

from src.config.settings import LOG_FORMAT, DDM_CONTACTS, SENDER
from src.modules.utils import *
logger = logging.getLogger(__name__)

#-------------
def site_code():
    """Returns this site code"""
    import socket
    return socket.getfqdn().split('.')[1]


def setup_logging(log_file: Path) -> logging.Logger:
    """Configure and return a logger instance.
    Returns:
        logging.Logger: Configured logger instance
    """
    # log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    # log_format = '[%(asctime)s] [%(name)s] [%(funcName)s] [%(levelname)s] %(message)s'
    logging.basicConfig(
        # level=log_level,
        level = os.environ.get('LOG_LEVEL', 'INFO').upper(),
        format=LOG_FORMAT,
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, mode='w'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def run_shell_cmd(cmd: str, timeout: int, is_shell: bool = False)-> List[str] | None:
    """
    Run a shell command and return its output as a list of strings.
    Args:
        cmd: The command to run
        timeout: Command timeout in seconds
        is_shell: Whether to run the command through the shell

    Returns:
        List of output lines or None if command failed
    """
    try:
        result = subprocess.run(
            cmd if is_shell else shlex.split(cmd),
            shell=is_shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=True
        )

        if result.stderr:
            # logger.error(f"Command [{cmd}] failed: {result.stderr}")
            logger.error("Command [%s] failed: %s", cmd, result.stderr)
            return None

        delimiter = ',' if result.stdout.count(',') == 1 else '\n'
        return [line.strip() for line in result.stdout.rstrip('\n').split(delimiter) if line.strip()]

    except subprocess.TimeoutExpired:
        logger.critical("%s timed out after %s seconds", cmd, timeout, exc_info=True)
    except subprocess.CalledProcessError as proc_error:
        logger.critical("Command [%s] failed with status %d: %s",
                       cmd, proc_error.returncode, proc_error.stderr, exc_info=True)

    return None


def file_older_than(file_path: str | os.PathLike, num_day: int=1):
    """Return true if file is older than number of days"""
    time_difference = time.time() - os.path.getmtime(file_path)
    seconds_in_a_day = 86400  # 24 * 60 * 60

    if time_difference > (seconds_in_a_day * num_day):
        return True
    else:
        return False


def create_file_decorator(func: Callable) -> Callable:
    """
    Decorator to handle data file creation with automatic refresh.
    Delete and re-create file if file is older than a day
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        ifile = args[0]
        try:
            # If file exists and is older than 1 day, remove it
            if ifile.exists() and file_older_than(ifile, num_day=1):
                logger.info('Data file is more than a day old. Removing old file...')
                ifile.unlink()

            # If file doesn't exist (either didn't exist or was just removed)
            if not ifile.exists():
                logger.info('Creating new data file...')
                return func(*args, **kwargs)

            logger.debug('Using existing data file (less than a day old)')
            return None

        except OSError as file_error:
            logger.error("Error handling data file %s: %s", ifile, file_error)
            raise
    return wrapper

@create_file_decorator
def create_disks_file(disk_file: Path) -> None:
    """
    Creates a data file containing paths of primary and cache disks for Cliosoft.
    This function retrieves disk information, filters it, and writes the relevant paths to the specified data file.
    Parameters:
        disk_file (Path): The path where the data file will be created.
    Raises:
        OSError: If there is an error during file creation or writing.
    """
    logger.info('Creating disk file at %s', disk_file)
    found_disks: set[Path] = set()

    def write_disk_path(disk_path: Path, seen_disks: set[Path], file_handle: TextIO) -> None:
        """Helper function to write disk path if not already seen."""
        if disk_path not in seen_disks:
            seen_disks.add(disk_path)
            file_handle.write(f"{disk_path}\n")

    sos_services = get_sos_services()

    try:
        with open(disk_file, 'w', newline='', encoding='utf-8') as file:
            for row in get_sos_disks(sos_services):
                if len(row) > 5:   # Replica server format
                    replica_dir = get_pg_data_parent(Path(row[-1]), depth=5)
                    write_disk_path(replica_dir, found_disks, file)
                    continue

                if  row[-2].lower() == 'local':
                    repo_dir = get_pg_data_parent(Path(row[-1]), depth=5)
                    write_disk_path(repo_dir, found_disks, file)

                cache_dir = get_pg_data_parent(Path(row[-3]), depth=5)
                write_disk_path(cache_dir, found_disks, file)

        # Normalize the paths in the data file
        subprocess.run(
            ["sed", "-i", "s:^/nfs/.*/disks:/nfs/site/disks:g", str(disk_file)],
            check=True
        )

    except OSError as err:
        logger.error("Failed to create data file: %s", err)
        raise


def send_email_alert(subject: str, message: list[str]) -> bool:
    """
    Send email notification to DDM contacts.
    Args:
        subject: Email subject
        message: Email body content
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        send_email(subject, message, DDM_CONTACTS, SENDER)
        return True
    except Exception as error:
        logger.error("Failed to send email: %s", error)
        return False


#-----
__all__ = [ 'site_code', 'setup_logging', 'run_shell_cmd', 'file_older_than', 'create_file_decorator',
            'create_disks_file', 'send_email_alert'
        ]
