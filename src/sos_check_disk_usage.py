#!/opt/cliosoft/monitoring/venv/bin/python3.12

import sys
import json
import logging

# Add the parent directory to modules
sys.path.append('/opt/cliosoft/monitoring')

from modules.sos_module_1 import *
from config.settings import *
from utils.helpers import *

class SosDiskMonitor:
    """Setup Cliosoft application service"""
    def __init__(self, site):
        """Initialize instance attributes and load environment data."""
        self.site = site.upper()
        self.server_role = None
        self.web_url = None
        self.site_name = None
        self.data_file = DATA_DIR / f"{self.site}_cliosoft_disks.txt"
        self.env_json_file = DATA_DIR / f'{self.site}_sos_env.json'
        self.load_env_data()

    def load_env_data(self):
        """Load environment data from file or initialize new configuration."""
        if self.env_json_file.exists():
            self.load_sos_env_vars_from_file()
        else:
            self.set_sos_env_variables()
            self.save_env_data()


    def load_sos_env_vars_from_file(self):
        """Load environment variables from JSON file and update SOS environment variables."""
        data = read_env_file(self.env_json_file)

        # Update instance variables
        self.site_name = data['site_name']
        self.web_url = data['site_url']

        # Update OS environment
        os.environ.update({
            'SOS_SERVERS_DIR': data['sos_servers_dir'],
            'CLIOSOFT_DIR': data['sos_cliosoft_dir'],
            'SOS_SERVER_ROLE': data['server_role'],
            'EC_ZONE': data['ec_zone'],
            'PATH': f"{os.environ['CLIOSOFT_DIR']}/bin:{os.environ['PATH']}"
        })

    def set_sos_env_variables(self):
        """Initialize SOS environment variables with default values."""
        os.environ.update({
            'CLIOSOFT_DIR': '/opt/cliosoft/latest',
            'SOS_SERVERS_DIR': get_service_dir(self.site),
            'EC_ZONE': self.site,
            'SOS_SERVER_ROLE': SOS_SERVER_ROLE,
            'PATH': f"{os.environ['CLIOSOFT_DIR']}/bin:{os.environ['PATH']}"
        })
        self.site_name, self.web_url = get_sitename_and_url()

    def save_env_data(self):
        """Save SOS environment variables to JSON file"""
        data = {
            'site_name': self.site_name,
            'site_url': self.web_url,
            'server_role': os.environ['SOS_SERVER_ROLE'],
            'sos_servers_dir': os.environ['SOS_SERVERS_DIR'],
            'sos_cliosoft_dir': os.environ['CLIOSOFT_DIR'],
            'ec_zone': os.environ['EC_ZONE']
        }
        try:
            with open(self.env_json_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except OSError as error:
            logger.error("Failed to write environment data file: %s", error)
            raise


def initialize_service(cli_args, class_name):
    """
    This function initializes the class service based on the test mode with site code ('ddm')
    or in production mode using the current site code.
    Args:
        cli_args: Command line arguments
        class_name: Class to initialize (e.g. SosDiskMonitor)
    Returns:
        An instance of the class
    """
    if cli_args.test_mode:
        logger.debug('Running script on DDM test server')
        return class_name('ddm')
    else:
        return class_name(site_code())



def main() -> int:
    """
    Main function to monitor and manage SOS disk usage.
    This function:
    1. Processes command line arguments
    2. Initializes the monitoring service
    3. Checks SOS web service status
    4. Refreshes disk data if needed
    5. Monitors disk space and handles low space scenarios
    6. Logs and reports any errors

    Returns:
        int: 0 on success, 1 on failure
    """
    try:
        logger.info("Starting disk monitoring process")

        # Process command line arguments
        cli_args = process_command_line()
        logger.debug("Command line arguments processed: %s", vars(cli_args))

        # Initialize service
        try:
            sos_monitor = initialize_service(cli_args, SosDiskMonitor)
            logger.info("Service initialized for site: %s", sos_monitor.site.upper())
        except Exception as error:
            logger.critical("Failed to initialize service: %s", str(error), exc_info=True)
            return 1

        # Check web service status
        try:
            if not check_web_status(sos_monitor.web_url):
                logger.error("Web service check failed for %s", sos_monitor.web_url)
                return 1
            logger.debug("Web service is responsive")
        except Exception as error:
            logger.error("Error checking web service status: %s", str(error))
            return 1

        # Refresh disk data if needed
        try:
            if cli_args.disk_refresh or not sos_monitor.data_file.exists():
                logger.info("Refreshing disk data file")
                prepare_disks_file(sos_monitor.data_file)
                logger.debug("Disk data file refreshed at %s", sos_monitor.data_file)
        except Exception as error:
            logger.error("Failed to prepare disk data file: %s", str(error))
            return 1

        # Check disk space
        try:
            disk_data = sos_monitor.data_file.read_text(encoding='utf-8').strip()
            if not disk_data:
                logger.error("Disk data file is empty")
                return 1

            disks = disk_data.splitlines()
            all_disks, low_space_disks = disk_space_info(disks, LOW_SPACE_THRESHOLD_GB)

            if low_space_disks:
                disk_size_to_add = ADDING_DISK_SIZE_GB if cli_args.add_size else 0
                logger.warning("Low disk space detected on %d volumes", len(low_space_disks))
                handle_low_disk_space(low_space_disks, disk_size_to_add)
            else:
                logger.info("All disks have sufficient space")

            # Save disk usage to CSV
            csv_file = DATA_DIR / f"{sos_monitor.site.upper()}_disk_usages.csv"
            write_to_csv_file(csv_file, all_disks)
            logger.debug("Disk usage report saved to %s", csv_file)

        except Exception as error:
            logger.error("Error processing disk information: %s", str(error), exc_info=True)
            return 1

        # Check for errors in log and notify if needed
        if error_messages := read_log_for_errors(LOG_FILE):
            subject = f"Cliosoft Alert: {sos_monitor.site.upper()} disk monitoring detected issues"
            try:
                send_email_alert(subject, error_messages)
                rotate_log_file(LOG_FILE)
                logger.warning("Sent notification for detected errors")
            except Exception as error:
                logger.error("Failed to send notification: %s", str(error))
                return 1
            return 1

        logger.info("%s disk space monitoring completed successfully", sos_monitor.site.upper())
        return 0

    except Exception as Error:
        logger.critical("Unexpected error in main(): %s", str(Error), exc_info=True)
        return 1


#-----  Main   -----
if __name__ == '__main__':
    # Set up file locking to prevent multiple instances
    LOCK_FILE = "/tmp/sos_check_disks.lock"
    lock_fd = lock_script(LOCK_FILE) # Acquire the lock
    logger = setup_logging(LOG_FILE)

    try:
        # Run main application
        sys.exit(main())
    except Exception as e:
        logger.error("Fatal error in main execution: %s", str(e), exc_info=True)
        sys.exit(1)
    finally:
        # Cleanup resources
        if lock_fd is not None:
            try:
                os.close(lock_fd)
                os.unlink(LOCK_FILE)
            except OSError as e:
                if logger:
                    logger.warning("Failed to clean up lock file: %s", str(e))

        logging.shutdown()
