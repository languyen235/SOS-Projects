import os
import re
from pathlib import Path

# Cliosoft Paths
SOS_ADMIN_CMD = "/opt/cliosoft/latest/bin/sosadmin"
SOS_MGR_CMD = "/opt/cliosoft/latest/bin/sosmgr"
SERVICE_DIR_LINK = '/opt/cliosoft/latest/SERVERS'
DEFAULT_SERVICE_DIR = '/nfs/site/disks/sos_adm/share/SERVERS7'

# Cliosoft env variables
CLIOSOFT_DIR = '/opt/cliosoft/latest'
REAL_SERVICE_DIR = os.path.realpath(SERVICE_DIR_LINK)  # real path of the sos_servers_dir
IS_REPLICA = re.search(r'(replica)', REAL_SERVICE_DIR)  # replica keyword found in the path name
SOS_SERVER_ROLE = 'replica' if IS_REPLICA else 'repo'

# Thresholds
LOW_SPACE_THRESHOLD_GB = 250
# DEFAULT_ADD_DISK_SIZE_GB = 500
ADDING_DISK_SIZE_GB = 500
DISK_SIZE_INCREASE_DAYS = 2

# Timeouts
COMMAND_TIMEOUT = 30  # seconds

# Email Settings
DDM_CONTACTS = ['linh.a.nguyen@intel.com']
SENDER = "linh.a.nguyen@intel.com"

# File Paths
MONITORING_BASE_DIR = Path('/opt/cliosoft/monitoring')
DATA_DIR = MONITORING_BASE_DIR / 'data'
LOG_DIR = MONITORING_BASE_DIR / 'logs'
LOG_FILE = LOG_DIR / 'sos_check_disk_usage.log'
EXCLUDED_SERVICES_FILE = DATA_DIR / 'excluded_services.txt'

# Site Configuration
SITES = ['sc', 'sc1', 'sc4', 'sc8', 'pdx', 'iil', 'png', 'iind', 'altera_sc', 'altera_png', 'vr']

# Logging Configuration
LOG_FORMAT = '[%(asctime)s] [%(name)s] [%(funcName)s] [%(levelname)s] %(message)s'
LOG_LEVEL = 'INFO'  # Can be overridden by environment variable

# Ensure required directories exist
for directory in [DATA_DIR, LOG_DIR]:
    directory.mkdir(parents=True, exist_ok=True, mode=0o775)
