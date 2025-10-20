#!/opt/cliosoft/monitoring/venv/bin/python3.12

import sys
import subprocess
import shutil
import shlex
import logging
import json
import argparse
from pathlib import Path
from typing import List, Tuple, Dict, Iterator

# Add the parent directory to modules
sys.path.append('/opt/cliosoft/monitoring')

from src.config.settings import *
from src.utils.helpers import *

logger = logging.getLogger(__name__)


def increase_disk_size(disk_name: str, adding_size: int) -> bool:
    """Increase disk size using START command
    """
    try:
        total, _, _ = shutil.disk_usage(disk_name)
        disk_size = total // (2**30)    # <size> // (2**30) converts bytes to Gb and keep only integer number

        # factoring value
        if disk_size >= 1000:
            factor = 100
        elif disk_size >= 100:
            factor = 10
        else:
            logger.error('%s original size is less than 100GB...Auto-resizing is not supported', disk_name)
            return False

        # rounding down to the nearest 1000 or 10 (for example: 501 -> 500, 1024 -> 1000)
        rounded_size = (disk_size // factor) * factor
        new_size = rounded_size + adding_size
        stod_cmd = (
            f"/usr/intel/bin/stod resize --cell {site_code()} --path {disk_name} "
            f"--size {new_size}GB --immediate --exceed-forecast"
        )

        logger.debug("START command: %s",stod_cmd)
        logger.debug("New disk size:  Size(%sGB) + adding(%sGB) = %sGB", disk_size, adding_size, new_size)

        p = subprocess.run(stod_cmd, capture_output=True, check=True, text=True, shell=True)
        if match := re.search(r'(successfully).*$', p.stdout, re.I):
            logger.info("Disk size has been increased to %sGb", new_size)
            logger.debug("%s", match.group())
            return True
        else:
            logger.error("START command completed but with error: %s", p.stderr)
            return False

    except subprocess.CalledProcessError as e:
        logger.error("START command failed with error: %s", e.stderr)
        return False


def has_disk_size_been_increased(disk_info: str, days: int) -> bool | None:
    """Check if disk size has been increased in the last `days` days using START history.
    1) Expected output (There may be a blank line in output depending on OS)
    Type,SubmitTime
    stod resize,10/24/2024 13:47:04
    2) Output as False:
    Type,SubmitTime
    3) Timeout error from START
    Error: request timed out, please try with --timeout switch
    """
    disk_name = Path(disk_info).name
    stod_request_cmd = (
        f"/usr/intel/bin/stodstatus requests --field Type,SubmitTime --format csv "
        f"--history {days}d --number 1 \"description=~'{disk_name}' && type=~'resize'\""
    )
    try:
        p = subprocess.run(stod_request_cmd, capture_output=True, check=True, shell=True, text=True)
        match = re.search(r"stod\s+resize,\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}", p.stdout)
        if match:
            logger.info("Resize found:%s", match.group())
            return True
        else:
            logger.info(
                "Disk %s has not been increased in the last %s days",
                disk_name.split('/')[-1], days
            )
            return False
    except subprocess.CalledProcessError as er:
        logger.debug("START command: %s",stod_request_cmd)
        logger.error("START command failed with error: %s",er.stderr)
        return False


def report_disk_size(disk: str):
    """Available disk space. See shutil module for more info
    (2**30) converts bytes to GB, // keeps only integer number
    Returns a list [total, used, available]
    """
    return [x // (2**30) for x in shutil.disk_usage(disk)]


def get_excluded_services(excluded_service_file: Path) -> List[str]:
    """Read file for excluded services and return list of service names"""
    excluded_services = [line.strip() for line in open(excluded_service_file, 'r', encoding='utf-8')
                         if line.strip() and not line.startswith('#')]

    if excluded_services:
        logger.debug("Excluding services: %s", excluded_services)
        return excluded_services
    else:
        return []


def send_email(subject: str, body: str | List [str], receiver: str | List [str], sender: str):
    """ Send email to users"""
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = ';'.join(receiver) if len(receiver) > 1 else receiver[0]
    msg.set_content("\n".join(body))
    # Send the message via our own SMTP server.
    s = smtplib.SMTP('localhost')
    s.send_message(msg)
    s.quit()
    logger.info("Email sent...")


def sosmgr_web_status(url)-> Tuple[str, int | str]:
    """Check sosmgr status. Credited to Intel iGPT"""
    import requests # type: ignore
    timeout = 5
    try:
        response = requests.get(url, timeout=timeout)
        logger.debug("The sosmgr check returned code: %s", response.status_code)
        if response.status_code != 200:
            return 'Failure', response.status_code

        return 'Success', response.status_code
    except requests.exceptions.Timeout:
        # Handle timeout exception
        logger.error("The request to %s timed out after %s seconds.", url, timeout)
        return 'Failure', "HTTP request timed out"
    except requests.exceptions.RequestException as e:
        # Handle any other exceptions that occur during the request
        logger.error("An error occurred: %s", e)
        return 'Failure', 1


def read_log_for_errors(log_file: Path)-> List[str]:
    """Parse messages from log file"""
    messages = []
    with open(log_file, 'r', encoding='utf-8') as file:
        for line in file:
            if re.search(r'ERROR|WARNING|CRITICAL|EXCEPTION|^([^[].*\n)+', line):
                messages.append(line)
    return messages


def rotate_log_file(filename: str | os.PathLike)-> None:
    """Rotate log files, keep last 5 files"""
    path = Path(filename)
    if not path.is_file():
        return  # Nothing to rotate

    max_backup_count = 5
    # Remove the oldest backup if it exists
    oldest = path.with_name(f"{path.name}.{max_backup_count}")
    if oldest.exists():
        oldest.unlink()

    # Shift existing backups
    for i in reversed(range(1, max_backup_count)):
        src = path.with_name(f"{path.name}.{i}")
        dst = path.with_name(f"{path.name}.{i + 1}")
        if src.exists():
            src.rename(dst)

    # Copy current log to .1
    shutil.copy2(path, path.with_name(f"{path.name}.1")) # copy2 preserves date creation time


def get_pg_data_parent(disk_path: Path, depth: int = 5) -> Path:
    """
    Returns the parent directory of the 'pg_data' folder located under the given disk path.
    Args:
        disk_path (Path): Base path to the disk.
        depth (int): Number of levels up from 'pg_data' to retrieve the parent directory.
    Raises:
        FileNotFoundError: If the disk path does not exist.
        ValueError: If the path is too shallow to reach the desired parent.
    Returns:
        Path: The parent directory at the specified depth.
    """
    if not disk_path.exists():
        raise FileNotFoundError(f"Disk path '{disk_path}' does not exist.")

    pg_data_path = disk_path / 'pg_data'
    parents = pg_data_path.parents
    level = len(parents) - depth
    if len(parents) < depth:
        raise ValueError(
            f"Path '{pg_data_path}' is too shallow (has {len(parents)} levels) "
            f"to retrieve parent at depth {depth}."
        )

    return parents[level]


def write_to_csv_file(csv_file, data: Tuple[str]) -> None:
    """Save data to cvs file"""
    import csv
    with open(csv_file, 'w', encoding='utf-8', newline='') as file:
        csv_writer = csv.writer(file)
        csv_writer.writerow(['Disk', 'Total', 'Used', 'Available'])
        for row in data:
            csv_writer.writerow(row)


def disk_space_info(disks:list[str], size_threshold: int)-> Tuple[Tuple[str], Tuple[str]]:
    """ Check disk space and return lists of all disks and low space disks"""
    all_disks = []
    low_space_disks = []
    # get free space for each disk
    for disk in sorted(disks, key=os.path.basename):
        size, used, avail = report_disk_size(disk)
        disk_info = (disk, size, used, avail)
        all_disks.append(disk_info)
        if avail <= size_threshold:
            low_space_disks.append(disk_info)

    return tuple(all_disks), tuple(low_space_disks)


def read_env_file(file_path)-> Dict[str, str]:
    """Load environment variables from JSON file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as file_error:
        logger.error("Failed to read environment data file: %s", file_error)
        raise


def get_service_dir(site)-> str:
    """Determine the appropriate SOS service configuration path."""
    if IS_REPLICA or site.lower() != 'sc':
        return REAL_SERVICE_DIR

    return DEFAULT_SERVICE_DIR


def get_sitename_and_url()-> tuple[str, str]:
    """Retrieve site name and URL using sosmgr command."""
    cmd = f"{SOS_MGR_CMD} site get -o csv --url | tail -2 | sed -E '/^$|site,url/d'"
    # return run_sos_cmd_in_subproc(cmd, timeout=TIMEOUT, is_shell=True)
    result = run_shell_cmd(cmd, timeout=COMMAND_TIMEOUT, is_shell=True)
    if not result or len(result) < 2:
        raise ValueError("Failed to get site name and URL")
    return result[0], result[1]


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
    services = run_shell_cmd(sos_cmd, timeout=COMMAND_TIMEOUT)

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
    lines = run_shell_cmd(sos_get_disks_cmd, timeout=COMMAND_TIMEOUT)
    if not lines:
        error_msg = "No SOS disks found"
        logger.error(error_msg)
        raise ValueError(error_msg)

    for line in filter(None, map(str.strip, lines)):  # Skip empty lines
        if not line.startswith('site'):  # Skip headers
            disk_info = [text.strip() for text in line.split(',')]
            logger.debug("Parsed SOS disk: %s", disk_info)
            yield disk_info


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


def prepare_disks_file(file: Path)-> None:
    """Refresh data file"""
    file.unlink(missing_ok=True)
    create_disks_file(file)


__all__ = [ 'increase_disk_size', 'has_disk_size_been_increased',
            'report_disk_size', 'get_excluded_services', 'send_email', 'sosmgr_web_status',
            'read_log_for_errors', 'rotate_log_file', 'write_to_csv_file', 'disk_space_info',
            'get_pg_data_parent', 'read_env_file', 'get_service_dir', 'run_shell_cmd',
            'get_sitename_and_url', 'get_sos_services', 'get_sos_disks', 'process_command_line',
            'check_web_status', 'handle_low_disk_space', 'prepare_disks_file',
            ]