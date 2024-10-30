#!/usr/intel/pkgs/python3/3.11.1/bin/python3.11
from UsrIntel.R1 import os, sys
import subprocess
import re
import shlex
import shutil
# import math
from pprint import pprint as pp
from typing import List, Iterator
from pathlib import Path


def lock_script(lock_file: str):
    """ Create a lock file to indicate script is currently running
        only once instant of this script running at any given time
    """
    import fcntl
    try:
        # Try to acquire an exclusive lock on the file
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, mode=0o644)
        fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd
    except IOError:
        print("Another instance of the script is already running.")
        sys.exit(1)


lock_file = "/tmp/sos_checkdisk.lock"
lock_fd = lock_script(lock_file)

# Directory for data and logs
data_path = Path('/opt/cliosoft/monitoring')
if not data_path.exists(): data_path.mkdir(mode=0o775, parents=True, exist_ok=True)

class SubprocessFailed(Exception):
    def __init__(self, message, exit_code, stderr):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class SiteSOS:
    def __init__(self, site):
        self.site = site
        self.disk_file = Path(data_path, f"{self.site.upper()}_cliosoft_disks.txt")
        self.excluded_file = Path(data_path, f"{self.site.upper()}_cliosoft_excluded_services.txt")


    def get_services(self) -> List[str]:
        """Get list of SOS services from Unix env using subprocess"""
        try:
            # os.system(f"ssh {self.sosmgr_server} sosmgr service get -o csv -pp > {self.f_services}")
            cmd = "/opt/cliosoft/latest/bin/sosadmin list"
            p = subprocess.run(shlex.split(cmd), capture_output=True, check=True, text=True)
        # except subprocess.CalledProcessError as e:
        #     print("Subprocess failed with exit code:", e.returncode)
        #     print("Error output:", e.stderr)
        #     raise Exception("Subprocess failed") from e
        except subprocess.CalledProcessError as e:
            raise SubprocessFailed("Subprocess failed", e.returncode, e.stderr) from e

        # return list of services
        if self: return p.stdout.rstrip().split()


    def exclude_services(self, exclu_file: str | os.PathLike) -> List[str]:
        """Remove service(s) from service list"""

        services = self.get_services()

        with open(exclu_file, 'r') as f:
            lines = f.read()

        for line in filter(None, lines.split('\n')):  # filter empty and split line
            if not line.startswith('#'):
                try:
                    services.remove(line)  # remove service from the list
                except ValueError:
                    print('-W-: %s not in service list' % line)

        print('-I- Excluding service(s): ',
              [x for x in filter(None, lines.split('\n')) if not x.startswith('#')])

        return services
    

    def get_disks(self) -> Iterator[str]:
        """sosmgr command returns strings for primary and cache disks"""

        # get service names and check for excluding services
        if self.excluded_file.exists():
            print('-I- Found service(s) to be excluded')
            services = self.exclude_services(self.excluded_file)
        else:
            services = self.get_services()

        # This command gives primary and cache paths of all services
        sos_cmd = "/opt/cliosoft/latest/bin/sosmgr service get -o csv -cpa -pp -pcl -s " + ','.join(services)
        p = subprocess.run(sos_cmd, capture_output=True, check=True, text=True, shell=True)
        if p.returncode: print(p.stderr)

        # split string to lines and also filter empty lines
        for line in filter(None, p.stdout.split('\n')):
            yield line.rstrip().split(',')  # split() for a list
            

    def create_disk_file(self, disk_file) -> None:
        """Write primary and cache paths to file"""

        seen = set()
        with open(disk_file, 'w', newline='') as file:
            for line in self.get_disks():
                if re.match(r'/bsite/b', line[0]): continue  # skip header row
                # os.path gives string, pathlib.Path gives instance
                cache = os.path.dirname(line[2])
                locality = line[3].lower()
                repo = os.path.dirname(line[4])
                

                if locality.lower() == 'local' and repo not in seen:
                    seen.add(repo)          # use set to track disk names
                    file.write(repo + '\n') # file.write works with string
                if cache not in seen:
                    seen.add(cache)         # use set to track disk names
                    file.write(cache + '\n')

        # unix sed command to substitute string 'sitecode' to  string 'site' on the disk
        # str(PosixPath) prevents error "can only concatenate str (not "PosixPath") to str"
        subprocess.run("sed -i 's:^/nfs/.*/disks:/nfs/site/disks:g' " + str(disk_file), check=True, shell=True)


    def disk_space_status(self, disk: str):
        """Available disk space. See shutil mode for more info
        (2**30) converts bytes to GB, // keeps only integer number
        """
        if self: return [x // (2**30) for x in shutil.disk_usage(disk)]


def main():

    # Requires SOS_SERVERS_DIR variable if not already set in the environment 
    # os.environ['SOS_SERVERS_DIR'] = '/nfs/site/disks/sos_adm/share/SERVERS7'

    import utils as util

    sos = SiteSOS('ddm')
    LIMIT: int = 250  # threshold disk size value 250GB
    recipient = "linh.a.nguyen@intel.com"

    disk_file = Path(data_path, sos.disk_file)

    if not disk_file.exists():
        print('-I- Create disk file')
        sos.create_disk_file(disk_file)

    if util.file_older_than(disk_file, day=1):  # older than 1 day
        try:
            print('Data file is more than a day old...Recreate data file')
            os.remove(disk_file)
            sos.create_disk_file(disk_file)
        except OSError:
            print('-E- Failed to remove data file')

    ### demo code
    # disk = /nfs/site/disks/hipipde_soscache_010 (pdx)
    # _disk = '/nfs/site/disks/hipipde.sosrepo.007'
    # _disk = '/nfs/site/disks/ddmtest_sosrepo_001'
    # _size, _space = sos.disk_space_status(_disk)
    # util.increase_disk_size(_disk, 1000)
    # print(util.has_size_been_increased(_disk))
    ###

    # check each disk for available space
    # disks = []
    with open(disk_file, 'r') as f:
        disks = f.read().splitlines()

    # check each disk for available space 
    msg = ''
    for disk in sorted(disks, key=os.path.basename):
        #disk_size, _, avail_space = sos.disk_space_status(disk)
        disk_size, _, avail_space = sos.disk_space_status(disk)
        
        if avail_space < LIMIT:
            msg += f"{disk} Size(GB): {disk_size}; Avail(GB): {avail_space} *** Low disk space" + '\n'

            # Test 1:
            # Test if it is sending email
            # Option 2:
            # sos.increase_disk_size(disk, 50)
            #   email status/error

        else:
            print(f"{disk} [ Size(GB): {disk_size}; Avail(GB): {avail_space} ]")

    # email users
    if msg:
        import email_user as m
        subject = f"Alert: {sos.site} Cliosoft disk is low on space"
        to_email = recipient
        from_email = recipient
        # m.send_email(subject, msg, to_email, from_email)
        pp(msg)


if __name__ == '__main__':
    main()

# # Release the lock (optional)
# os.close(lock_fd)
# os.unlink(lock_file)
