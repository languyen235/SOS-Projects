#!/usr/intel/pkgs/python3/3.11.1/bin/python3.11

import os
import sys
import csv
import fcntl
import re
import shlex
import subprocess
from functools import wraps
from pathlib import Path
from pprint import pprint as pp
from typing import List, Iterator, Tuple

# from UsrIntel.R1 import os, sys

import utils as util
import email_user as email


def lock_script(lockf_: str):
    """
    Locks a file pertaining to this script so that it cannot be run simultaneously.

    Since the lock is automatically released when this script ends, there is no
    need for an unlock function for this use case.

    Returns:
        lockfile if lock was acquired. Otherwise, print error and exists.
    """
    try:
        # Try to acquire an exclusive lock on the file
        lockfd_ = os.open(lockf_, os.O_CREAT | os.O_RDWR, mode=0o644)
        fcntl.lockf(lockfd_, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lockfd_
    except IOError:
        print("Another instance of the script is already running.")
        sys.exit(1)


lock_file = "/tmp/sos_checkdisk.lock"
lock_fd = lock_script(lock_file)


def decorator_file_creation(func):
    """Delete and re-create file"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        file_ = args[0]
        if file_.exists() and util.file_older_than(file_, day=1):  # older than 1 day
            try:
                print('-I- Data file is more than a day old...Re-create data file')
                os.remove(file_)
            except OSError:
                print("-E- Failed to remove data file")
        if not file_.exists():
            func(self, *args, **kwargs)
    return wrapper


class SiteSOS:
    """Cliosoft site"""
    site_string_ = 'sc, sc1, sc4, sc8, pdx, iil, png, iind, vr'
    zsc_ = [f"zsc{n}" for n in (4, 7, 9, 10, 11, 12, 14, 15, 16, 18)]
    sites = re.sub(r'\s+', '', site_string_).split(',') + zsc_
    this_site = subprocess.getoutput('echo $EC_ZONE', encoding='utf-8')
    ddm_contacts = ['linh.a.nguyen@intel.com']

    # Directory for data and logs
    data_path = Path('/opt/cliosoft/monitoring')
    if not data_path.exists():
        data_path.mkdir(mode=0o775, parents=True)
        

    def __init__(self, site):
        self.site = site
        self.data_path = SiteSOS.data_path
        self.data_file_path = Path(self.data_path, f"{self.site.upper()}_cliosoft_disks.txt")

        if self.site in SiteSOS.sites:
            os.environ['SOS_SERVERS_DIR'] = '/nfs/site/disks/sos_adm/share/SERVERS7'


    @staticmethod
    def get_sos_services() -> List[str]:
        """Get list of SOS services from Unix env using subprocess"""
        cmd = "/opt/cliosoft/latest/bin/sosadmin list"
        try:
            p = subprocess.run(shlex.split(cmd), capture_output=True, check=True, text=True)
            if not p.stdout:
                raise ValueError('-F- Operation failed...No SOS service found')
        except subprocess.CalledProcessError as e:
            print("Subprocess failed", e.returncode, e.stderr)
            sys.exit(1)

        # return list of services
        return p.stdout.rstrip().split()

    @staticmethod
    def get_sos_disks() -> Iterator[str]:
        """sosmgr command yields strings for primary and cache disks"""

        services = SiteSOS.get_sos_services()
        # This command gives primary and cache paths of all services
        sos_cmd = "/opt/cliosoft/latest/bin/sosmgr service get -o csv -cpa -pp -pcl -s " + ','.join(services)
        try:
            p = subprocess.run(sos_cmd, capture_output=True, check=True, text=True, shell=True)
        except subprocess.CalledProcessError as e:
            print("Subprocess.run failed", e.returncode, e.stderr)
            sys.exit(1)

        # split string to lines and also filter empty lines
        for line in filter(None, p.stdout.split('\n')):
            yield line.rstrip().split(',')  # split() for a list


    @decorator_file_creation
    def create_data_file(self, out_file) -> None:
        """Saves primary and cache paths to file"""
        seen = set()
        print('-I- Create data file')
        with open(out_file, 'w', newline='', encoding='utf-8') as file:
            for line in SiteSOS.get_sos_disks():
                if re.match(r'site', line[0]):
                    continue  # skip header row
                # os.path gives string vs. pathlib.Path gives instance of a path
                cache = Path(line[2]).parent
                locality = line[3].lower()
                repo = Path(line[4]).parent

                if locality == 'local' and repo not in seen:
                    seen.add(repo)          # use set to track disk names
                    file.write(str(repo) + '\n') # file.write works with string
                if cache not in seen:
                    seen.add(cache)         # use set to track disk names
                    file.write(str(cache) + '\n')

        # unix sed command to substitute string 'sitecode' to  string 'site' of the path
        subprocess.run(f"sed -i 's:^/nfs/.*/disks:/nfs/site/disks:g' {str(out_file)}", check=True, shell=True)


def check_disk_space(obj):
    disks = Path(obj.data_file_path).read_text(encoding='utf-8').strip().splitlines()
    all_disks = ()
    low_space = ()
    low_limit: int = 250  # threshold low disk size
    for disk in sorted(disks, key=os.path.basename):
        size, used, avail = util.disk_space_status(disk)
        all_disks += ([disk, size, used, avail],)
        if avail <= low_limit: low_space += ([disk, size, used, avail],)
    return all_disks, low_space


def write_to_csv_file(csv_file, data: Tuple[str]) -> None:
    """Save data to cvs file"""
    with open(csv_file, 'w', encoding='utf-8', newline='') as file:
        csv_writer = csv.writer(file)
        csv_writer.writerow(['Disk', 'Total', 'Used', 'Available'])
        for row in data:
            csv_writer.writerow(row)


def perform_check(problem_disks: Tuple, add_space=False) -> List[str]:
    """
    Iterate over a tuple of disks for disk name, size and space.
    Generate messages for low disk space and recent disk size increases.
    With option to increase disk size.
    """
    messages = []
    print(problem_disks)
    for line in problem_disks:
        disk, size, _, avail = line
        messages.append(f"-W- {disk} Size={size}GB; Avail={avail}GB *** Low disk space")

        if result := util.has_size_been_increased(disk, day=2):
            messages.append(f"-W- {disk} size was increased recently...Need investigation")
        elif result is None:
            if add_space:
                messages.append(util.increase_disk_size(disk, adding=10))
        else:
            messages.append('-E- Disk check failed')
    return messages


def validate_cmd_line():
    """Parser"""
    import argparse
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Script for monitoring Cliosoft disk usages
        Data file refreshes every 24 hours
        Use -n | --new to  create a new data file.
        Use -as | --add_size to increase disk space.
    """
    )
    parser.add_argument("-nd", "--new_data_file", action="store_true", default=False, help='Create a new data file')
    parser.add_argument("-as", "--add_size", action="store_true", default=False, help='Increase disk size')
    return parser.parse_args()


def main() -> None:
    """ """
    ## Requires SOS_SERVERS_DIR variable if not already set in the environment
    # os.environ['SOS_SERVERS_DIR'] = '/nfs/site/disks/sos_adm/share/SERVERS7'

    cli_args = validate_cmd_line()
    new_data_file = bool(cli_args.new_data_file)
    add_size = bool(cli_args.add_size)

    sos = SiteSOS('ddm')
    # sos = SiteSOS(SiteSOS.this_site)
    if new_data_file:
        os.remove(sos.data_file_path)

    sos.create_data_file(sos.data_file_path)

    # check disk space
    all_disks, low_space = check_disk_space(sos)

    if low_space:
        recipient = "linh.a.nguyen@intel.com"
        messages = '\n'.join(perform_check(low_space, add_size))
        # email user(s)
        subject = f"Cliosoft Alert: {sos.site} disk is low on space"
        to_person = ';'.join(SiteSOS.ddm_contacts)
        from_person = recipient
        # email.send_email(subject, messages, to_person, from_person)
        print(messages)

    # save disk usages to csv file
    csv_file = Path(sos.data_path, f"{sos.site}_disk_usages.csv")
    write_to_csv_file(csv_file, all_disks)


if __name__ == '__main__':
    main()

# Release the lock (optional)
os.close(lock_fd)
os.unlink(lock_file)
