#!/opt/cliosoft/monitoring/venv/bin/python3.12

import json
import logging
import re
import shlex
import socket
import subprocess
import argparse
from functools import wraps
from pathlib import Path
from typing import List, Iterator, Tuple, TextIO, Dict, Callable
import os, sys

# Add the parent directory to modules
sys.path.append('/opt/cliosoft/monitoring')
from modules.utils import *

# Constants
LOW_SPACE_THRESHOLD_GB: int = 250  # GBthreshold for low disk size
ADDING_DISK_SIZE_GB: int = 500  # GB value to be add to current disk size
SERVER_CONFIG_LINK = '/opt/cliosoft/latest/SERVERS'
SERVER_CONFIG_PATH = '/nfs/site/disks/sos_adm/share/SERVERS7'
SOS_ADMIN_CMD = "/opt/cliosoft/latest/bin/sosadmin"
SOS_MGR_CMD = "/opt/cliosoft/latest/bin/sosmgr"
COMMAND_TIMEOUT = 30  # seconds
DDM_CONTACTS = ['linh.a.nguyen@intel.com']
SENDER = "linh.a.nguyen@intel.com"
EXCLUDED_SERVICES_FILE = Path('/opt/cliosoft/monitoring/data/excluded_services.txt')
SITES = ['sc','sc1', 'sc4', 'sc8', 'pdx', 'iil', 'png', 'iind', 'altera_sc', 'altera_png', 'vr'] # noqa, ignore=E501
DISK_SIZE_INCREASE_DAYS = 2  # Days to check for recent disk size increases

#----
def setup_logging() -> logging.Logger:
    """Configure and return a logger instance.
    Returns:
        logging.Logger: Configured logger instance
    """
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_format = '[%(asctime)s] [%(name)s] [%(funcName)s] [%(levelname)s] %(message)s'

    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(SosDiskMonitor.log_file, mode='w'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


class SosDiskMonitor:
    """Setup Cliosoft application service"""

    # Class variables
    data_path = Path('/opt/cliosoft/monitoring/data')
    log_path = Path('/opt/cliosoft/monitoring/logs')
    log_file = Path(log_path, 'sos_service_monitoring.log')

    # Ensure required directories exist
    for path in [data_path, log_path]:
        path.mkdir(mode=0o775, parents=True, exist_ok=True)

    def __init__(self, site):
        """Initialize instance attributes and load environment data."""
        self.site = site
        self.server_role = None
        self.web_url = None
        self.site_name = None
        self.data_file = Path(SosDiskMonitor.data_path, f"{self.site.upper()}_cliosoft_disks.txt")
        self.env_data_file = Path(SosDiskMonitor.data_path, f'{self.site.upper()}_sos_env.json')
        self.load_env_data()

    def load_env_data(self):
        """Load environment data from file or initialize new configuration."""
        if self.env_data_file.exists():
            self.load_from_env_data_file()
        else:
            self.initialize_env_variables()
            self.save_env_data()

    @staticmethod
    def logging_debug_decorator(func)-> Callable:
        """ Decorate debug information to be logged"""
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            result = func(self, *args, **kwargs)

            # Log relevant debug information
            log_vars = [
                ("Disk data file", self.data_file),
                ("SOS_SERVERS_DIR", os.environ['SOS_SERVERS_DIR']),
                ("CLIOSOFT_DIR", os.environ['CLIOSOFT_DIR']),
                ("SOS_SERVER_ROLE", os.environ['SOS_SERVER_ROLE']),
                ("EC_ZONE", os.environ['EC_ZONE']),
                ("Site name", self.site_name.rstrip(':')),
                ("Web URL", self.web_url),
            ]
            for name, value in log_vars:
                logger.debug("%s: %s", name, value)

            return result
        return wrapper

    @logging_debug_decorator
    def load_from_env_data_file(self):
        """ Load environment variables from JSON file """
        data: Dict = self.read_from_env_data_file(self.env_data_file)
        self.update_site_variables(data)
        self.update_env_variables(data)

    def update_site_variables(self, data: Dict):
        """Update instance variables from loaded data"""
        self.site_name = data['site_name']
        self.web_url = data['site_url']
        self.server_role = data['server_role']


    @staticmethod
    def update_env_variables(data: Dict):
        """update environment variables from loaded data"""
        os.environ.update({
            'SOS_SERVERS_DIR': data['sos_servers_dir'],
            'CLIOSOFT_DIR': data['sos_cliosoft_dir'],
            'SOS_SERVER_ROLE': data['server_role'],
            'EC_ZONE': data['ec_zone'],
        })

    @logging_debug_decorator
    def initialize_env_variables(self):
        """Initialize SOS environment variables with default values"""
        os.environ['CLIOSOFT_DIR'] = '/opt/cliosoft/latest'
        os.environ['SOS_SERVERS_DIR'] = SosDiskMonitor.get_server_config_path(self.site)
        os.environ['EC_ZONE'] = self.site

        # Determine server role based on servers directory
        if re.search(r'replica$', os.environ['SOS_SERVERS_DIR']):
            os.environ['SOS_SERVER_ROLE'] = 'replica'
        else:
            os.environ['SOS_SERVER_ROLE'] = 'repo'

        self.server_role = os.environ['SOS_SERVER_ROLE']
        self.site_name, self.web_url = SosDiskMonitor.get_sitename_and_url()


    def save_env_data(self):
        """Save environment variables to file"""
        self.write_to_env_data_file(
            self.site_name, self.web_url,
            self.server_role, os.environ['SOS_SERVERS_DIR'],
            os.environ['CLIOSOFT_DIR'], os.environ['EC_ZONE'])


    def write_to_env_data_file(self, *args):
        """Write environment data to JSON file"""
        SITE_INFO_KEYS = ['site_name', 'site_url', 'server_role', 'sos_servers_dir', 'sos_cliosoft_dir', 'ec_zone']
        data = dict(zip(SITE_INFO_KEYS, args[:6]))
        try:
            with open(self.env_data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4) # noqa, ignore=E501
        except IOError as e:
            logger.error("Failed to write environment data file: %s", e)
            raise


    @staticmethod
    def read_from_env_data_file(file_path)-> Dict[str, str]:
        """Load environment variables from JSON file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logger.error("Failed to read environment data file: %s", e)
            raise


    @staticmethod
    def get_sitename_and_url()-> tuple[str, str]:
        """Retrieve site name and URL using sosmgr command."""
        cmd = f"{SOS_MGR_CMD} site get -o csv --url | tail -2 | sed -E '/^$|site,url/d'"
        # return run_sos_cmd_in_subproc(cmd, timeout=TIMEOUT, is_shell=True)
        result = run_sos_cmd_in_subproc(cmd, timeout=COMMAND_TIMEOUT, is_shell=True)
        if not result or len(result) < 2:
            raise ValueError("Failed to get site name and URL")
        return result[0], result[1]


    @staticmethod
    def get_server_config_path(site)-> str:
        """Determine the appropriate server configuration path."""
        real_path = os.path.realpath(SERVER_CONFIG_LINK)
        if re.search(r'(SERVERS8-replica$)', real_path) or site != 'sc':
            return real_path
        return SERVER_CONFIG_PATH


def run_sos_cmd_in_subproc(cmd: str, timeout: int, is_shell: bool = False)-> List[str] | None:
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
    except subprocess.CalledProcessError as e:
        logger.critical("Command [%s] failed with status %d: %s",
                       cmd, e.returncode, e.stderr, exc_info=True)

    return None


def get_sos_services() -> list[str]:
    """
    Get list of SOS services, excluding any that are in the excluded services file.
    Returns:
        List of service names
    Raises:
        ValueError: If no SOS services are found
    """
    logger.info('Querying SOS services')
    sos_cmd = f"{SOS_ADMIN_CMD} list"
    services = run_sos_cmd_in_subproc(sos_cmd, timeout=COMMAND_TIMEOUT)

    if services is None:
        logger.error("No SOS services found")
        raise ValueError('No SOS services found')

    if EXCLUDED_SERVICES_FILE.exists():
        excluded_services = get_excluded_services(EXCLUDED_SERVICES_FILE)
        return [service for service in services if service not in excluded_services]

    return services


def get_sos_disks(services: list[str]) -> Iterator[list[str]]:
    """
    Get disk information for SOS services.
    Args:
        services: List of service names to query
    Yields:
        Lists containing disk information for each service
    Raises:
        ValueError: If no SOS disks are found or server role is unknown
    """
    logger.debug('Services: %s', services)
    logger.info('Querying SOS disks for %d services', len(services))

    server_role = os.environ['SOS_SERVER_ROLE']
    if server_role not in ['replica', 'repo']:
        logger.error("Unknown server role: %s", server_role)
        raise ValueError(f'Unknown server role:  {server_role}')

    # Define commands based on server role
    server_role_commands = {
        'replica': f"{SOS_MGR_CMD} service get -o csv -cpa -ppa -rpa -pcl -rcl -s {','.join(services)}",
        'repo': f"{SOS_MGR_CMD} service get -o csv -cpa -ppa -pcl -s {','.join(services)}",
    }

    sos_get_disks_cmd = server_role_commands.get(server_role)
    lines = run_sos_cmd_in_subproc(sos_get_disks_cmd, timeout=COMMAND_TIMEOUT)
    if not lines:
        error_msg = "No SOS disks found"
        logger.error(error_msg)
        raise ValueError(error_msg)

    for line in filter(None, map(str.strip, lines)):  # Skip empty lines
        if not line.startswith('site'):  # Skip headers
            disk_info = [text.strip() for text in line.split(',')]
            logger.debug("Parsed SOS disk: %s", disk_info)
            yield disk_info


def create_data_file_decorator(func: Callable) -> Callable:
    """
    Decorator to handle data file creation with automatic refresh.
    Delete and re-create file if file is older than a day
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        data_file = args[0]
        try:
            # If file exists and is older than 1 day, remove it
            if data_file.exists() and file_older_than(data_file, day=1):
                logger.info('Data file is more than a day old. Removing old file...')
                data_file.unlink()
            
            # If file doesn't exist (either didn't exist or was just removed)
            if not data_file.exists():
                logger.info('Creating new data file...')
                return func(*args, **kwargs)
            
            logger.debug('Using existing data file (less than a day old)')
            return None
            
        except OSError as e:
            logger.error("Error handling data file %s: %s", data_file, e)
            raise

    return wrapper


@create_data_file_decorator
def create_data_file(data_file: Path) -> None:
    """
    Creates a data file containing paths of primary and cache disks for Cliosoft.
    This function retrieves disk information, filters it, and writes the relevant paths to the specified data file.
    Parameters:
        data_file (Path): The path where the data file will be created.
    Raises:
        OSError: If there is an error during file creation or writing.
    """
    logger.info('Creating data file at %s', data_file)
    found_disks: set[Path] = set()

    def write_disk_path(disk_path: Path, seen_disks: set[Path], file_handle: TextIO) -> None:
        """Helper function to write disk path if not already seen."""
        if disk_path not in seen_disks:
            seen_disks.add(disk_path)
            file_handle.write(f"{disk_path}\n")

    sos_services = get_sos_services()

    try:
        with open(data_file, 'w', newline='', encoding='utf-8') as file:
            for row in get_sos_disks(sos_services):
                if len(row) > 5:   # Replica server format
                    replica_dir = get_parent_dir(Path(row[-1]))
                    write_disk_path(replica_dir, found_disks, file)
                    continue

                if  row[-2].lower() == 'local':
                    repo_dir = get_parent_dir(Path(row[-1]))
                    write_disk_path(repo_dir, found_disks, file)

                cache_dir = get_parent_dir(Path(row[-3]))
                write_disk_path(cache_dir, found_disks, file)

        # Normalize the paths in the data file
        subprocess.run(
            ["sed", "-i", "s:^/nfs/.*/disks:/nfs/site/disks:g", str(data_file)],
            check=True
        )

    except OSError as err:
        logger.error("Failed to create data file: %s", err)
        raise


def handle_low_disk_space(disks: Tuple, adding_size: int) -> None:
    """
    Handle disks with low space by logging warnings and optionally increasing disk size.
    Args:
        disks: List of tuples containing disk info (path, size, used, available)
        adding_size: Size in GB to add to the disk (0 to disable auto-increase)
    """
    for disk_info in disks:
        disk_path, size, used, avail = disk_info
        logger.warning("%s Size: %sGB; Avail: %sGB *** Low disk space",
                      disk_path, size, avail)

        if has_disk_size_been_increased(disk_path, days=DISK_SIZE_INCREASE_DAYS):
            disk_name = disk_path.split('/')[-1]
            logger.warning("Disk %s size has been recently increased. Investigation needed.", disk_name)
        elif adding_size > 0:
            logger.info("Attempting to add %sGB to %s", adding_size, disk_path.split('/')[-1])
            increase_disk_size(disk_path, adding_size)


def check_web_status(web_url: str) -> bool:
    """
    Check if the SOS web service is accessible.
    Args:
        web_url: Base URL of the web service
    Returns:
        bool: True if web service is accessible, False otherwise
    """
    web_status, _ = sosmgr_web_status(web_url)
    if web_status == 'Failure':
        logger.critical("%s is inaccessible", web_url)
        return False

    logger.info("SOS web service status: %s", web_status)
    return True


def send_notification(subject: str, message: list[str]) -> bool:
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
    except Exception as e:
        logger.error("Failed to send email notification: %s", e)
        return False


def process_command_line()-> argparse.Namespace:
    """
    Parse and validate command line arguments.
    Returns:
        Parsed command line arguments
    """
    parser = argparse.ArgumentParser(
        description="""Script for monitoring Cliosoft disks and server performance.
        1. Check sosmgr web service status
        2. Check for too many sosmgr processes that may affect server performance
        3. Check low disk space and optionally increase disk size
        4. Generate email notifications for low disk space and recent disk size increases
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
        Options:
        -dr | --disk-refresh    Refresh the disk file manually. 
                                (Default: automatically refreshes every 24 hours)
        -as | --add-size        Enable automation for adding disk space
        -tm | --test-mode       Flag that the script is running on a test server.

        Logging control (set in environment):
        - tcsh: setenv LOG_LEVEL DEBUG
        - bash: export LOG_LEVEL=DEBUG
        - cron: LOG_LEVEL=DEBUG && python3 sos_check_disk_usage.py [args]
        """
    )
    parser.add_argument("-dr", "--disk-refresh", action="store_true", help='Refresh data file manually')
    parser.add_argument("-as", "--add-size", action="store_true", help='Enable increasing disk size')
    parser.add_argument("-tm", "--test-mode", action="store_true", help='Indicate running on test server')
    logger.debug('Command line arguments: %s', parser.parse_args())
    return parser.parse_args()


def initialize_service(cli_args)-> SosDiskMonitor:
    """Initialize service based on site code or test flag"""
    if cli_args.test_mode:
        logger.debug('Running script on DDM test server')
        return SosDiskMonitor('ddm')
    else:
        return SosDiskMonitor(site_code())

def prepare_data_file(file: Path)-> None:
    """Refresh data file"""
    file.unlink(missing_ok=True)
    create_data_file(file)


def main() -> None|int:
    """Main function"""
    cli_args = process_command_line()

    # Initialize object
    sosMonitor= initialize_service(cli_args)

    # check sosmgr web service response
    check_web_status(sosMonitor.web_url)

    # # Refresh disk data file if needed
    if cli_args.disk_refresh or not sosMonitor.data_file.exists():
        prepare_data_file(sosMonitor.data_file)

    # check disk space and optionally increase disk size
    _disks = sosMonitor.data_file.read_text(encoding='utf-8').strip().splitlines()
    all_disks, low_space_disks = disk_space_info(_disks, LOW_SPACE_THRESHOLD_GB)

    if low_space_disks:
        disk_size_to_add = ADDING_DISK_SIZE_GB if cli_args.add_size else 0
        handle_low_disk_space(low_space_disks, disk_size_to_add)
    else:
        logger.info("All disks have sufficient space")

    # save disk usages to csv file
    csv_file = Path(sosMonitor.data_path, f"{sosMonitor.site.upper()}_disk_usages.csv")
    write_to_csv_file(csv_file, all_disks)


    if messages := read_log_for_errors(sosMonitor.log_file):
        subject = f"Cliosoft Alert: {sosMonitor.site.upper()} disk monitoring failed"
        send_notification(subject, messages)
        rotate_log_file(sosMonitor.log_file)
        return 1

    logger.info("%s disk space monitoring completed successfully", sosMonitor.site.upper())
    return 0


#-----  Main   -----
if __name__ == '__main__':
    # Set up file locking to prevent multiple instances
    LOCK_FILE = "/tmp/sos_check_disks.lock"
    lock_fd = lock_script(LOCK_FILE) # Acquire the lock
    logger = setup_logging()

    try:
        # sys.exit(main())
        main()
    finally:
        # Clean up lock file
        if 'lock_fd' in locals():
            os.close(lock_fd)
            os.unlink(LOCK_FILE)
        logging.shutdown()
