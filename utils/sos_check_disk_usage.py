#!/usr/intel/pkgs/python3/3.11.1/bin/python3.11

import subprocess
import re
import shlex
import fcntl
import csv
import argparse
from pprint import pprint as pp
from typing import List, Iterator, Tuple
from pathlib import Path
from functools import wraps

from UsrIntel.R1 import os, sys

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


class SiteSOS:
    """Cliosoft site"""
    site_string_ = 'sc, sc1, sc4, sc8, pdx, iil, png, iind, vr'
    zsc_ = [f"zsc{n}" for n in (4, 7, 9, 10, 11, 12, 14, 15, 16, 18)]
    sites = re.sub(r'\s+', '', site_string_).split(',') + zsc_
    this_site = subprocess.getoutput('echo $EC_ZONE', encoding='utf-8')

    # Directory for data and logs
    data_path = Path('/opt/cliosoft/monitoring')

    # make path
    if not data_path.exists():
        data_path.mkdir(mode=0o775, parents=True)
        

    def __init__(self, site):
        self.site = site
        self.data_file_path = Path(SiteSOS.data_path, f"{self.site.upper()}_cliosoft_disks.txt")
        self.excluded_file_path = Path(SiteSOS.data_path, f"{self.site.upper()}_cliosoft_excluded_services.txt")

        if self.site in SiteSOS.sites:
            os.environ['SOS_SERVERS_DIR'] = '/nfs/site/disks/sos_adm/share/SERVERS7'


    @staticmethod
    def get_services() -> List[str]:
        """Get list of SOS services from Unix env using subprocess"""
        cmd = "/opt/cliosoft/latest/bin/sosadmin list"
        try:
            p = subprocess.run(shlex.split(cmd), capture_output=True, check=True, text=True)
        except subprocess.CalledProcessError as e:
            print("Subprocess failed", e.returncode, e.stderr)
            sys.exit(1)

        # return list of services
        return p.stdout.rstrip().split()


    @staticmethod
    def exclude_services(exclu_file: str | os.PathLike) -> List[str]:
        """Remove service(s) from service list"""

        services = SiteSOS.get_services()

        with open(exclu_file, 'r', encoding='utf8') as f:
            lines = f.read()

        for line in filter(None, lines.split('\n')):  # filter empty and split line
            if not line.startswith('#'):
                try:
                    services.remove(line)  # remove service from the list
                except ValueError:
                    print(f'-W-: {line} not in service list')

        print('-I- Excluding service(s): ',
              [x for x in filter(None, lines.split('\n')) if not x.startswith('#')])

        return services


    def get_disks(self) -> Iterator[str]:
        """sosmgr command returns strings for primary and cache disks"""

        # get service names and check for excluding services
        if self.excluded_file_path.exists():
            print('-I- Found service(s) to be excluded')
            services = SiteSOS.exclude_services(self.excluded_file_path)
        else:
            services = SiteSOS.get_services()

        # This command gives primary and cache paths of all services
        sos_cmd = "/opt/cliosoft/latest/bin/sosmgr service get -o csv -cpa -pp -pcl -s " + ','.join(services)
        p = subprocess.run(sos_cmd, capture_output=True, check=True, text=True, shell=True)
        if p.returncode:
            print(p.stderr)

        # split string to lines and also filter empty lines
        for line in filter(None, p.stdout.split('\n')):
            yield line.rstrip().split(',')  # split() for a list


    def decorator_file_older_than(func):
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


    @decorator_file_older_than
    def create_data_file(self, file_) -> None:
        """Saves primary and cache paths to file"""
        seen = set()
        print('-I- Create data file')
        with open(file_, 'w', newline='', encoding='utf-8') as file:
            for line in self.get_disks():
                if re.match(r'site', line[0]):
                    continue  # skip header row
                # os.path gives string vs. pathlib.Path gives instance of a path
                cache = os.path.dirname(line[2])
                locality = line[3].lower()
                repo = os.path.dirname(line[4])

                if locality == 'local' and repo not in seen:
                    seen.add(repo)          # use set to track disk names
                    file.write(repo + '\n') # file.write works with string
                if cache not in seen:
                    seen.add(cache)         # use set to track disk names
                    file.write(cache + '\n')

        # unix sed command to substitute string 'sitecode' to  string 'site' of the path
        # str(PosixPath) solves error "can only concatenate str (not "PosixPath") to str"
        subprocess.run("sed -i 's:^/nfs/.*/disks:/nfs/site/disks:g' " + str(file_), check=True, shell=True)


def write_to_csv_file(csv_file, data: Tuple[str]):
    """Pass"""
    with open(csv_file, 'w', encoding='utf-8', newline='') as file:
        csv_writer = csv.writer(file)
        csv_writer.writerow(['Disk', 'Total', 'Used', 'Available'])
        for row in data:
            csv_writer.writerow(row)


def perform_check(list_: Tuple) -> List:
    """Pass"""
    messages = []
    for line in list_:
        disk, size, _, avail = line
        messages.append(f"-W- {disk} Size(GB): {size}; Avail(GB): {avail} *** Low disk space")
        answer = util.has_size_been_increased(disk, day=7)
        match answer:
            case None:
                pass
                # status, output = util.increase_disk_size(disk, adding=10)
                # messages.append(output)
            case True:
                messages.append(f"-E- {disk} size was increased recently...Need investigation")
            case False:

                messages.append(f"-F- Failed to check disk {disk}...Got unexpected result")
            case _:
                raise ValueError("-F- Not a correct value")
    return messages


def main() -> None:
    """ """
    ## Requires SOS_SERVERS_DIR variable if not already set in the environment
    # os.environ['SOS_SERVERS_DIR'] = '/nfs/site/disks/sos_adm/share/SERVERS7'

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Script for monitoring Cliosoft disk usages
        Data file is refreshed every 24 hours
        You can use -n | --new to  create a new data file.
    """
    )
    parser.add_argument("-n", "--new", action="store_true", help='Create new data file')
    args = parser.parse_args()

    sos = SiteSOS('ddm')
    # sos = SiteSOS(SiteSOS.this_site)
    limit: int = 250  # threshold disk size value 250GB
    recipient = "linh.a.nguyen@intel.com"

    if args.new:
        os.remove(sos.data_file_path)
    sos.create_data_file(sos.data_file_path)

    # compute disk usages and save result to list
    all_disks = Path(sos.data_file_path).read_text(encoding='utf-8').strip().splitlines()
    tmp_array = ()
    attention = ()
    for disk in sorted(all_disks, key=os.path.basename):
        size, used, avail = util.disk_space_status(disk)
        tmp_array += ([disk, size, used, avail],)
        if avail <= limit: attention += ([disk, size, used, avail],)

    # write list of disk usages to csv file
    csv_file = Path(SiteSOS.data_path, f"{sos.site}_disk_usages.csv")
    write_to_csv_file(csv_file,tmp_array)


    if attention:
        print(attention)
        messages = perform_check(attention)
        # email user(s)
        subject = f"Cliosoft Alert: {sos.site} disk is low on space"
        to_person = recipient
        from_person = recipient
        # email.send_email(subject, '\n'.join(messages), to_person, from_person)
        pp(messages)


if __name__ == '__main__':
    main()

# Release the lock (optional)
os.close(lock_fd)
os.unlink(lock_file)

### demo code
    # disk = /nfs/site/disks/hipipde_soscache_010 (pdx)
    # _disk = '/nfs/site/disks/hipipde.sosrepo.007'
    #_disk = '/nfs/site/disks/ddmtest_sosrepo_001'
    # _size, _space = disk_space_status(_disk)
    # util.increase_disk_size(_disk, 1000)
    # print(util.has_size_been_increased(_disk))
    # _disk2 = '/nfs/site/disks/ddmtest_soscache_001'
    # print(util.has_size_been_increased(_disk2))
    ###
