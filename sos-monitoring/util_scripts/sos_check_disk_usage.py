#!/usr/intel/pkgs/python3/3.11.1/bin/python3.11

import os
import sys
import re
import shlex
import subprocess
import logging
from functools import wraps
from pathlib import Path
from typing import List, Iterator, Tuple, Final, TextIO
from modules.utils import (send_email, sosgmr_status,
                           lock_script, report_disk_size, parse_error_messages, verify_file_link)

# Global variables
LOW_SPACE_LIMIT: Final[int] = 250  # threshold for low disk size
ADDED_SPACE_LIMIT: Final[int] = 10  # threshold for disk size increase
# SERVER_CONFIG_LINK_PATH = Path('/opt/cliosoft/latest/SERVERS')
# PRIME_SERVER_CONFIG_PATH = Path('/nfs/site/disks/sos_adm/share/SERVERS7')
# REPLICA_SERVER_CONFIG_PATH = Path('/nfs/site/disks/sos_adm/share/SERVERS8-replica')
# SITES = ['sc','sc1', 'sc4', 'sc8', 'pdx',
#              'iil', 'png', 'iind', 'altera_sc', 'altera_png', 'vr']

class ClioService:
    """Setup Cliosoft application service"""
    sites = ['sc','sc1', 'sc4', 'sc8', 'pdx',
             'iil', 'png', 'iind', 'altera_sc', 'altera_png', 'vr']
    ddm_contacts = ['linh.a.nguyen@intel.com']
    sender = "linh.a.nguyen@intel.com"

    # Directory for data and logs
    data_path = Path('/opt/cliosoft/monitoring/data')
    log_path = Path('/opt/cliosoft/monitoring/logs')
    log_file = Path(log_path, 'sos_check_disks.log')
    for path in [data_path, log_path]:
        if path.exists() is False:
            path.mkdir(mode=0o775, parents=True, exist_ok=True)



    def __init__(self, site):
        self.site = site
        self.sever_config_link_path = Path('/opt/cliosoft/latest/SERVERS')
        self.primary_server_config_folder = Path('/nfs/site/disks/sos_adm/share/SERVERS7')
        self.replica_server_config_folder = Path('/nfs/site/disks/sos_adm/share/SERVERS8-replica')
        self.web_url = ''
        os.environ['SOS_SERVERS_DIR'] = ''

        # Set up SOS_SERVERS_DIR and sosmgr URL for each site based on site name
        if self.site == 'sc':   # <-- this is necessary because SC has both production and test servers
            os.environ['SOS_SERVERS_DIR'] = '/nfs/site/disks/sos_adm/share/SERVERS7'
            self.web_url = f"http://sosmgr-{self.site}.sync.intel.com:3070"
        # search sites including zsc sites
        elif self.site in ClioService.sites or re.match(r'^zsc\d+$', self.site):
            if verify_file_link(self.sever_config_link_path, self.primary_server_config_folder):
                os.environ['SOS_SERVERS_DIR'] = '/nfs/site/disks/sos_adm/share/SERVERS7'
                self.web_url = f"http://sosmgr-{self.site}.sync.intel.com:3070"
            elif verify_file_link(self.sever_config_link_path, self.replica_server_config_folder):
                os.environ['SOS_SERVERS_DIR'] = '/nfs/site/disks/sos_adm/share/SERVERS8-replica'
                self.web_url = f"http://sosmgr-{self.site}-replica.sync.intel.com:3080"
            else:
                logging.critical("Cannot detect server config folder for %s", self.site)
                sendmail_before_raising_exception()
                raise Exception(f"Cannot find server config folder for {self.site}")
        else:
            os.environ['SOS_SERVERS_DIR'] = '/opt/cliosoft/latest/SERVERS'
            self.web_url = 'http://scysync36.sc.intel.com:8080'  # this test server URL

        self.site_name = subprocess.getoutput('sosmgr site get -u | head -1', encoding='utf-8')
        self.data_file = Path(ClioService.data_path, f"{self.site.upper()}_cliosoft_disks.txt")


def run_subprocess(cmd, timeout: int) -> List[str]:
    """Run subprocess with timeout"""
    process = subprocess.Popen(shlex.split(cmd),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               universal_newlines=True)
    try:
        std_out, std_err = process.communicate(timeout=timeout)
        if process.returncode != 0:
            # def remove_empty_lines(string):
            # return re.sub(r'(?<=\n)\s+', '', string , re.MULTILINE)
            logger.critical("Command [%s] failed: %s", cmd, std_out)
            return []
        else:
            return std_out.rstrip().split()
    except subprocess.TimeoutExpired:
        logger.critical("%s function timed out", run_subprocess.__name__)
        process.kill()
        process.communicate()
        # raise TimeoutError(f"Command: [{cmd}] timed out")
        return []


def get_sos_services() -> List[str]:
    """Get list of SOS services"""
    logger.info('Querying SOS services')
    sos_cmd = "/opt/cliosoft/latest/bin/sosadmin list"
    services = run_subprocess(sos_cmd, timeout=10)
    if not services:
        logger.error("No SOS services found")
        sendmail_before_raising_exception()
        raise ValueError('No SOS services found')
    else:
        logger.debug("SOS services: %s", services)
        return services


def get_sos_disks() -> Iterator[str]:
    """Yields strings containing primary and cache disk paths"""
    services = get_sos_services()
    logger.info('Querying SOS disks')
    sos_cmd = f"/opt/cliosoft/latest/bin/sosmgr service get -o csv -cpa -pp -rpa -pcl -rcl -s {','.join(services)}"
    # site,name,primary.configuration_locality,primary.path,replica.configuration_locality,replica.path
    # sos_cmd = f"/opt/cliosoft/latest/bin/sosmgr service get -o csv -cpa -pp -pcl -s {','.join(services)}"
    # site,name,cache.path,primary.configuration_locality,primary.path
    lines = run_subprocess(sos_cmd, timeout=40)
    if not lines:
        logger.error("No SOS disks found")
        sendmail_before_raising_exception()
        raise ValueError('No SOS disks found')
    else:
        for line in lines:
            logger.debug("%s", line.rstrip().split(','))
            yield line.rstrip().split(',')


def decorator_create_data_file(func: callable) -> callable:
    """Delete and re-create file if older than 1 day"""
    from modules.utils import file_older_than
    @wraps(func)
    def wrapper(*args, **kwargs):
        data_file = args[0]
        if data_file.exists() and file_older_than(data_file, day=1):  # older than 1 day
            try:
                logger.info('Data file is more than a day old...Create a new data file')
                os.remove(data_file)
            except OSError as err:
                logger.error("Failed to remove data file: %s", err)
                sendmail_before_raising_exception()
                raise
        if data_file.exists() is False:
            func(*args, **kwargs)
    return wrapper


def get_parent_dir(disk_path: Path) -> Path:
    """Get a disk path that relatives to pg_data folder"""
    path = Path(disk_path, 'pg_data')
    disk_name_level = 5  #  5 elements: ('/', 'nfs', 'site', 'disks', 'hipipde_soscache_013')
    level = len(path.parents) - disk_name_level
    return path.parents[level]


@decorator_create_data_file
def create_data_file(data_file: Path) -> None:
    """Creates data file for replica"""
    found_disks: set[Path] = set()
    logger.info('Creating data file')

    def write_disk_path(disk_path: Path, seen_disks: set[Path], file_: TextIO) -> None:
        if disk_path not in seen_disks:
            seen_disks.add(disk_path)
            file_.write(str(disk_path) + '\n')
    try:
        with open(data_file, 'w', newline='', encoding='utf-8') as file:
            for row in get_sos_disks():
                if re.match(r'site', row[0]):
                    continue # skip header row
                if len(row) > 5:   # contains replica path
                    replica_dir = get_parent_dir(Path(row[-1]))
                    write_disk_path(replica_dir, found_disks, file)
                else:
                    repo_dir = get_parent_dir(Path(row[-1]))
                    locality = row[-2].lower()
                    cache_dir = get_parent_dir(Path(row[-3]))
                    if locality == 'local':
                        write_disk_path(repo_dir, found_disks, file)
                    write_disk_path(cache_dir, found_disks, file)
    except OSError as err:
        logger.error("Failed to create data file: %s", err)
        sendmail_before_raising_exception()
        raise

    # unix sed command to substitute text in file
    subprocess.run(f"sed -i 's:^/nfs/.*/disks:/nfs/site/disks:g' {str(data_file)}", check=True, shell=True)


def disk_space_info(file: str | Path)-> Tuple[Tuple[str], Tuple[str]]:
    """ Check disk space and return disk info and low disk space disks"""
    disks = Path(file).read_text(encoding='utf-8').strip().splitlines()
    disk_info_all = ()
    low_space_disks = ()
    # find available disk space
    for disk in sorted(disks, key=os.path.basename):
        size, used, avail = report_disk_size(disk)
        disk_info_all += ([disk, size, used, avail],)
        if avail <= LOW_SPACE_LIMIT:
            low_space_disks += ([disk, size, used, avail],)
    return disk_info_all, low_space_disks


def write_to_csv_file(csv_file, data: Tuple[str]) -> None:
    """Save data to cvs file"""
    import csv
    with open(csv_file, 'w', encoding='utf-8', newline='') as file:
        csv_writer = csv.writer(file)
        csv_writer.writerow(['Disk', 'Total', 'Used', 'Available'])
        for row in data:
            csv_writer.writerow(row)


def todo_when_low_disk_space(problem_disks: Tuple, added_size: int) -> None:
    """
    Iterate over a tuple of disks for disk name, size and space.
    Generate messages for low disk space and recent disk size increases.
    With option to increase disk size.
    """
    from modules.utils import has_disk_size_been_increased, increase_disk_size
    for line in problem_disks:
        disk, size, _, avail = line
        warning_low_space = f"{disk} Size: {size}GB; Avail: {avail}GB *** Low disk space"

        if result := has_disk_size_been_increased(disk, day=2):
            logger.warning("%s", warning_low_space)
            logger.warning("%s's size was increased recently...Investigation needed", disk.split('/')[-1])
        elif result is None:
            if added_size > 0:
                increase_disk_size(disk, added_size)
            else:
                logger.warning("%s", warning_low_space)
        else:
            logger.warning("%s", warning_low_space)
            logger.error('Disk check failed: %s', result)


def check_web_status(web_url: str) -> None:
    """Check sosmgr web service status"""
    mgr_status = sosgmr_status(web_url)
    if mgr_status[0] == 'Failure':
        logger.debug("sosmgr status: %s", mgr_status)
        logger.critical("%s is inaccessible", web_url)


def before_exit_program(obj: ClioService):
    """Send email if there are errors in log file before exiting"""
    if messages := parse_error_messages(ClioService.log_file):
        subject = f"Cliosoft Alert: {obj.site.upper()} disk space check finished with errors"
        send_email(subject, messages, ClioService.ddm_contacts, ClioService.sender)
    else:
        logger.info("%s disk space check passed", obj.site.upper())
        logger.info('Script finished')


def sendmail_before_raising_exception():
    messages = parse_error_messages(ClioService.log_file)
    this_site = subprocess.getoutput('echo $EC_ZONE', encoding='utf-8')
    subject = f"Cliosoft Alert: {this_site.upper()} disk space check exited with errors"
    send_email(subject, messages, ClioService.ddm_contacts, ClioService.sender)


def validate_cmd_line():
    """Validate command line arguments"""
    import argparse
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Script for monitoring Cliosoft disk low space and optionally auto-increasing disk space
        Data file for disk information refreshes every 24 hours
        
        Use -nd | --new_data_file to force refreshing a new data file.
        Use -as | --add_size to enable auto-increasing low disk space
        To turn on logging debug level, set environment variable (default is INFO)
            tcsh: setenv LOG_LEVEL DEBUG
            bash: export LOG_LEVEL=DEBUG
    """
    )
    parser.add_argument("-nd", "--new_data_file", action="store_true", help='Create a new data file')
    parser.add_argument("-as", "--add_size", action="store_true", help='Increase disk size')
    return parser.parse_args()


def main() -> None:
    """Main function"""
    cli_args = validate_cmd_line()
    logger.debug('Command line arguments: %s', cli_args)
    is_new_data_file = cli_args.new_data_file
    is_adding_space = cli_args.add_size

    ### uncomment for testing script on test site
    # sos = ClioService('ddm')  # test site
    #### End

    ## Uncomment this block for production site
    this_site = subprocess.getoutput('echo $EC_ZONE', encoding='utf-8')
    sos = ClioService(this_site)
    ## End
    logger.debug("Setting SOS_SERVERS_DIR to: %s", os.environ['SOS_SERVERS_DIR'])
    logger.debug("Site name: %s", sos.site_name.rstrip(':'))
    logger.debug("Web URL: %s", sos.web_url)

    # check if we need to refresh data file
    if is_new_data_file or (sos.data_file.exists() and sos.data_file.stat().st_size == 0):
        os.remove(sos.data_file)

    create_data_file(sos.data_file)

    # check sosmgr FE web service
    check_web_status(sos.web_url)

    # check disk space and optionally increase disk size
    list_disks, low_space_disks = disk_space_info(sos.data_file)
    if low_space_disks:
        adding_space = ADDED_SPACE_LIMIT if is_adding_space else 0
        todo_when_low_disk_space(low_space_disks, adding_space)
    else:
        logger.debug("All disks have enough space")

    # save disk usages to csv file
    csv_file = Path(ClioService.data_path, f"{sos.site.upper()}_disk_usages.csv")
    write_to_csv_file(csv_file, list_disks)

    before_exit_program(sos)

if __name__ == '__main__':
    lock_file = "/tmp/sos_check_disks.lock"
    lock_fd = lock_script(lock_file)
    log_file = Path(ClioService.log_path, 'sos_check_disks.log')
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper() # Default 'INFO' if LOG_LEVEL is not set
    logging.basicConfig(level=log_level,
                        format='[%(asctime)s] [%(name)s] [%(funcName)s] [%(levelname)s] %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        handlers=[
                            logging.FileHandler(log_file, mode='w'),  # Create a file handler
                            logging.StreamHandler()  # Create a console handler
                        ])
    logger = logging.getLogger(__name__)
    main()

    # Release the lock (optional)
    os.close(lock_fd)
    os.unlink(lock_file)
    sys.exit(0)
