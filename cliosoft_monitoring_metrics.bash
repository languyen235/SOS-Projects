#!/bin/bash
#

# Purpose: script test primary and cache services and write status to Prometheus 
#
# Requirements: Cliosoft software installed on server at /opt/cliosoft


# enable error trap 
set -exuo pipefail 

# Script will not copy the promp file at /dsm/prom../testfile if DEBUG=on
set +u; arg=$1
DEBUG=off
[[ $arg == -d ]] && { echo '-I: Debug mode is on'; DEBUG=on; } && set -u

# global variable $CLIOSOFT_DIR must have been set
[[ -z $CLIOSOFT_DIR ]] && { export CLIOSOFT_DIR=/opt/cliosoft/latest; export PATH=$CLIOSOFT_DIR/bin:$PATH; } || true
[[ -e "$CLIOSOFT_DIR"/bin ]] || { echo '-F: Cliosoft binary not found'; exit 1; }
site="$EC_ZONE"



#----
create_data_file () {
# Run sos info to find service names, ports, roles, and disks and save the results to a file for future reference.
hostname=$(hostname)
db="$data_file"

#each query returns infomation of primary (local or remote) and cache
#> sosadmin info ddm_test
#Server name:            ddm_test
#Primary server type:    REMOTE
#Primary host:           scysync31.sc.intel.com
#Primary command port:   13202
#Primary repository path:/nfs/site/disks/sos_eval_scm/ddm_test.repo
#Primary backup:
#Client Authentication:  ?
#Cache server type:      LOCAL
#Cache host:             scysync29.sc.intel.com
#Cache command port:     13203
#Cache path:             /infrastructure/sos_storage/ddm_test.cache

    # This sos command  should not take more than 3s or exit error
    if ! /usr/bin/timeout 3s sosadmin list; then
        echo "-F: Cliosoft command timeout occurred."
        exit 1
    else
        readarray -t services < <(sosadmin list)
    fi

    # iterate each primary and cache service in array
    for service in "${services[@]}"
    do
		# store inputs  to variables
        while read -r primary_host primary_port primary_path cache_host cache_port cache_path
        do
            # remove trailing .<site>.intel.com
            primary_host="${primary_host%%.*}" && cache_host="${cache_host%%.*}"

            # primary's hostname matches this monitoring host, save both primary and cache info
            if [[ $primary_host =~ $hostname ]]; then
                echo "$service,$primary_host,repo,$primary_port,$primary_path" >> "$db"  # output repo server metrics to file
                echo "$service,$cache_host,cache,$cache_port,$cache_path" >> "$db"      # output cache server metrics to file
            # primary_host doesn't match hostname but cache matches, save ony cache info
            elif [[ $cache_host =~ $hostname ]]; then
                echo "$service,$cache_host,remote_cache,$cache_port,$cache_path" >> "$db"   # save remote cache server metrics to file
            else
                continue  # next service name in the array
            fi

        # inside of <<< $(...) command subtitution
        # run sosadmin info command of each serivce and  pipe output to grep.
        # grep lines starting with word Primary or Cache following with \s+, optional (\w+\s+)?, host|port|path,colon (:)
        # the \K ignores all previous matched groups
        # print the last non-space matches (\S+) group
        done <<< $(sosadmin info "$service" | grep -Po '(?x)^(Primary|Cache) \s+ (\w+\s+)? (host|port|path): (\s+)? \K (\S+)')
    done

    [[ "$?" -eq 0 ]] || { echo "-E: generate_csv_file was uncessful"; exit 1; }
} # End create_data_file

#----
check_data_file () {
# Check to see if a csv file exists and is less than a day old.

    # return 0 (true). Return 1 (fail)
    if [[ ! -e $data_file ]]; then
		echo "-I: $data_file not found..Will create a new file"
        echo 1
    # 60min x 24 = 1440
    elif  [[ $(find "$data_file" -mmin +1440) ]]; then
        echo "-I: $data_file was more than a day old... Will create a new file"
		rm -f "$data_file" || echo "-E: Could not delete $data_file"
        echo 1
	else
		echo "-I: $data_file is a day old. Will not create file again"
        echo 0
    fi
} # End check_data_file


#----
rename_prom_file () {
# move prom file to dsm location
sfile=$1
dfile=$2
[[ -e $sfile ]] || { echo "-F: Source file not found"; exit 1; } 

    if [[ "$DEBUG" == off ]]; then
        chmod 755 "$prom_file"
        # if new prom file missing due to any errors, remove previous promp file and possibly raise alerts
        mv "$sfile" "$dfile" || { echo "-F: Failed to rename file"; rm -f $dfile; exit 1; }
    else
        echo '-W: Debug mode was on... Will not rename prom file'
    fi
} # End rename_prom_file

#----
monitor_sos_service () {
# print status of repos and cache services to prom file
#local fname=${dsm_location}/check_sos_service.prom
local tmpfile=${script_path}/check_sos_service.$$

	# promp file headers
	echo "# HELP sos_service_check Check if SOS service is running" > "$tmpfile"
	echo "# TYPE sos_service_check  gauge" >> "$tmpfile"

	# reading the csv file with , deleminator and save data to variables
	while IFS=, read -r _service _host _role _port 
	do
		# sosadmin ping command  returns status of primary and cache service
		# grep: search for a word after discard all previously matches (\K)
		# save results to p_status c_status variables
		read  -r p_status c_status  <<< $(sosadmin ping $_service | grep -Po '^\s+Status:\s+\K\w+')  
		[[ $p_status == Running ]] && p_result=0 || { p_result=1; p_status='Not_Running'; }  
		[[ $c_status == Running ]] && c_result=0 || { c_result=1; c_status='Not_Running'; }

		case $_role in 
			repo) 
				echo "sos_service_check{site="$site",hostname="$_host",service="$_service",role="$_role",status="$p_status"}" "$p_result" >> "$tmpfile"
				;;
			cache)
				echo "sos_service_check{site="$site",hostname="$_host",service="$_service",role="$_role",status="$c_status"}" "$c_result" >> "$tmpfile"
				;;
			remote_cache)
				echo "sos_service_check{site="$site",hostname="$_host",service="$_service",role="$_role",status="$c_status"}" "$c_result" >> "$tmpfile"
				;;
			*)
				echo "-F: I can't determine service role"
				echo "-I: Role: $_role"
				exit 1
				;;
		esac
	done <"$data_file"

	local promfile=${prom_location}/check_sos_service.prom
	rename_prom_file "$tmpfile" "$promfile"
	
} # End monitor_sos_service()


#----
main() {
#source $(dirname "$0")/utils.bash
script_path=$(dirname "$0")
data_file="${script_path}/data.csv"
prom_location=/dsm/prom_exporter/textfile

	[[ $(check_data_file | tail -n 1) -eq 0  ]] || create_data_file
	monitor_sos_service

} # End main()

main

















