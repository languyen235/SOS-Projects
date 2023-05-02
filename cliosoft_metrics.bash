#!/bin/bash
#
# Purpose: script check Clisooft service then write service status and metrics to Prometheus prom files
# 1. Monitor Cliosoft service running
# 2. Monitor read/write performance of NFS disks
# 3. Monitor amount disk space avaialable
# Requirements: Cliosoft software installed on server at /opt/cliosoft


#set -exuo pipefail
#export PS4='Line $LINENO: '

## global $CLIOSOFT_DIR variable
[[ -z $CLIOSOFT_DIR ]] && { export CLIOSOFT_DIR=/opt/cliosoft/latest; export PATH=$CLIOSOFT_DIR/bin:$PATH; } || true
[[ -e "$CLIOSOFT_DIR"/bin ]] || { echo '-F: Cliosoft binary not found'; exit 1; }
export sitecode=$(hostname -f | cut -d"." -f2)
export hostname=$(hostname)

# Script location
script_path=$(dirname "$0")

# csv data file location
data_file="${script_path}/data.csv"

# scratch area
tmp_dir=/opt/cliosoft/monitoring/tmp
[[ -d $tmp_dir ]] || mkdir -p "$tmp_dir"

# prommetheus location
prom_files=/opt/cliosoft/monitoring/prom_files
[[ -L $prom_files ]] || ln -s /dsm/prom_exporter/textfile "$prom_files"
DEBUG=off

#----
run_sosmgr() {
# Aquire SOS service names by runing SOS command
name="$1"  # service name
attr="$2"  # atribute name 
key="${attr##*_}"  # Remove front value by removing text from beggining including underscore

	# host: ipde-sc:scyhdk060.sc.intel.com
	# regrex "^\s+$key:\s+.*:\K\S+"; \K ignores spaces and texts to 'host: ipde-sc:' and return the rest
	server=$(sosmgr service get -s "$name" --"$attr" | grep -Po "^\s+$key:\s+\S+:\K\S+")
	# return value or NULL if variable is empty
	echo "${server:=NULL}"
}

#----
convert_iglb_to_hostname () {
# convert alias to real hostnanme
local input_name=$1

	if [[ $input_name =~ iglb.intel.com ]]; then
	  #covert name using nslookup to find ip and host on ip to return hostname
	  ip=$(nslookup $input_name | tail -2 | grep -Po '^Address:\s+\K.*') 
	  cname="$(host $ip | awk '{print $NF}' | awk -F. '{print $1}')"
	else
	  # covert to short name
	  cname="${input_name%%.*}"
	fi
	echo "$cname"
} # convert_iglb_to_hostname

#----
create_data_file() {
# Run cliosoft command to list service names, ports, roles, and disks and save the results to a csv file
# Use a lock to ensure that only one process is creating csv file at any given time.

	# set file descriptor 100 
	exec 100>"$data_file" || { echo "-E: Exec command failed"; exit 1; }
	
	#Acquire a lock using file handle
	flock -n 100 || { echo "-E: There is another process updating the file"; return; }
	trap 'flock -u 100' INT TERM 

    # The sos command  should not take more than 3 seconds
    if ! /usr/bin/timeout 3s sosadmin list >/dev/null; then
        echo "-F: Cliosoft command timeout occurred."
        exit 1
    else
        #readarray -t services < <(sosadmin list)  # output multiple lines
        read -ra  services <<< $(sosadmin list)  # output multiple lines
    fi

	# if array is empty, exit script with error
	[[ ${#services[@]} -ne 0 ]] || { echo "-F: Array is empty"; exit 1; }

	# add header to csv file
	# example: testbk,sos-testprimary1-sc,primary,6381,/nfs/site/disks/sos_eval_scm/testbk.repo
	# as: service,hostname,role,port,storage_path
	echo "service,hostname,role,port,storage_path" > "$data_file"

    # read each primary and cache service in array and save them to data file
    for service in "${services[@]}"
    do
		# Saving Cliosoft command output to array
		readarray -t atts < <(sosadmin info "$service" ptype phost pcport prpath chost ccport cpath)

		# ptype phost pcport prpath ctype chost ccport cpath
		#   0      1      2      3    4     5     6      7

		# if variable is empty, run second command 
        ptype="${atts[0]:?Variable is empty or unset}"
        phost="${atts[1]:=$(run_sosmgr $service primary_host)}"
        pcport="${atts[2]:=$(run_sosmgr $service primary_port)}"
        prpath="${atts[3]:=$(run_sosmgr $service primary_path)}"
        chost="${atts[4]:=$(run_sosmgr $service cache_host)}"
        ccport="${atts[5]:=$(run_sosmgr $service cache_port)}"
        cpath="${atts[6]:=$(run_sosmgr $service cache_path)}"
	
		# remove suffix .<site>.intel.com
		#phost="${phost%%.*}" && chost="${chost%%.*}"
		#phost=$(convert_iglb_to_hostname $phost)
		#chost=$(convert_iglb_to_hostname $chost)
        # use nslookup to get real hostname if using alias *.sync.intel.com
        phost=$(nslookup "$phost"  | grep -Po 'Name:\s+\K(\w+)')
        chost=$(nslookup "$chost"  | grep -Po 'Name:\s+\K(\w+)')

		if [[ $ptype == LOCAL ]]; then
			echo "$service,$phost,primary,$pcport,$prpath" >> "$data_file"        # output repo server metrics to file
			echo "$service,$chost,cache,$ccport,$cpath" >> "$data_file"      # output cache server metrics to file
		else
			echo "$service,$chost,cache,$ccport,$cpath" >> "$data_file"   # save remote cache server metrics to file
		fi
		unset atts
    done

	# file size > 0  or exit error
    [[ -s $data_file ]] || { echo "-F: generate_csv_file failed"; exit 1; }

	# After a successful file creation, remove the lock.
	flock -u 100

} # End create_data_file

#----
check_data_file() {
# Check and  create if a data file doesn't exist  or more than a day old.
	echo "-I: Checking data file"

    if [[ ! -e $data_file ]]; then
		echo "-I: $data_file not found... Creating data file."
        create_data_file 
    # 60min x 24 = 1440
    elif  [[ $(find "$data_file" -mmin +1440) ]]; then
        echo "-I: $data_file is more than a day old...Creating a new file."
		rm -f "$data_file" || { echo "-E: I could not delete $data_file"; exit 1; } 
        create_data_file
	else
		echo "-I: $data_file is less than a day old...Existing."
        return
    fi
} # End check_data_file


#----
create_prom_file() {
# create metrics file to move it to location with .prom extension
local tmpfile=${1:?Source file not found}
# [[ -e $tmpfile ]] || { echo "-F: Source file not found"; exit 1; } 

	if [[ "$DEBUG" == off ]]; then
        chmod 644 "$tmpfile"
		#local filename=$(basename "$tmpfile")
		local filename=$(basename "$tmpfile")
		
		
		# change file name extension from .$$ to .prom using variable subtitution 
		local promfile="$prom_files/${filename/.$$/.prom}"
        
		# if new prom file missing due to any errors, remove previous promp file and possibly raise alerts
        mv "$tmpfile" "$promfile" || { echo "-F: Failed to rename file"; rm -f "$promfile"; exit 1; }
    else
        echo "-I: Debug mode is on... Skip creating a prom file."
    fi
} # End create_prom_file

#----
monitor_sos_service() {
# print metrics and status of repo and cache services to prom file
local tmpfile
tmpfile=${tmp_dir}/Check_Cliosoft_Service.$$

	# promp file headers
	echo "# HELP Check_Cliosoft_Service Check whether SOS service is running" > "$tmpfile"
	echo "# TYPE Check_Cliosoft_Service" >> "$tmpfile"

	# reading the csv file with , deleminator and save data to variables
	while IFS=, read -r _service _host _role 
	do
		# sosadmin ping command  returns status of primary and cache service
		# grep: search for a word after discard all previously matches (\K)
		# save results to primary_status cache_status variables
		read  -r p_status c_status  <<< $(sosadmin ping "$_service" | grep -Po '^\s+Status:\s+\K\w+')  
		[[ $p_status == Running ]] && p_result=0 || { p_result=1; p_status='Not_Running'; }  
		[[ $c_status == Running ]] && c_result=0 || { c_result=1; c_status='Not_Running'; }

		# Only monitoroing services running on this server
		if [[ $_host == "$hostname" ]]; then
			case $_role in 
				primary) 
					echo "Check_Cliosoft_Service{site=\"$sitecode\",hostname=\"$_host\",service=\"$_service\",role=\"$_role\",status=\"$p_status\"}" "$p_result" >> "$tmpfile"
				;;
				cache)
					echo "Check_Cliosoft_Service{site=\"$sitecode\",hostname=\"$_host\",service=\"$_service\",role=\"$_role\",status=\"$c_status\"}" "$c_result" >> "$tmpfile"
				;;
				*)
					echo "-F: I can't determine service role"
					echo "-I: Role: $_role"
					continue
				;;
			esac
		fi
	#10nm_sc,scyhdk060,repo,7009,/nfs/site/disks/hipipde.sosrepo.003/10nm_sc.repo
	done < <(grep "$hostname" "$data_file" | cut -d ',' -f 1,2,3)

	create_prom_file "$tmpfile" 
	
} # End monitor_sos_service()

#----
monitor_nfs_times() {
# Monitoring the nfs speeds - a simple creation of files
# identify the nfs areas do a copy and calculate the seconds
# This copying, typically on the /tmp local disks is time ~1.5s

	# Assign file handle to a lock file
	exec 200>/tmp/monitor_nfs_times.lock || { echo "-E: Exec command failed"; return 10; }

	#Acquire a lock using file handle
	flock -n 200 || { echo "-E: There is another process updating the file"; return 10; }
	trap "flock -u 200; rm -f /tmp/monitor_nfs_times.lock" INT TERM

	tmpfile=${tmp_dir}/Check_Cliosoft_NFS_Latency.$$
	dir=FiLe-CrEaTe.$$
    echo "# HELP Check_Cliosoft_NFS_Latency Check Read/Write for elapsed time (seconds)" > "$tmpfile"
    echo "# TYPE Check_Cliosoft_NFS_Latency gauge" >> "$tmpfile"

	# inside process subtitution < <(...)
	# awk gets all disks from data file 
	# grep with look-ahead to match text begins and ends with /
	# sort unique
	# output to array
    readarray -t paths < <(grep "$hostname" "$data_file" | awk -F, '{print $NF}' | grep -Po '^/.*(?=/)' | sort -u)

	for nfs_path in "${paths[@]}"
    do
		[[ $nfs_path == NULL ]] && continue   # If the value is NULL, the iteration continues.
     	num_files=1000
     	start_time=$(date +%s.%N)
     	# Have used mkdir instead of mkdir -p so you can see the errors if it is
     	# continuously returning 555 sec which is indeed a long time!
     	mkdir "${nfs_path}/$dir"
     	if [ "$?" -ne 0 ]; then
			time_used=555
		else
			set +e
       		while [[ "$num_files" -gt 0 ]]
        	do
				dd if=/dev/zero of="$nfs_path/$dir/time_file.$num_files" count=10 bs=2 2>>/dev/null
          		num_files=$(expr "$num_files" - 1)
        	done
			rm -rf "${nfs_path}/$dir"  1>>/dev/null 2>&1
        	exec_time=$(echo "$(date +%s.%N) - $start_time" | bc)
        	time_used=$(printf "%.2f" "$exec_time")
			echo "Check_Cliosoft_NFS_Latency{site=\"$sitecode\",server=\"$hostname\",path=\"$nfs_path\"}" "$time_used" >> "$tmpfile"
		fi
    done

	create_prom_file "$tmpfile"

	#remote lock file
	flock -u 200
} # End monitor_nfs_times

#----
scrub_cache_disk() {
#function to scrub service's cache disk
#
# disk=ddgipde.soscache.001; for srv in $(ls /nfs/site/disks/${disk} | grep -Po '.*(?=\.cache)'); do for prj in $(sosadmin projects $srv); do sosadmin cachecleanup $srv $prj 30 2; done; done

local disk=$1
# exit if variable is null
## exit function if disk is not a cache disk
[[ $disk =~ cac[he]? ]] || return

local log=/tmp/scrubbed_${disk##*/}.log
[[ -e $log ]] || touch "$log"
retry=0

	# if log exists and older than 1 day
	if [[ -e $log && $(find "$log" -mmin +1440) ]]; then
      rm -f "$log"
	  touch "$log"
    else
      retry=$(cat $log)
    fi
  
    for srv in $(ls $disk | grep -Po '.*(?=\.cache)'); do
        for prj in $(sosadmin projects $srv); do
            # clean up cache data when 'older_than_days' is 30 and 'link_count' is 2
            sosadmin cachecleanup $srv $prj 2 30 2
        done
    done

	((retry++)); echo "$retry" > $log
	echo -e "Alert: Cache $disk was low space and scrubbed $retry $( [[ $retry > 1 ]] && echo times || echo time)" |
	mail -s "Alert: Alert: $disk low disk space $avail_space" linh.a.nguyen@intel.com

} # End scrub_cache_disk

#----
monitor_disk_space() {
# check available disk space
local tmpfile
tmpfile=${tmp_dir}/Check_Cliosoft_Disk_Space.$$

   	echo "# HELP Check_Cliosoft_Disk_Space Check free disk space" > "$tmpfile"
    echo "# TYPE Check_Cliosoft_Disk_Space gauge" >> "$tmpfile"

	readarray -t disks < <(grep "$hostname" "$data_file" | awk -F, '{print $NF}' | grep -Po '^/.*(?=/)' | sort -u)
	for disk in "${disks[@]}"
	do
		# df -BG always output in GB (1T is 1000GB) 
		read -r total avail <<< $(df -BG "$disk" --output=size,avail | tail -n 1)

		echo "$avail"
		
		# scrub cache disk
		[[ $avail -lt 500 ]] && scrub_cache_disk $disk
		
		#echo "sos_disk_space{site=$sitecode,server=$hostname,path=$disk,free_space=$size}" "${size%G}"  >> "$tmpfile"				
		echo "Check_Cliosoft_Disk_Space{site=\"$sitecode\",server=\"$hostname\",path=\"$disk\",total=\"$total\"}" "${avail%?}"  >> "$tmpfile"				
	done
	
	create_prom_file "$tmpfile"
} # End monitor_disk_space

#----
run_all() {
	check_data_file
	monitor_sos_service
	monitor_nfs_times
	monitor_disk_space
} # End run_all()


#----------
	# Option to run function at command line
	echo "The number of arguments passed to the script is: $#"
	if [[ ${1-} == -d || ${2-} == -d ]] ; then
		echo '-I: Debug mode is on'
		DEBUG=on
	fi

	## Options to run a function at  command line.
	case "${1-}" in 
		"" | -d)
			run_all
			;;
		check_data_file)	"$@"; exit ;;
		monitor_sos_service)
			check_data_file; "$@"; exit ;;
		monitor_nfs_times)		
			check_data_file; "$@"; exit ;;
		monitor_disk_space)		
			check_data_file; "$@"; exit ;;
		*)
			echo "Usage:"
			echo "$0 help	: Print this menu"
			echo "$0  [-d ] : Run all in debug mode. Save outputs to ../tmp"
			echo "$0 [ check_data_file | monitor_sos_service | monitor_nfs_times | monitor_disk_space ] [-d]"
			exit 1
			;;
	esac
