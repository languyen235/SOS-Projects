#!/usr/intel/pkgs/python3/3.11.1/bin/python3.11

import os
import sys
import subprocess
import fcntl
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


def increase_disk_size(disk_name: str, adding: int=500) -> str:
    """Increase disk size (500GB) using START command
    1. Expected output for success:
    Your request is being processed
    successfully resized user area /nfs/site/disks/ddmtest_sosrepo_001
    """
    _THIS_SITE: str = subprocess.getoutput('echo $EC_ZONE')

    # <size> /(2**30) return  GB from Bytes; // division and returns the integer part of the result (rounding down)
    size = (shutil.disk_usage(disk_name)[0]) // (2**30)

    # nearest hundredth or tenth digit
    by_number = 100 if size >= 1000 else 10
    new_size = (size // by_number * by_number) + adding  # the // for only integer

    logging.info(f"-I- New disk size:  Size({size}Gb) + adding({adding}Gb) = {new_size}Gb")
    stod_cmd = f"/usr/intel/bin/stod resize --cell {_THIS_SITE} --path {disk_name} " \
               f"--size {new_size}GB --immediate --exceed-forecast"
    logger.info("%s",stod_cmd)

    try:
        p = subprocess.run(stod_cmd, capture_output=True, check=True, text=True, shell=True)
        if result := re.search(r'successfully.*$', p.stdout, re.I):
            return f"-I- {result.group()}"
        else:
            return f"-F- Failure to resize disk: {p.stderr}"
    except subprocess.CalledProcessError as er:
        return f"-F- Exception occurred: {er.stderr}"


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
    d_name = Path(disk_info).name
    # cmd: str = '/usr/intel/bin/stodstatus requests --field Type,SubmitTime --format csv --history ' + \
    #     f"{day}d --number 1 \"description=~'{d_name}' && type=~'resize'\""

    cmd: str = "/usr/intel/bin/stodstatus requests --field Type,SubmitTime --format csv --history " \
                f"{day}d --number 1 \"description=~'{d_name}' && type=~'resize'\""
    logger.info("%s",cmd)

    try:
        p = subprocess.run(cmd, capture_output=True, check=True, shell=True, text=True)
        logger.debug("%s",p.stdout)
        # match_true = re.search(r"stod\s+resize", p.stdout)
        # match_none = re.search(r"Type,SubmitTime", p.stdout)
        return re.search(r"stod\s+resize", p.stdout.strip())
    except subprocess.CalledProcessError as er:
        logger.error("Exception occurred: %s", er.stderr)
        return False


def disk_usage(disk: str):
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
                new_list.remove(line)  # remove service from the list
            except ValueError:
                logger.warning(f'-W-: {line} not in service list')

    logging.info('Excluding service(s): ',
          [x for x in filter(None, lines.split('\n')) if not x.startswith('#')])

    return new_list


def send_email(subject: str, body: str | List [str], to_email: str | List [str], from_email: str):
    """ Send email to users"""
    import smtplib
    from email.message import EmailMessage
    # with open(textfile) as fp:
    #   # Create a text/plain message
    #   msg = EmailMessage()
    #   msg.set_content(fp.read())

    msg = EmailMessage()
    msg['Subject'] = subject
    # msg['From'] = from_email
    msg['From'] = from_email
    msg['To'] = ';'.join(to_email) if len(to_email) > 1 else to_email[0]
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
        return 'Failure', "sosmgr web timed out"
    else:
        return 'Success', response.getcode()