#!/usr/intel/pkgs/python3/3.11.1/bin/python3.11

import json
import logging
import re
import shlex
import socket  # for socket.getfqdn() "server domain"
import subprocess
from functools import wraps
from pathlib import Path
from typing import List, Iterator, Tuple, Final, TextIO, Dict

from UsrIntel.R1 import os, sys
sys.path.append('/opt/cliosoft/monitoring')  # Add the parent directory to modules
from modules.utils import *

# Global variables
LOW_SPACE_THRESHOLD: int = 250  # threshold for low disk size
ADDING_DISK_SIZE: int = 500  # value to be add to current disk size
SERVER_CONFIG_LINK = '/opt/cliosoft/latest/SERVERS'
SERVER_CONFIG_PATH = '/nfs/site/disks/sos_adm/share/SERVERS7'
SOS_ADMIN_CMD = "/opt/cliosoft/latest/bin/sosadmin"
SOS_MGR_CMD = "/opt/cliosoft/latest/bin/sosmgr"
TIMEOUT = 30  # seconds
DDM_CONTACTS = ['linh.a.nguyen@intel.com']
SENDER = "linh.a.nguyen@intel.com"
EXCLUDED_SERVICES_FILE = Path('/opt/cliosoft/monitoring/data/excluded_services.txt')
SITES = ['sc','sc1', 'sc4', 'sc8', 'pdx',
             'iil', 'png', 'iind', 'altera_sc', 'altera_png', 'vr'] # noqa, ignore=E501

#----
class ClioService:
    """Setup Cliosoft application service"""
    # Paths of data and logs
    data_path = Path('/opt/cliosoft/monitoring/data')
    log_path = Path('/opt/cliosoft/monitoring/logs')
    for path in [data_path, log_path]:
        if not path.exists():
            path.mkdir(mode=0o775, parents=True)

    log_file = Path(log_path, 'sos_service_monitoring.log')

    def __init__(self, site):
        self.site = site
        self.server_role = None
        self.web_url = None
        self.site_name = None
        self.data_file = Path(ClioService.data_path, f"{self.site.upper()}_cliosoft_disks.txt")
        self.env_data_file = Path(ClioService.data_path, f'{self.site.upper()}_sos_env.json')
        # self.excluded_services = Path(ClioService.data_path, f'{self.site.upper()}_excluded_services.txt')
        self.load_env_data()

    def load_env_data(self):
        """wrapper for load_from_env_data_file and initialize_env_variables"""
        if Path.exists(self.env_data_file):
            self.load_from_env_data_file()
        else:
            self.initialize_env_variables()
            self.save_env_data()

    @staticmethod
    def logging_debug_decorator(func)-> callable:
        """ Decorate debug information to be logged"""
        @wraps(func)
        def logit(self, *args, **kwargs):
            func(self, *args, **kwargs)
            # Define variables to be logged
            log_vars = [
                    ("Disk data file", self.data_file),
                    ("SOS_SERVERS_DIR", os.environ['SOS_SERVERS_DIR']),
                    ("CLIOSOFT_DIR", os.environ['CLIOSOFT_DIR']),
                    ("SOS_SERVER_ROLE", os.environ['SOS_SERVER_ROLE']),
                    ("EC_ZONE", os.environ['EC_ZONE']),
                    ("Site name", self.site_name.rstrip(':')),
                    ("Web URL", self.web_url),
                    ]
            for name, value in log_vars:
                logger.debug("%s: %s", name, value)
        return logit

    @logging_debug_decorator
    def load_from_env_data_file(self):
        """ Load environment variables from file """
        data = self.read_from_env_data_file(self.env_data_file)
        self.update_site_variables(data)
        self.update_env_variables(data)


    def update_site_variables(self, data):
        """update instance variables"""
        self.site_name = data['site_name']
        self.web_url = data['site_url']
        self.server_role = data['server_role']


    @staticmethod
    def update_env_variables(data):
        """update environment variables"""
        os.environ.update({
            'SOS_SERVERS_DIR': data['sos_servers_dir'],
            'CLIOSOFT_DIR': data['sos_cliosoft_dir'],
            'SOS_SERVER_ROLE': data['server_role'],
            'EC_ZONE': data['ec_zone'],
            })


    @logging_debug_decorator
    def initialize_env_variables(self):
        """Initialize SOS environment variables"""
        os.environ['CLIOSOFT_DIR'] = '/opt/cliosoft/latest'
        os.environ['SOS_SERVERS_DIR'] = ClioService.get_server_config_path(self.site)
        os.environ['EC_ZONE'] = self.site

        if re.search(r'replica$', os.environ['SOS_SERVERS_DIR']):
            os.environ['SOS_SERVER_ROLE'] = 'replica'
        else:
            os.environ['SOS_SERVER_ROLE'] = 'repo'

        self.server_role = os.environ['SOS_SERVER_ROLE']
        self.site_name, self.web_url = ClioService.get_sitename_and_url()


    def save_env_data(self):
        """Save environment variables to file"""
        self.write_to_env_data_file(self.site_name, self.web_url,
                                    self.server_role, os.environ['SOS_SERVERS_DIR'],
                                    os.environ['CLIOSOFT_DIR'], os.environ['EC_ZONE'])


    def write_to_env_data_file(self, *args):
        """Write environment variables to file"""
        SITE_INFO_KEYS = ['site_name', 'site_url', 'server_role', 'sos_servers_dir', 'sos_cliosoft_dir', 'ec_zone']
        data = dict(zip(SITE_INFO_KEYS, args[:6]))

        with open(self.env_data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4) # noqa, ignore=E501


    @staticmethod
    def read_from_env_data_file(file_path)-> Dict[str, str]:
        """Load environment variables from file"""
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)


    @staticmethod
    def get_sitename_and_url()-> List[str]:
        """Returns a list with list of 2 items: site name and web url"""
        cmd = f"{SOS_MGR_CMD} site get -o csv --url | tail -2 | sed -E '/^$|site,url/d'"
        return run_sos_cmd_in_subproc(cmd, timeout=TIMEOUT, is_shell=True)


    @staticmethod
    def get_server_config_path(site)-> str:
        """Set the SOS_SERVERS_DIR path for the given site."""
        real_path = os.path.realpath(SERVER_CONFIG_LINK)

        if site == 'sc':
            return SERVER_CONFIG_PATH
        elif site in SITES or re.match(r'zsc\d+', site):
            if re.search(r'(SERVERS)(7$|8-replica$)', real_path):
                return real_path
            else:
                # logger.error(f"Failed to match server config path for {site} site: {real_path}")
                logger.error("Failed to match server config path for %s site: %s", site, real_path)
                raise ValueError(f'Invalid server config path: {real_path}')
        else:
            logger.debug("Running on test server: %s", site)
            return real_path


def this_site_code() -> str:
    """Returns this site code"""
    return socket.getfqdn().split('.')[1]


def run_sos_cmd_in_subproc(cmd: str, timeout: int, is_shell: bool = False)-> List[str] | None:
    """Run subprocess with timeout"""
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
        return result.stdout.rstrip('\n').split(delimiter)

    except subprocess.TimeoutExpired:
        # logger.critical(f"{run_sos_cmd_in_subproc.__name__} timed out", exc_info=True)
        logger.critical("%s timed out", run_sos_cmd_in_subproc.__name__, exc_info=True)

    except subprocess.CalledProcessError as e:
        # logger.critical(f"Command [{cmd}] failed: {e.stderr}", exc_info=True)
        logger.critical("Command [%s] failed: %s", cmd, e.stderr, exc_info=True)
    return None


def get_sos_services() -> List[str]:
    """Get list of SOS services"""
    logger.info('Querying SOS services')
    sos_cmd = f"{SOS_ADMIN_CMD} list"
    services = run_sos_cmd_in_subproc(sos_cmd, timeout=TIMEOUT)

    if services is None:
        logger.error("No SOS services found")
        raise ValueError('No SOS services found')

    if EXCLUDED_SERVICES_FILE.exists():
        excluded_services = get_excluded_services(EXCLUDED_SERVICES_FILE)
        return [service for service in services if service not in excluded_services]

    return services


def get_sos_disks(services: List[str]) -> Iterator[str]:
    """Yields strings containing primary and cache disk paths"""
    logger.debug('Services: %s', services)
    logger.info('Querying SOS disks')

    # site,name,primary.configuration_locality,primary.path,replica.configuration_locality,replica.path
    # sos_cmd = f"{SOS_MGR_CMD} service get -o csv -cpa -ppa -pcl -s {','.join(services)}"
    # site,name,cache.path,primary.configuration_locality,primary.path
    # --primary_path|-ppa --primary_configuration_locality|-pcl
    # --cache_path|-cpa --cache_configuration_locality|-ccl
    # --replica_path|-rpa --replica_configuration_locality|-rcl
    server_role_commands = {
        'replica': f"{SOS_MGR_CMD} service get -o csv -cpa -ppa -rpa -pcl -rcl -s {','.join(services)}",
        'repo': f"{SOS_MGR_CMD} service get -o csv -cpa -ppa -pcl -s {','.join(services)}",
    }

    server_role = os.environ['SOS_SERVER_ROLE']
    sos_cmd = server_role_commands.get(server_role)

    if sos_cmd is None:
        logger.error("Unknown server role: %s", server_role)
        raise ValueError(f'Unknown server role:  {server_role}')

    lines = run_sos_cmd_in_subproc(sos_cmd, timeout=TIMEOUT)

    if lines is None:
        logger.error("No SOS disks found")
        raise ValueError('No SOS disks found')

    for line in lines:
        line = line.rstrip('\n').split(',')
        logger.debug("SOS disk: %s", line)
        yield line


def create_data_file_decorator(func: callable) -> callable:
    """Delete and re-create file if file is older than a day"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        data_file = args[0]
        if data_file.exists() and file_older_than(data_file, day=1):  # older than 1 day
            try:
                logger.info('Data file is more than a day old...Create a new data file')
                os.remove(data_file)
            except OSError as err:
                logger.error("Failed to remove data file: %s", err)
                raise
        if data_file.exists() is False:
            func(*args, **kwargs)
    return wrapper


# def get_parent_dir(disk_path: Path) -> Path:
#     """Get a disk path that relatives to SQL (pg_data) folder"""
#     path = Path(disk_path, 'pg_data')
#     disk_name_level = 5  #  5 elements: ('/', 'nfs', 'site', 'disks', 'hipipde_soscache_013')
#     level = len(path.parents) - disk_name_level
#     return path.parents[level]


@create_data_file_decorator
def create_data_file(data_file: Path) -> None:
    """
    Creates a data file containing paths of primary and cache disks for Cliosoft.
    This function retrieves disk information, filters it, and writes the relevant paths to the specified data file.
    Parameters:
        data_file (Path): The path where the data file will be created.
    Raises:
        OSError: If there is an error during file creation or writing.
    """
    found_disks: set[Path] = set()
    logger.info('Creating data file')

    def write_disk_path(disk_path: Path, seen_disks: set[Path], file_: TextIO) -> None:
        if disk_path not in seen_disks:
            seen_disks.add(disk_path)
            file_.write(str(disk_path) + '\n')

    my_services = get_sos_services()

    try:
        with open(data_file, 'w', newline='', encoding='utf-8') as file:
            for row in get_sos_disks(my_services):
                if re.match(r'site', row[0]):
                    continue # skip header row
                if len(row) > 5:   # 5 columns when output contains replica path
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
        raise

    # unix sed command to substitute text in file
    subprocess.run(f"sed -i 's:^/nfs/.*/disks:/nfs/site/disks:g' {str(data_file)}", check=True, shell=True)


# def disk_space_info(file: str | Path, size_threshold: int)-> Tuple[Tuple[str], Tuple[str]]:
#     """ Check disk space and return disk info and low space disks"""
#     disks = Path(file).read_text(encoding='utf-8').strip().splitlines()
#     disk_info_all = ()
#     low_space_disks = ()
#     # get free space for each disk
#     for disk in sorted(disks, key=os.path.basename):
#         size, used, avail = report_disk_size(disk)
#         disk_info_all += ([disk, size, used, avail],)
#         if avail <= size_threshold:
#             low_space_disks += ([disk, size, used, avail],)
#     return disk_info_all, low_space_disks


# def write_to_csv_file(csv_file, data: Tuple[str]) -> None:
#     """Save data to cvs file"""
#     import csv
#     with open(csv_file, 'w', encoding='utf-8', newline='') as file:
#         csv_writer = csv.writer(file)
#         csv_writer.writerow(['Disk', 'Total', 'Used', 'Available'])
#         for row in data:
#             csv_writer.writerow(row)


def handle_low_disk_space(disks_with_low_space: Tuple, adding_size: int) -> None:
    """
    Iterate over a tuple of disks for disk name, size and space.
    Generate messages for low disk space and recent disk size increases.
    With option to increase disk size.
    """
    # from modules.utils import has_disk_size_been_increased, increase_disk_size
    DISK_SIZE_INCREASE_DAYS: Final[int] = 2

    for line in disks_with_low_space:
        disk, size, _, avail = line
        warning_low_space = f"{disk} Size: {size}GB; Avail: {avail}GB *** Low disk space"
        logger.warning("%s", warning_low_space)

        if has_disk_size_been_increased(disk, day=DISK_SIZE_INCREASE_DAYS):
            logger.warning("START found %s size has been recently increased... Need investigation",
                           disk.split('/')[-1])
        elif adding_size > 0:
            logger.info("Attempt to add %sGB to %s", adding_size, disk.split('/')[-1])
            increase_disk_size(disk, adding_size)


def check_web_status(web_url: str) -> None:
    """Check sosmgr web service status"""
    web_status, _ = sosmgr_web_status(web_url)
    if web_status == 'Failure':
        logger.debug("sosmgr status: %s", web_status)
        logger.critical("%s is inaccessible", web_url)
    else:
        logger.info("sosmgr status: %s", web_status)


def send_email_status(log_file: str | os.PathLike)-> bool:
    """Send email if there are errors in log file"""
    _site = this_site_code().upper()
    if messages := read_log_error_messages(log_file):
        logger.error("%s disk space monitoring failed", _site)
        subject = f"Cliosoft Alert: {_site} disk monitoring check failed with errors"
        send_email(subject, messages, DDM_CONTACTS, SENDER)
        rotate_log_file(log_file)
        return False

    logger.info("%s disk space monitoring passed", _site)
    logger.info('Script finished')
    return True


def process_cmd_line():
    """Validate command line arguments"""
    import argparse
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,

    description="""\
        Script for monitoring Cliosoft disks and server performance.
            1. Check sosmgr web service status
            2. Check for too many sosmgr processes that may affect server performance (future work)
            3. Check low disk space and optionally increase disk space
            4. Generate email messages for low disk space and recent disk size increases

        Use -rdf | --refresh_disk_file to refresh data file now. (Default refresh every 24 hours)
        Use -eas | --enable_add_size to enable automation for adding disk space
        Use -tst | --test to flag that script is running on a test server
        To enable log debug level in interactive shell (default is INFO)
            tcsh: setenv LOG_LEVEL DEBUG
            bash: export LOG_LEVEL=DEBUG
            cron: LOG_LEVEL=DEBUG && python3 sos_check_disk_usage.py [args]
    """
    )
    parser.add_argument("-rdf", "--refresh_disk_file", action="store_true", help='Refresh data file now')
    parser.add_argument("-eas", "--enable_add_size", action="store_true", help='Enable increasing disk size')
    parser.add_argument("-tst", "--test", action="store_true", help='Indicate running on test server')
    logger.debug('Command line arguments: %s', parser.parse_args())
    return parser.parse_args()


def initialize_service(cli_args)-> ClioService:
    """Initialize service based on site code or test flag"""
    if cli_args.test:
        logger.debug('Running script on DDM test server')
        return ClioService('ddm')
    else:
        logger.debug('Running script on production server')
        return ClioService(this_site_code())


def handle_disk_space(list_low_space_disks: Tuple, cli_args) -> None:
    """
    Handles the disk space monitoring by checking if there are disks with low space.
    Args:
        list_low_space_disks (Tuple): A tuple containing the disks that are low on space.
        cli_args: Command line arguments that may include options for modifying disk size.
    Returns: None: This function does not return a value.
    """
    if list_low_space_disks:
        disk_size_value = ADDING_DISK_SIZE if cli_args.enable_add_size else 0
        handle_low_disk_space(list_low_space_disks, disk_size_value)
    else:
        logger.info("All disks have enough space")


def should_refresh_disk_file(cli_args, obj: ClioService)-> bool:
    """Returns status if data file should be refreshed
    if user requests or when data file size is 0
    """
    return cli_args.refresh_disk_file or (obj.data_file.exists() and obj.data_file.stat().st_size == 0)


def refresh_disk_file(obj: ClioService)-> None:
    """Refresh data file"""
    if os.path.exists(obj.data_file):
        os.remove(obj.data_file)

    create_data_file(obj.data_file)


def main() -> None|int:
    """Main function"""
    cli_args = process_cmd_line()
    sos = initialize_service(cli_args)

    # check sosmgr web service response
    check_web_status(sos.web_url)

    # we want to refresh data file now or file does not exist
    if should_refresh_disk_file(cli_args, sos) or not sos.data_file.exists():
        refresh_disk_file(sos)

    # check disk space and optionally increase disk size
    list_all_disks, list_low_space_disks = disk_space_info(sos.data_file, LOW_SPACE_THRESHOLD)
    handle_disk_space(list_low_space_disks, cli_args)

    # save disk usages to csv file
    csv_file = Path(sos.data_path, f"{sos.site.upper()}_disk_usages.csv")
    write_to_csv_file(csv_file, list_all_disks)

    # return status of sending email
    return send_email_status(sos.log_file)

#-----  Main   -----
if __name__ == '__main__':
    lock_file = "/tmp/sos_check_disks.lock"
    lock_fd = lock_script(lock_file) # Acquire the lock
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper() # Default 'INFO' if LOG_LEVEL is not set

    try:
        logging.basicConfig(
            level=log_level,
            format='[%(asctime)s] [%(name)s] [%(funcName)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[
                logging.FileHandler(ClioService.log_file, mode='w'),  # Create a file handler
                logging.StreamHandler()  # Create a console handler
            ])

        logger = logging.getLogger(__name__)
        status = main()
    finally:
        logging.shutdown()
        # Release the lock file
        os.close(lock_fd)
        os.unlink(lock_file)

    sys.exit(status)
    # # Release the lock file (optional)
    # os.close(lock_fd)
    # os.unlink(lock_file)
    # sys.exit(status)
