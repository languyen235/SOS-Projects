#!/usr/intel/pkgs/python3/3.11.1/bin/python3.11

import os
import sys
import re
import shlex
import subprocess
import logging
from functools import wraps
from pathlib import Path
from typing import List, Iterator, Tuple, Final
# from modules.utils import lock_script as lock_script
from modules.utils import send_email, sosgmr_status, lock_script


class ClioService:
    """Setup Cliosoft application service"""
    site_names = 'sc, sc1, sc4, sc8, pdx, iil, png, iind'
    zones = [f"zsc{n}" for n in (4, 7, 9, 10, 11, 12, 14, 15, 16, 18, 28)]
    sites = re.sub(r'\s+', '', site_names).split(',') + zones
    this_site = subprocess.getoutput('echo $EC_ZONE', encoding='utf-8')
    ddm_contacts = ['linh.a.nguyen@intel.com']
    sender = "linh.a.nguyen@intel.com"

    # Directory for data and logs
    data_path = Path('/opt/cliosoft/monitoring')
    log_path = Path('/opt/cliosoft/monitoring/log')

    if log_path.exists() is False:
        log_path.mkdir(mode=0o775, parents=True, exist_ok=True)

    def __init__(self, site):
        self.site = site
        self.web_url = f"http://sosmgr-{self.site}.sync.intel.com:3070"
        self.data_file = Path(ClioService.data_path, f"{self.site.upper()}_cliosoft_disks.txt")



def run_subprocess( cmd, timeout ):
    """Run subprocess with timeout"""
    process = subprocess.Popen(shlex.split(cmd),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               universal_newlines=True)
    try:
        std_out, std_err = process.communicate(timeout=timeout)
        if process.returncode != 0:
            def remove_empty_lines(string):
                return re.sub(r'(?<=\n)\s+', '', string , re.MULTILINE)
            logging.critical("Command [%s] failed: \n%s", cmd, remove_empty_lines(std_err))
            sys.exit(1)
    except subprocess.TimeoutExpired:
        logging.critical("Subprocess timed out")
        process.kill()
        process.communicate()
        raise TimeoutError(f"Command: [{cmd}] timed out")
    else:
        return std_out.rstrip().split()


def get_sos_services() -> List[str]:
    """Get list of SOS services"""
    logging.info('Querying SOS services')
    sos_cmd = "/opt/cliosoft/latest/bin/sosadmin list"
    try:
        services = run_subprocess(sos_cmd, timeout=10)
        if not services:
            raise ValueError('No SOS services found')
        else:
            return services
    except Exception as err:
        logging.error("Failed to get SOS services: ", err)
        raise Exception

def get_sos_disks() -> Iterator[str]:
    """Yields strings containing primary and cache disk paths"""
    services = get_sos_services()
    logging.info('Querying SOS disks')
    sos_cmd = f"/opt/cliosoft/latest/bin/sosmgr service get -o csv -cpa -pp -pcl -s {','.join(services)}"
    lines = run_subprocess(sos_cmd, timeout=40)
    for line in lines:
        logging.debug(line.rstrip().split(','))
        yield line.rstrip().split(',')


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
            except OSError as err:
                logging.error("Failed to remove data file: %s", err)
        if data_file.exists() is False:
            func(*args, **kwargs)
    return wrapper


@decorator_create_data_file
def create_data_file(data_file: Path) -> None:
    """Saves primary and cache paths to file"""
    disks: set[Path] = set()
    logging.info('Creating data file')
    with open(data_file, 'w', newline='', encoding='utf-8') as file:
        for row in get_sos_disks():
            if re.match(r'site', row[0]):
                continue  # skip header row
            cache_dir = Path(row[2]).parent
            repo_dir = Path(row[4]).parent
            if row[3].lower() == 'local' and repo_dir not in disks:
                disks.add(repo_dir)
                file.write(str(repo_dir) + '\n')
            if cache_dir not in disks:
                disks.add(cache_dir)
                file.write(str(cache_dir) + '\n')

    # unix sed command to substitute text in file
    subprocess.run(f"sed -i 's:^/nfs/.*/disks:/nfs/site/disks:g' {str(data_file)}", check=True, shell=True)


def disk_space_info(file: str | Path)-> Tuple[Tuple[str], Tuple[str]]:
    """ Check disk space and return list of low space disks """
    from modules.utils import disk_usage

    disks = Path(file).read_text(encoding='utf-8').strip().splitlines()
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


def act_on_low_space_disk(problem_disks: Tuple, increasing_space=False) -> List[str]:
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


def check_web_status(web_url: str, site: str):
    mgr_status = sosgmr_status(web_url)
    if mgr_status[0] == 'Failure':
        logging.debug("sosmgr web service is inaccessible")
        error_msg = f"{site.upper()} {mgr_status[1]}"
        subject = f"Cliosoft Alert: {site.upper()} sosmgr web service is inaccessible"
        send_alert(subject, [error_msg] , ClioService.ddm_contacts, ClioService.sender)


def send_alert(subject, messages, recipients, sender):
    send_email(subject, messages, recipients, sender)


def validate_cmd_line():
    """Validate command line arguments"""
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

    sos = ClioService('ddm')
    # sos = ClioService(ClioService.this_site)
    if sos.site in ClioService.sites:
        os.environ['SOS_SERVERS_DIR'] = '/nfs/site/disks/sos_adm/share/SERVERS7'

    # create data file
    if is_new_data_file or (sos.data_file.exists() and sos.data_file.stat().st_size == 0):
        os.remove(sos.data_file)
    create_data_file(sos.data_file)

    # check sosmgr status
    sos.web_url = "http://scysync36.sc.intel.com:8080"
    check_web_status(sos.web_url, sos.site)

    # check disk space
    list_disks, problem_disks = disk_space_info(sos.data_file)
    if problem_disks:
        logging.debug(problem_disks)
        messages = act_on_low_space_disk(problem_disks, is_adding_space)
        subject = f"Cliosoft Alert: {sos.site.upper()} disk is low on space"
        send_alert(subject, messages, ClioService.ddm_contacts, ClioService.sender)

    # save disk usages to csv file
    csv_file = Path(ClioService.data_path, f"{sos.site.upper()}_disk_usages.csv")
    write_to_csv_file(csv_file, list_disks)


if __name__ == '__main__':
    lock_file = "/tmp/sos_checkdisk.lock"
    lock_fd = lock_script(lock_file)
    logging.basicConfig(level=logging.INFO,
                        format='[%(asctime)s] [%(name)s] [%(module)s] [%(levelname)s] %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')
    logger = logging.getLogger(__name__)
    main()

    # Release the lock (optional)
    os.close(lock_fd)
    os.unlink(lock_file)

