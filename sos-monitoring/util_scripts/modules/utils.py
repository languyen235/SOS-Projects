#!/usr/intel/pkgs/python3/3.11.1/bin/python3.11

import os
import sys
import subprocess
import re
import time
import shutil
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


def file_older_than(file_path: str | os.PathLike, day: int = 1):
    """Return status if file is older than number of days"""
    # time_difference = current_time - last_modified_time_on_file
    time_difference = time.time() - os.path.getmtime(file_path)
    # one day (86400 seconds)
    one_day_in_seconds = 24 * 60 * 60

    if time_difference > (one_day_in_seconds * day):
        return True
    return False


def increase_disk_size(disk_name: str, adding_size: int) -> bool:
    """Increase disk size using START command
    1. Expected output for success:
    Your request is being processed
    successfully resized user area /nfs/site/disks/ddmtest_sosrepo_001
    """
    _THIS_SITE: str = subprocess.getoutput('echo $EC_ZONE')

    # <size> / (2**30) converts bytes to Gb and keep only integer, discard the decimal part
    size = (shutil.disk_usage(disk_name)[0]) // (2**30)

    # by_number = 100 if size >= 1000 else 10
    # new_size = (size // by_number * by_number) + adding_size  # the // returns only integer
    #
    #  rounding down to the nearest 1000 or 100
    # decimal_factor = -3 if size >= 1000 else -2
    if size >= 1000:
        decimal_factor = -3
    elif size >= 100:
        decimal_factor = -2
    else:
        logger.debug('Original disk size is less than 100GB')
        return False

    #  rounding down size to the nearest 1000 or 10 (for example: 501 -> 500, 1024 -> 1000)
    rounded_down_value = round(size, decimal_factor)
    new_size = rounded_down_value + adding_size
    logger.debug(f"New disk size:  Size({size}Gb) + adding({adding_size}Gb) = {new_size}Gb")

    stod_cmd = f"/usr/intel/bin/stod resize --cell {_THIS_SITE} --path {disk_name} " \
               f"--size {new_size}GB --immediate --exceed-forecast"

    try:
        p = subprocess.run(stod_cmd, capture_output=True, check=True, text=True, shell=True)
        if result := re.search(r'(successfully).*$', p.stdout, re.I):
            logger.info("%s", result.group())
            return True
    except subprocess.CalledProcessError as er:
        logger.debug("START command: %s",stod_cmd)
        logger.error("START command failed with error: %s", er.stderr)
        return False


def has_disk_size_been_increased(disk_info: str, day: int=2) -> bool | None:
    """read START history if disk size has been increased since the last 2 days
    1) Expected output (There may be a blank line in output depending on OS)
    Type,SubmitTime
    stod resize,10/24/2024 13:47:04
    2) Output as False:
    Type,SubmitTime
    3) Timeout error from START
    Error: request timed out, please try with --timeout switch
    """
    disk_name = Path(disk_info).name
    stod_request_cmd: str = "/usr/intel/bin/stodstatus requests --field Type,SubmitTime --format csv --history " \
                f"{day}d --number 1 \"description=~'{disk_name}' && type=~'resize'\""

    try:
        p = subprocess.run(stod_request_cmd, capture_output=True, check=True, shell=True, text=True)
        # match_true = re.search(r"stod\s+resize", p.stdout)
        # match_none = re.search(r"Type,SubmitTime", p.stdout)
        # search for "stod resize" in the output
        if search_result := re.search(r"stod\s+resize,\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}", p.stdout):
            logger.info("%s", search_result.group())
            return True
        elif search_result is None:
            logger.info("Disk %s was not increased in the last %s days", disk_name, day)
            return None
    except subprocess.CalledProcessError as er:
        logger.debug("START command: %s",stod_request_cmd)
        logger.error("START command failed with error: %s",er.stderr)
        return False


def report_disk_size(disk: str):
    """Available disk space. See shutil mode for more info
    (2**30) converts bytes to GB, // keeps only integer number
    Returns a list [total, used, available]
    """
    return [x // (2**30) for x in shutil.disk_usage(disk)]


def exclude_services(exclu_file: str | os.PathLike, services: List) -> List[str]:
    """Remove service(s) from service list"""
    new_list = services
    with open(exclu_file, 'r', encoding='utf-8') as file:
        lines = file.read()

    for line in filter(None, lines.split('\n')):  # filter empty and split line
        if not line.startswith('#'):
            try:
                logger.debug("Excluding service: %s", line)
                new_list.remove(line)  # remove service from the list
            except ValueError:
                logger.warning("%s is not in service list, skipping...", line)

    logger.debug('Excluding service(s): ',
          [x for x in filter(None, lines.split('\n')) if not x.startswith('#')])

    return new_list


def send_email(subject: str, body: str | List [str], receiver: str | List [str], sender: str):
    """ Send email to users"""
    import smtplib
    from email.message import EmailMessage
    # with open(textfile) as fp:
    #   # Create a text/plain message
    #   msg = EmailMessage()
    #   msg.set_content(fp.read())

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


def sosgmr_status(url)-> Tuple[str, int | str]:
    import urllib.request
    import urllib.error
    import socket

    try:
        response = urllib.request.urlopen(url, timeout=10)
        logger.debug("The sosmgr check returned code: %s", response.getcode())
        # html = response.read().decode('utf-8')
        # print(html)
    except urllib.error.HTTPError as e:
        logger.error('HTTP Error: %s', e.code)
        if e.code == 404:
            logger.error('Page not found.')
        elif e.code == 500:
            logger.error('Internal server error.')
        return 'Failure', e.code
    except urllib.error.URLError as e:
        logger.error('URL Error: %s', e.reason)
        return 'Failure', e.reason
    except socket.timeout:
        logger.error("SOS web access timed out")
        return 'Failure', "sosmgr timed out"
    else:
        return 'Success', response.getcode()


def parse_error_messages(log_file: str | os.PathLike)-> List[str]:
    """Parse messages from log file"""
    messages = []
    with open(log_file, 'r', encoding='utf-8') as file:
        for line in file:
            # if re.search(r'ERROR|WARNING|FATAL|CRITICAL|EXCEPTION', line):
            if re.search(r'todo_when_low_disk_space|has_disk_size_been_increased|increase_disk_size', line):
                messages.append(line)
    return messages


def verify_file_link(file_link, expected_directory):
    # Check if the file link exists
    if not os.path.exists(file_link):
        logger.error(f"The file link '{file_link}' does not exist.")
        return False

    # Get the absolute path of the file link
    file_link_abs_path = os.path.abspath(file_link)

    # Get the absolute path of the expected directory
    expected_directory_abs_path = os.path.abspath(expected_directory)

    # Check if the file link is a symbolic link
    if os.path.islink(file_link):
        # Get the target of the symbolic link
        target_path = os.readlink(file_link)
        target_abs_path = os.path.abspath(target_path)

        # Verify if the target path is within the expected directory
        if target_abs_path.startswith(expected_directory_abs_path):
            logger.info(f"The file link '{file_link}' "
                        f"is correctly linking to the expected directory '{expected_directory}'.")
            return True
        else:
            logger.error(f"The file link '{file_link}' "
                         f"is not linking to the expected directory '{expected_directory}'.")
            return False
    else:
        logger.error(f"The file link '{file_link}' is not a symbolic link.")
        return False