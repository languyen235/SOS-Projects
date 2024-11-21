#!/usr/intel/pkgs/python3/3.11.1/bin/python3.11

import os
import sys
import re
import shlex
import subprocess
from functools import wraps
from pathlib import Path
from typing import List, Iterator, Tuple, Final

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

from modules.utils import lock_script as lock_script
lock_file = "/tmp/sos_checkdisk.lock"
lock_fd = lock_script(lock_file)

class ClioSite:
    """Cliosoft site"""
    site_names = 'sc, sc1, sc4, sc8, pdx, iil, png, iind, vr'
    zones = [f"zsc{n}" for n in (4, 7, 9, 10, 11, 12, 14, 15, 16, 18)]
    sites = re.sub(r'\s+', '', site_names).split(',') + zones
    this_site = subprocess.getoutput('echo $EC_ZONE', encoding='utf-8')
    ddm_contacts = ['linh.a.nguyen@intel.com']

    # Directory for data and logs
    data_path = Path('/opt/cliosoft/monitoring')
    log_path = Path('/opt/cliosoft/monitoring/log')

    if not log_path.exists():
        log_path.mkdir(mode=0o775, parents=True, exist_ok=True)

    def __init__(self, site):
        self.site = site
        self.data_file = Path(ClioSite.data_path, f"{site.upper()}_cliosoft_disks.txt")




def get_sos_services() -> List[str]:
    """Get list of SOS services from Unix env using subprocess"""
    sos_cmd = "/opt/cliosoft/latest/bin/sosadmin list"
    timeout_s = 10 # 10 seconds

    try:
        p = subprocess.run(shlex.split(sos_cmd), capture_output=True, check=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        logging.critical("Get SOS services timed out: ", e.stderr)
    except subprocess.CalledProcessError as e:
        logging.critical("Get SOS services failed: ", e.returncode, e.stderr)
        sys.exit(1)
    else:
        return p.stdout.rstrip().split()


def get_sos_disks() -> Iterator[str]:
    """sosmgr command yields strings for primary and cache disks"""

    services = get_sos_services()
    # This command gives primary and cache paths of all services
    sos_cmd = f"/opt/cliosoft/latest/bin/sosmgr service get -o csv -cpa -pp -pcl -s {','.join(services)}"
    timeout_s = 40
    try:
        p = subprocess.run(shlex.split(sos_cmd), capture_output=True, check=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        logging.critical("Get SOS disks timed out", e.stderr)
    except subprocess.CalledProcessError as e:
        logging.critical("Get SOS disks failed", e.returncode, e.stderr)
        sys.exit(1)
    else:
        # split string to lines and also filter empty lines
        for line in filter(None, p.stdout.split('\n')):
            logging.debug(line.rstrip().split(','))
            yield line.rstrip().split(',')  # split() for a list


def decorator_create_data_file(func: callable) -> callable:
    """Delete and re-create file if older than 1 day"""
    from modules.utils import file_older_than

    @wraps(func)
    def wrapper(*args, **kwargs):
        data_file = args[0]
        if data_file.exists() and file_older_than(data_file, day=1):  # older than 1 day
            try:
                logging.info('Data file is more than a day old...Re-create data file')
                os.remove(data_file)
            except OSError:
                logging.error("Failed to remove data file")
        if data_file.exists() is False:
            func(*args, **kwargs)
    return wrapper


@decorator_create_data_file
def create_data_file(output_file: Path) -> None:
    """Saves primary and cache paths to file"""
    seen_disks: set[Path] = set()
    logging.info('Creating data file')
    with open(output_file, 'w', newline='', encoding='utf-8') as file:
        for line in get_sos_disks():
            if re.match(r'site', line[0]):
                continue  # skip header row
            cache = Path(line[2]).parent
            locality = line[3].lower()
            repo = Path(line[4]).parent

            if locality == 'local' and repo not in seen_disks:
                seen_disks.add(repo)          # use set to track disk names
                file.write(str(repo) + '\n') # file.write works with string

            if cache not in seen_disks:
                seen_disks.add(cache)
                file.write(str(cache) + '\n')

    # unix sed command to substitute string 'sitecode' to  string 'site' of the path
    subprocess.run(f"sed -i 's:^/nfs/.*/disks:/nfs/site/disks:g' {str(output_file)}", check=True, shell=True)


def disk_space_info(obj: ClioSite)-> Tuple[Tuple[str], Tuple[str]]:
    """ Check disk space and return list of low space disks """
    from modules.utils import disk_usage

    disks = Path(obj.data_file).read_text(encoding='utf-8').strip().splitlines()
    disk_info_all = ()
    low_space_disks = ()
    LIMIT: Final[int] = 250  # threshold for low disk size
    for disk in sorted(disks, key=os.path.basename):
        size, used, avail = disk_usage(disk)
        disk_info_all += ([disk, size, used, avail],)
        if avail <= LIMIT: low_space_disks += ([disk, size, used, avail],)
    return disk_info_all, low_space_disks


def write_to_csv_file(csv_file, data: Tuple[str]) -> None:
    """Save data to cvs file"""
    import csv
    with open(csv_file, 'w', encoding='utf-8', newline='') as file:
        csv_writer = csv.writer(file)
        csv_writer.writerow(['Disk', 'Total', 'Used', 'Available'])
        for row in data:
            csv_writer.writerow(row)


def perform_check(problem_disks: Tuple, increasing_space=False) -> List[str]:
    """
    Iterate over a tuple of disks for disk name, size and space.
    Generate messages for low disk space and recent disk size increases.
    With option to increase disk size.
    """
    from modules.utils import has_disk_size_been_increased, increase_disk_size
    messages = []
    for line in problem_disks:
        disk, size, _, avail = line
        messages.append(f"-W- {disk} Size={size}GB; Avail={avail}GB *** Low disk space")

        if result := has_disk_size_been_increased(disk, day=2):
            messages.append(f"-W- {disk} size was increased recently...Need investigation")
        elif result is None:
            if increasing_space:
                messages.append(increase_disk_size(disk, adding=10))
        else:
            messages.append('-E- Disk check failed')
    return messages


def email_user(messages, obj):
    """ Send email to user"""
    from modules.utils import send_email
    recipient = "linh.a.nguyen@intel.com"
    subject = f"Cliosoft Alert: {obj.site} disk is low on space"
    to_person = ';'.join(ClioSite.ddm_contacts)
    from_person = recipient
    send_email(subject, messages, to_person, from_person)
    logging.debug(messages)


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
    is_new_data_file = bool(cli_args.new_data_file)
    is_adding_space = bool(cli_args.add_size)

    # sos = ClioSite('ddm')
    sos = ClioSite(ClioSite.this_site)

    if sos.site in ClioSite.sites:
        os.environ['SOS_SERVERS_DIR'] = '/nfs/site/disks/sos_adm/share/SERVERS7'

    if is_new_data_file or (sos.data_file.exists() and sos.data_file.stat().st_size == 0):
        os.remove(sos.data_file)

    create_data_file(sos.data_file)

    # check disk space
    list_disks, problem_disks = disk_space_info(sos)

    if problem_disks:
        logging.debug(problem_disks)
        messages = perform_check(problem_disks, is_adding_space)
        email_user(messages, sos)

    # save disk usages to csv file
    csv_file = Path(ClioSite.data_path, f"{sos.site.upper()}_disk_usages.csv")
    write_to_csv_file(csv_file, list_disks)


if __name__ == '__main__':
    main()

# Release the lock (optional)
os.close(lock_fd)
os.unlink(lock_file)
