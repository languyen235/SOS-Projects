#!/bin/bash
#

# Purpose: script test primary and cache services and write status to Prometheus 
# Requirements: Cliosoft software installed on server at /opt/cliosoft


# enable error trap 
#set -xuo pipefail 

## Script will not copy the promp file at /dsm/prom../testfile if DEBUG=on
set +u; arg=$1
DEBUG=off
[[ $arg == -d ]] && { echo '-I: Debug mode is on'; DEBUG=on; } && set -u

# global variable $CLIOSOFT_DIR must have been set
[[ -z $CLIOSOFT_DIR ]] && { export CLIOSOFT_DIR=/opt/cliosoft/latest; export PATH=$CLIOSOFT_DIR/bin:$PATH; } || true
[[ -e "$CLIOSOFT_DIR"/bin ]] || { echo '-F: Cliosoft binary not found'; exit 1; }
site="$EC_ZONE"
hostname=$(hostname)


#----
create_data_file () {
# Run sos info to find service names, ports, roles, and disks and save the results to a file for future reference.
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
        exit 10
    else
        readarray -t services < <(sosadmin list)
    fi

	# if array is empty, exit script with error
	[[ ${#serivces[@]} -gt 0 ]] || { echo "-F: Array is empty"; exit 10; }

    # iterate each primary and cache service in array
    for service in "${services[@]}"
    do
		# store inputs  to variables
        while read -r primary_host primary_port primary_path cache_host cache_port cache_path
        do
            # remove trailing .<site>.intel.com
            primary_host="${primary_host%%.*}" && cache_host="${cache_host%%.*}"

            # primary's hostname matches this monitoring host, save both primary and cache info
            if [[ $primary_host == $hostname ]]; then
                echo "$service,$primary_host,repo,$primary_port,$primary_path" >> "$data_file"  # output repo server metrics to file
                echo "$service,$cache_host,cache,$cache_port,$cache_path" >> "$data_file"      # output cache server metrics to file
            # primary_host doesn't match hostname but cache matches, save ony cache info
            #elif [[ $cache_host != $hostname ]]; then
            else 
                echo "$service,$cache_host,remote_cache,$cache_port,$cache_path" >> "$data_file"   # save remote cache server metrics to file
            #else
            #    continue  # next service name in the array
            fi

        # inside of <<< $(...) command subtitution
        # run sosadmin info command of each serivce and  pipe output to grep.
        # grep lines starting with word Primary or Cache following with \s+, optional (\w+\s+)?, host|port|path,colon (:)
        # the \K ignores all previous matched groups
        # print the last non-space matches (\S+) group
        done <<< $(sosadmin info "$service" | grep -Po '(?x)^(Primary|Cache) \s+ (\w+\s+)? (host|port|path): (\s+)? \K (\S+)')
    done

	# file has size > 0  or exit error
    [[ -s $data_file ]] || { echo "-F: generate_csv_file failed"; exit 1; }
} # End create_data_file

#----
check_data_file () {
# Check and  create if a data file if not exsiting or less than a day old.

    # return 0 (true). Return 1 (fail)
    if [[ ! -e $data_file ]]; then
		echo "-I: $data_file not found... I am creating a new file"
        create_data_file 
    # 60min x 24 = 1440
    elif  [[ $(find "$data_file" -mmin +1440) ]]; then
        echo "-I: $data_file was more than a day old...I am creating a new file"
		rm -f "$data_file" || echo "-E: Could not delete $data_file"
        create_data_file
	else
		echo "-I: $data_file is less than a day old. I will not create file this time"
        return
    fi
} # End check_data_file


#----
create_prom_file () {
# move tmp file to dsm location with .prom extension
local infile=$1
local export_location=/dsm/prom_exporter/textfile
[[ -e $infile ]] || { echo "-F: Source file not found"; exit 1; } 

	if [[ "$DEBUG" == off ]]; then
        chmod 644 "$infile"
		local filename=$(basename "$infile")
		
		# variable subtitution for $$ to prom
		local promfile=${export_location}/$(echo "${filename/$$/prom}")
        
		# if new prom file missing due to any errors, remove previous promp file and possibly raise alerts
        mv "$infile" "$promfile" || { echo "-F: Failed to rename file"; rm -f $promfile; exit 1; }
    else
        echo "-W: Debug mode was on... I skipped creating a prom file"
    fi
} # End create_prom_file

#----
monitor_sos_service () {
# print status of repos and cache services to prom file
local tmpfile=${script_path}/sos_check_service.$$

	# promp file headers
	echo "# HELP sos_check_service Check if SOS service is running" > "$tmpfile"
	echo "# TYPE sos_check_service  gauge" >> "$tmpfile"

	# reading the csv file with , deleminator and save data to variables
	while IFS=, read -r _service _host _role _port 
	do
		# sosadmin ping command  returns status of primary and cache service
		# grep: search for a word after discard all previously matches (\K)
		# save results to p_status c_status variables
		read  -r p_status c_status  <<< $(sosadmin ping $_service | grep -Po '^\s+Status:\s+\K\w+')  
		[[ $p_status == Running ]] && p_result=0 || { p_result=1; p_status='Not_Running'; }  
		[[ $c_status == Running ]] && c_result=0 || { c_result=1; c_status='Not_Running'; }

		# Only monitoroing services running on this server
		if [[ $_host == $hostname ]]; then
			case $_role in 
				repo) 
					echo "sos_check_service{site="$site",hostname="$_host",service="$_service",role="$_role",status="$p_status"}" "$p_result" >> "$tmpfile"
				;;
				cache)
					echo "sos_check_service{site="$site",hostname="$_host",service="$_service",role="$_role",status="$c_status"}" "$c_result" >> "$tmpfile"
				;;
				remote_cache)
					echo "sos_check_service{site="$site",hostname="$_host",service="$_service",role="$_role",status="$c_status"}" "$c_result" >> "$tmpfile"
				;;
				*)
					echo "-F: I can't determine service role"
					echo "-I: Role: $_role"
					continue
				;;
			esac
		fi
	done <"$data_file"

	create_prom_file "$tmpfile" 
	
} # End monitor_sos_service()

#----
monitor_nfs_times () {
# Monitoring the nfs speeds - a simple creation of files
# identify the nfs areas do a copy and calculate the seconds
# This copying, typically on the /tmp local disks is time ~1.5s

	tmpfile=${script_path}/sos_nfs_times.$$
	dir=FiLe-CrEaTe.$$
    echo "# HELP sos_server_nfs_time Read/Write elapsed time (seconds)" > "$tmpfile"
    echo "# TYPE sos_server_nfs_time counter" >> "$tmpfile"

	declare -a disks
	
	# awk gets all disks from data file 
	# sed returns parent folder for diskname (using : deliminator)
	# sort unique
	#ddm_srv1,scysync29,repo,6004,/infrastructure/sos_storage/ddm_srv1.repo
	#disks=$(cat "$data_file" | awk -F, '{print $NF}' | sed 's:\(.*\)\/.*:\1:' | sort -u)
	# awk -v host="$host" -F, '$2 ~ host {print $0}'
	disks=$(cat "$data_file" | awk -v host="$hostname" -F, '$2 ~ host {print $NF}' | sed 's:\(.*\)\/.*:\1:' | sort -u)
    
	for nfs_path in ${disks[@]}
    do
     	num_files=1000
     	start_time=$(date +%s.%N)
     	# Have used mkdir instead of mkdir -p so you can see the errors if it is
     	# continuously returning 555 sec which is indeed a long time!
     	mkdir ${nfs_path}/${dir}
     	if [ "$?" -ne 0 ]
     	then
			time_used=555
		else
       		while [ "$num_files" -gt 0 ]
        	do
          		dd if=/dev/zero of=${nfs_path}/${dir}/time_file.${num_files} count=10 bs=2 2>>/dev/null
          		num_files=$(expr "$num_files" - 1)
        	done
		rm -rf ${nfs_path}/${dir}  1>>/dev/null 2>&1
        exec_time=$(echo "$(date +%s.%N) - $start_time" | bc)
        time_used=$(printf "%.2f" "$exec_time")
		echo "sos_server_nfs_time{site="$site",server="$hostname",path="$nfs_path"}" "$time_used" >> "$tmpfile"
		fi
    done

	create_prom_file "$tmpfile"
} # End monitor_nfs_times

#----
monitor_disk_space () {
# Disk shoule not be less than 250GB availble space
local tmpfile=${script_path}/sos_disk_space.$$
   	echo "# HELP sos_disk_space Check free space for less than 250GB" > "$tmpfile"
    echo "# TYPE sos_disk_space counter" >> "$tmpfile"

	#ddm_srv1,scysync29,repo,6004,/infrastructure/sos_storage/ddm_srv1.repo
	while IFS=, read -r _service _host _role _port _path 
	do
		[[ $_host == $hostname ]] || continue

		# df command outputs size in GB, the sed command remove letter G
		size=$(df -BG "$_path" | tail -n +2 | sed s/G//g | awk '{print $4}')
		
		echo "sos_disk_space{site="$site",server="$hostname",role="$_role",path="$_path",free_space="${size}GB"}" "$size"  >> "$tmpfile"				
	done <"$data_file"
	
	create_prom_file "$tmpfile"
} # End monitor_disk_space



#----
main() {
#source $(dirname "$0")/utils.bash
script_path=$(dirname "$0")
data_file="${script_path}/data.csv"
#prom_location=/dsm/prom_exporter/textfile

	check_data_file
	monitor_sos_service
	monitor_nfs_times
	monitor_disk_space

} # End main()

main

















