#!/bin/bash
# venv_functions.sh
# Description: Utility functions for creatingPython virtual environments base on SLES version

# Constants
declare -r BASE_DIR="/opt/cliosoft/monitoring"
declare -r SERVICE_DIR="/opt/cliosoft/monitoring/replica_service"
[[ -d "$SERVICE_DIR" ]] && mkdir -p "$SERVICE_DIR"

# declare -r SRC_DIR="/opt/cliosoft/monitoring/tests"
# declare -r SCRIPT_NAME="tests.py"
declare VENV_PATH
declare OS_VERSION
declare -r DEFAULT_PYTHON_FILE="/usr/intel/bin/python3"
declare LOG_FILE="$SERVICE_DIR/venv_functions.log"
# Set proxy
export HTTPS_PROXY=http://proxy-dmz.intel.com:912
export HTTPS_PROXY=http://proxy-dmz.intel.com:912

# Function to activate Python venv based on OS
verify_os_version() {
  local os_version

  # Get OS version from /etc/os-release
  os_version=$(grep VERSION_ID /etc/os-release | cut -d'=' -f2 | tr -d '"')

  # Set virtual environment path
  # For SLES12 and SLES15.4 use venv_312; Otherwise use venv_313 (python 3.13.2)
  case "$os_version" in
    12*)
      VENV_PATH="$BASE_DIR/venv_312"
      OS_VERSION="SLES12"
      ;;
    15.4)
      VENV_PATH="$BASE_DIR/venv_312"
      OS_VERSION="SLES15-SP4"
      ;;
    15.7)
      VENV_PATH="$BASE_DIR/venv_313"
      OS_VERSION="SLES15-SP7"
      ;;
  esac
}

activate_python_venv() {
  # Activate virtual environment
  if [[ -f "${VENV_PATH}/bin/activate" ]]; then
    log "INFO" "Activating: ${VENV_PATH}"
    source "${VENV_PATH}/bin/activate"
    return 0
  else
    log "ERROR" "venv not found: $BASE_DIR" >&2
    return 1
  fi
}

create_python_venv() {
  # Create virtual environment
  echo "Creating virtual environment: $VENV_PATH"
  if [[ ${OS_VERSION} == "SLES12" || ${OS_VERSION} == "SLES15-SP4" ]]; then
    mypython3='/usr/intel/pkgs/python3/3.12.3/bin/python3'
  elif [[ ${OS_VERSION} == 'SLES15-SP7' ]]; then
    mypython3='/usr/intel/bin/python3'
  else
    log "ERROR" "Unsupported OS version: $OS_VERSION" >&2
    return 1
  fi

  if ! $mypython3 -m venv "$VENV_PATH"; then
    echo "ERROR: Failed to create virtual environment" >&2
    return 1
  fi
}


install_python_libs() {
  # Install Python requirements.txt
  check_reqs=$(python3 -c "import requests" && echo "Passed" || echo "Failed")
  # log "INFO" "Requests module check result: $check_reqs" >&2
  if [[ $check_reqs == "Failed" ]]; then
    log "INFO" "Installing requirements.txt"
    if ! python3 -m pip install -r "$BASE_DIR/requirements.txt"; then
      log "ERROR" "Failed to install Python requirements" >&2
      return 1
    fi
  fi
}


run_with_venv() {
  # Run script with venv
  local args=("$@")

  if [[ $(which python3) == "$DEFAULT_PYTHON_FILE" ]]; then
    log "ERROR" "Failed to run Python in virtual environment" >&2
    return 1
  else
    log "INFO" "Python virtual environment path: $(which python3)"
    python3 "${args[@]}"
  fi
}

log() {
  local level="$1"
  local message="${*:2}"
  local timestamp
  timestamp=$(date +"%Y-%m-%d %H:%M:%S")
  echo "$timestamp [$level] $message" | tee -a "$LOG_FILE"
}


main() {
  local args=("$@")

  log "DEBUG" "Verifying OS version"
  verify_os_version
  log "INFO" "OS version: $OS_VERSION" >&2
  log "DEBUG" "Virtual environment path: $VENV_PATH" >&2

  # Create virtual environment
  if [[ ! -d "$VENV_PATH" ]]; then
    log "INFO" "Creating virtual environment at $VENV_PATH"
    create_python_venv
  else
    log "DEBUG" "Virtual environment already exists at $VENV_PATH"
  fi

  # Activate virtual environment and install Python required libs if missing
  log "DEBUG" "Activating virtual environment..."
  if ! activate_python_venv; then
    # log "ERROR" "Failed to activate virtual environment"
    exit 1
  fi

  log "INFO" "Installing/verifying Python libraries..."
  if ! install_python_libs; then
    # log "ERROR" "Failed to install Python libraries"
    exit 1
  fi

  # Run script with venv
  if ! run_with_venv "${args[@]}"; then
    # log "ERROR" "Command failed with exit code $?"
    exit 1
  fi
}

  log "INFO" "Script executed successfully"

#----
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi

