#!/bin/bash
# venv_functions.sh
# Description: Utility functions for creatingPython virtual environments base on SLES version

# Constants

declare -r BASE_DIR="/opt/cliosoft/monitoring"
declare VENV_LOG_FILE="$BASE_DIR/logs/venv_functions.log"
declare -r SCRIPT_DIR="$BASE_DIR/scripts"
[[ ! -d $BASE_DIR/logs ]] && mkdir -p "$BASE_DIR/logs"

declare -r DEFAULT_INTERPRETER="/usr/intel/bin/python3"
delare -r  ALTERNATE_INTERPRETER='/usr/intel/pkgs/python3/3.12.3/bin/python3'

# Set proxy
export HTTP_PROXY=http://proxy-dmz.intel.com:912
export HTTPS_PROXY=http://proxy-dmz.intel.com:912

declare VENV_PATH
declare OS_VERSION

# Function to activate Python venv based on OS
get_os_version() {
  # Get OS version from /etc/os-release
  log_debug "Verifying OS version..."
  OS=$(grep VERSION_ID /etc/os-release | cut -d'=' -f2 | tr -d '"')

  # Set Python virtual environment folder location by OS version
  case "$OS" in
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
  log_debug "OS: $OS_VERSION; VENV path: $VENV_PATH"
}

create_python_venv() {
  # Create virtual environment for Python whether OS SLES12 or SLES15

  case "$OS_VERSION" in
    12*)
      mypython3="$ALTERNATE_PYTHON_FILE"
      ;;
    15.4)
      mypython3="$ALTERNATE_PYTHON_FILE"
      ;;
    15.7)
      mypython3="$DEFAULT_INTERPRETER"
      ;;
    *)
      log_error "Unsupported OS version: $OS_VERSION"
      return 1
  esac

  if ! $mypython3 -m venv "$VENV_PATH"; then
    log_error "Failed to create virtual environment"
    return 1
  fi

  log_debug "Python version: $($mypython3 --version)"
  return 0
}

activate_python_venv() {
  # Activate virtual environment
  if ! source "${VENV_PATH}/bin/activate"; then
    log_error "Failed to activate virtual environment"
    return 1
  fi

  log_debug "Python version: $(python3 --version)"
  return 0
}


check_requests_lib() {
  # Check if requests library is installed
  if ! python3 -c "import requests"; then
    log_error "Requests library is not installed"
    return 1
  fi

  log_debug "Requests library is installed"
  return 0
}


install_python_libs() {
  # Install Python requirements.txt
  if ! python3 -m pip install -r "$BASE_DIR/requirements.txt"; then
    log_error "Failed to install Python requirements"
    return 1
  fi

  log_debug "Python requirements installed successfully"
  return 0
}


run_with_venv() {
  # Run script with python venv
  local args=("$@")
  python3 "${args[@]}"
  log_debug "Script executed successfully"
  deactivate
  return 0
}


main() {
  local args=("$@")
  get_os_version

  # Create virtual environment
  if [[ -d "$VENV_PATH" ]]; then
    log_debug "Activating virtual environment..."
    if ! activate_python_venv; then
      log_error "Failed to activate virtual environment"
      exit 1
    fi
  else
    return_codes=()
    log_debug "Creating virtual environment at $VENV_PATH"
    create_python_venv
    return_codes+=($?)
    activate_python_venv
    return_codes+=($?)
    install_python_libs
    return_codes+=($?)

    for code in "${return_codes[@]}"; do
      if [[ $code -ne 0 ]]; then
          log_error "Failed to create virtual environment"
          exit 1
      fi
    done
  fi

  # Run script in virtual environment
  run_with_venv "${args[@]}"
}

help() {
  echo "Usage: $0 <Python script> [python script arguments] [-d|--debug]"
}


#----------------
# Main execution block
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  # Default values
  DEBUG=0
  args=("$@")
  echo "args: ${args[*]}"

  # Check for debug flag in any position
  for arg in "$@"; do
    if [[ "$arg" == "--debug" || "$arg" == "-d" ]]; then
        DEBUG=1
        # export LOG_LEVEL=DEBUG
        # Remove debug flag from arguments so it doesn't get passed to Python script
        unset "args[-1]"
        break
    fi
  done

  # Source logging functions with the determined debug level
  source "$SCRIPT_DIR/log_functions.bash" "$DEBUG" "$VENV_LOG_FILE"

  # If no arguments provided, show help
  if [[ ${#args[@]} -eq 0 ]]; then
    help
    exit 1
  fi

  # Pass remaining arguments to main
  main "${args[@]}"
fi