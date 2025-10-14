#!/opt/cliosoft/monitoring/venv/bin/python3.12

import os, sys
import subprocess
import re
import time
import shutil
import socket
import logging
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

def lock_script(lock_file: str):
    """
    Locks a file pertaining to this script so that it cannot be run simultaneously.

    Since the lock is automatically released when this script ends, there is no
    need for an unlock function for this use case.

    Returns:
        lockfile if lock was acquired. Otherwise, print error and exists.
    """
    import fcntl
    try:
        # Try to acquire an exclusive lock on the file
        lock_handle = os.open(lock_file, os.O_CREAT | os.O_RDWR, mode=0o644)
        fcntl.lockf(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_handle
    except IOError:
        logger.warning("Another instance of the script is already running.")
        sys.exit(1)

def file_older_than(file_path: str | os.PathLike, num_day: int=1):
    """Return true if file is older than number of days"""
    time_difference = time.time() - os.path.getmtime(file_path)
    seconds_in_a_day = 86400  # 24 * 60 * 60

    if time_difference > (seconds_in_a_day * num_day):
        return True
    else:
        return False


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

def site_code():
    """Returns this site code"""
    return socket.getfqdn().split('.')[1]

__all__ = [ 'lock_script', 'file_older_than', 'increase_disk_size', 'has_disk_size_been_increased',
            'report_disk_size', 'get_excluded_services', 'send_email', 'sosmgr_web_status',
            'read_log_for_errors', 'rotate_log_file', 'write_to_csv_file', 'disk_space_info',
            'site_code', 'get_pg_data_parent'
            ]