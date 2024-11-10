#!/usr/intel/pkgs/python3/3.11.1/bin/python3.11

from typing import List
import subprocess
import re
import time
import shutil
from pathlib import Path
import os

_THIS_SITE: str = subprocess.getoutput('echo $EC_ZONE')


def file_older_than(file_path: str | os.PathLike, day: int = 1):
    """Return status if file is older than number of days"""
    # time_difference = current_time - last_modified_time_on_file
    time_difference = time.time() - os.path.getmtime(file_path)
    # one day (86400 seconds)
    one_day_in_seconds = 24 * 60 * 60

    if time_difference > (one_day_in_seconds * day):
        print(f"The file '{file_path}' is older than {day} day(s).")
        return True
    return False


def increase_disk_size(disk_name: str, adding: int=500) -> str:
    """Increase disk size (500GB) using START command
    1. Expected output for success:
    Your request is being processed
    successfully resized user area /nfs/site/disks/ddmtest_sosrepo_001
    """
    # <size> /(2**30) return  GB from Bytes; // division and returns the integer part of the result (rounding down)
    size = (shutil.disk_usage(disk_name)[0]) // (2**30)
    # nearest hundredth or tenth digit
    by_number = 100 if size >= 1000 else 10
    new_size = (size // by_number * by_number) + adding  # the // for only integer

    print(f"-I- New disk size:  Size({size}Gb) + adding({adding}Gb) = {new_size}Gb")
    stod_cmd = f"/usr/intel/bin/stod resize --cell {_THIS_SITE} " + \
               f"--path {disk_name} --size {new_size}GB --immediate --exceed-forecast"
    print(stod_cmd)

    try:
        p = subprocess.run(stod_cmd, capture_output=True, check=True, text=True, shell=True)
        if result := re.search(r'successfully.*$', p.stdout, re.I):
            return f"-I- {result.group()}"
        else:
            return f"-F- Disk resizing failed: {p.stderr}"
    except subprocess.CalledProcessError as er:
        return f"-F- Exception occurred: {er.stderr}"


def has_size_been_increased(disk_info: str, day: int=2) -> bool|None:
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
    cmd: str = '/usr/intel/bin/stodstatus requests --field Type,SubmitTime --format csv --history ' + \
        f"{day}d --number 1 \"description=~'{d_name}' && type=~'resize'\""
    print(cmd)

    try:
        p = subprocess.run(cmd, capture_output=True, check=True, shell=True, text=True)
        print(p.stdout)
        # match_true = re.search(r"stod\s+resize", p.stdout)
        # match_none = re.search(r"Type,SubmitTime", p.stdout)
        return re.search(r"stod\s+resize", p.stdout.strip())
    except subprocess.CalledProcessError as er:
        print(f"-E- Exception occurred: {er.stderr}")
        return False


def disk_space_status(disk: str):
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
                print(f'-W-: {line} not in service list')

    print('-I- Excluding service(s): ',
          [x for x in filter(None, lines.split('\n')) if not x.startswith('#')])

    return new_list
