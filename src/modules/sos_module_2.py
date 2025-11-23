# Add the parent directory to modules
import sys
sys.path.append('/opt/cliosoft/monitoring')

from src.config.settings import *
from src.modules.sos_module_1 import *

logger = logging.getLogger(__name__)

#-------------
def lock_script(lock_file: str):
    """
    Locks a file pertaining to this script so that it cannot be run simultaneously.

    Since the lock is automatically released when this script ends, there is no
    need for an unlock function for this use case.

    Returns:
        lockfile if lock was acquired. Otherwise, print error and exists.
    """
    import fcntl
    try:
        # Try to acquire an exclusive lock on the file
        lock_handle = os.open(lock_file, os.O_CREAT | os.O_RDWR, mode=0o644)
        fcntl.lockf(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_handle
    except IOError:
        logger.warning("Another instance of the script is already running.")
        sys.exit(1)


def site_code():
    """Returns this site code"""
    import socket
    return socket.getfqdn().split('.')[1]


def file_older_than(file_path: str | os.PathLike, num_day: int=1):
    """Return true if file is older than number of days"""
    time_difference = time.time() - os.path.getmtime(file_path)
    seconds_in_a_day = 86400  # 24 * 60 * 60

    if time_difference > (seconds_in_a_day * num_day):
        return True
    else:
        return False


def create_file_decorator(func: Callable) -> Callable:
    """
    Decorator to handle data file creation with automatic refresh.
    Delete and re-create file if file is older than a day
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        ifile = args[0]
        try:
            # If file exists and is older than 1 day, remove it
            if ifile.exists() and file_older_than(ifile, num_day=1):
                logger.info('Data file is more than a day old. Removing old file...')
                ifile.unlink()

            # If file doesn't exist (either didn't exist or was just removed)
            if not ifile.exists():
                logger.info('Creating new data file...')
                return func(*args, **kwargs)

            logger.debug('Using existing data file (less than a day old)')
            return None

        except OSError as file_error:
            logger.error("Error handling data file %s: %s", ifile, file_error)
            raise
    return wrapper

@create_file_decorator
def create_disks_file(disk_file: Path) -> None:
    """
    Creates a data file containing paths of primary and cache disks for Cliosoft.
    This function retrieves disk information, filters it, and writes the relevant paths to the specified data file.
    Parameters:
        disk_file (Path): The path where the data file will be created.
    Raises:
        OSError: If there is an error during file creation or writing.
    """
    logger.info('Creating disk file at %s', disk_file)
    found_disks: set[Path] = set()

    def write_disk_path(disk_path: Path, seen_disks: set[Path], file_handle: TextIO) -> None:
        """Helper function to write disk path if not already seen."""
        if disk_path not in seen_disks:
            seen_disks.add(disk_path)
            file_handle.write(f"{disk_path}\n")

    sos_services = get_sos_services()

    try:
        with open(disk_file, 'w', newline='', encoding='utf-8') as file:
            for row in get_sos_disks(sos_services):
                if len(row) > 5:   # Replica server format
                    replica_dir = get_pg_data_parent(Path(row[-1]), depth=5)
                    write_disk_path(replica_dir, found_disks, file)
                    continue

                if  row[-2].lower() == 'local':
                    repo_dir = get_pg_data_parent(Path(row[-1]), depth=5)
                    write_disk_path(repo_dir, found_disks, file)

                cache_dir = get_pg_data_parent(Path(row[-3]), depth=5)
                write_disk_path(cache_dir, found_disks, file)

        # Normalize the paths in the data file
        subprocess.run(
            ["sed", "-i", "s:^/nfs/.*/disks:/nfs/site/disks:g", str(disk_file)],
            check=True
        )

    except OSError as err:
        logger.error("Failed to create data file: %s", err)
        raise


def send_email_alert(subject: str, message: list[str]) -> bool:
    """
    Send email notification to DDM contacts.
    Args:
        subject: Email subject
        message: Email body content
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        send_email(subject, message, DDM_CONTACTS, SENDER)
        return True
    except Exception as error:
        logger.error("Failed to send email: %s", error)
        return False


__all__ = [ 'lock_script', 'site_code', 'file_older_than', 'create_file_decorator',
            'create_disks_file', 'send_email_alert'
        ]
