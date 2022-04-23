#!/bin/bash
#

# Purpose: script test primary and cache services and write status to Prometheus 
#
# Requirements: Cliosoft software installed on server at /opt/cliosoft


# enable error trap 
set -exuo pipefail 
trap "echo ERROR: There was error in ${FUNCTION-main context}" ERR

# turn  debug mode. Script will not copy the promp file at /dsm/prom../testfile if DEBUG=on
set +u; arg=$1
DEBUG=off
[[ $arg == -d ]] && { echo '-I: Debug mode is on'; DEBUG=on; } && set -u

# global variable $CLIOSOFT_DIR must have been set
[[ -z $CLIOSOFT_DIR ]] && { export CLIOSOFT_DIR=/opt/cliosoft/latest; export PATH=$CLIOSOFT_DIR/bin:$PATH; } || true

[[ -e "$CLIOSOFT_DIR"/bin ]] || { echo '-F: Cliosoft binary not found'; exit 1; }

site="$EC_ZONE"

#----
generate_prom_file () {
# print status of repos and cache services to prom file
data_file=$1
fname=$2 

# start with new prom file
[[ -e $fname ]] && rm -f "$fname" || true

	# promp file headers
	echo "# HELP sos_health_check Checking if SOS service is running" > "$fname"
	echo "# TYPE sos_health_check  gauge" >> "$fname"

	# reading the csv file with , deleminator and save data to variables
	while IFS=, read -r _service _host _role _port 
	do
		# Default is 0
		#p_result=0
		#c_result=0
		
		# sosadmin ping command  returns real status of primary and cache service
		# I save status in p_status c_status variables
		read  -r p_status c_status  <<< $(sosadmin ping $_service | perl -lne 'print $1 if /^\s+Status:\s+\K(\w+)/')

		[[ $p_status == Running ]] && p_result=0 || { p_result=1; p_status='Not_Running'; }  

		[[ $c_status == Running ]] && c_result=0 || { c_result=1; c_status='Not_Running'; }


		# case 1: role is repo i
		if [[ $_role == repo ]]; then
			echo "sos_health_check{site="$site",hostname="$_host",service="$_service",role="$_role",status="$p_status"}" "$p_result" >> "$fname"
		elif [[ $_role == cache ]]; then
			echo "sos_health_check{site="$site",hostname="$_host",service="$_service",role="$_role",status="$c_status"}" "$c_result" >> "$fname"
		elif [[ $_role == remote_cache ]]; then
			echo "sos_health_check{site="$site",hostname="$_host",service="$_service",role="$_role",status="$c_status"}" "$c_result" >> "$fname"
		else
			echo "-F: I can't determine service role"
			echo "-I: Role: $_role"
			exit 1
		fi
	done <"$data_file"
} # End generate_prom_file


#----
remove_lock () {
    echo "-I: Remove lock dir"
	rm -rf "$LOCK_DIR"  || echo "-F: Cannot remore lock dir"
}

#----
main() {
source $(dirname "$0")/utils.bash
script_path=/opt/cliosoft/monitoring/scripts
lookup_file="${script_path}/data.csv"
prom_file="${script_path}/sos_health_check.prom"
prom_location=/dsm/prom_exporter/textfile
LOCK_DIR=/tmp/sos_lockdir

	# if verify_lookup_file fails, create file
	#if [[ $(verify_lookup_file "$lookup_file" "$LOCK_DIR" | tail -n 1) ]];  then
	verify_lookup_file "$lookup_file" "$LOCK_DIR" 
	if [[ "$?" -eq 1 ]]; then
		echo '-I: Create lock dir'
		mkdir -p "$LOCK_DIR" ||  { echo "-F: Cannot create lock dir"; exit 2; }
		trap cleanup INT KILL
		generate_lookup_file "$lookup_file"
		remove_lock
	fi	
	
	generate_prom_file "$lookup_file" "$prom_file"

	if [[ "$DEBUG" == off ]]; then
		chmod 644 "$fname"
		# if new prom file missing due to any errors, remove previous promp file and possibly raise alerts
		mv "$prom_file" "$prom_location" || rm -f "${prom_location}/${prom_file}"
	fi
}

main
exit $?


















