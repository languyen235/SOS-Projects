#!/usr/intel/bin/bash
## functions can reuse and import into another bash scripts


#----
verify_lookup_file () {
# delete  data file if +24 hours old
local file=$1
local lock_dir=$2

	# return 0 (true). Return 1 (fail)
	if [[ ! -e "$lock_dir" ]]; then
		if [[ ! -e $file ]]; then
			echo "-W: $file didn't exist..Will create a new file"
			status=1
		# 60min x 24 = 1440
		elif  [[ $(find "$file" -mmin +1440) ]]; then
			echo "-I: $file was more than a day old... Will create a new file"
			rm -f "$file"
			status=1
		else
			echo "-I: $file is a day old. Will not create file again"
			status=0
		fi
	# if lockdir was create +5 mins ago, delete it
	elif [[ -d "$lock_dir" &&  $(find "$lock_dir" -maxdepth 1 -type d -mmin +5) ]]; then
		echo "-I: Lock dir is old... Deleting $lock_dir"
		rm -rf "$lock_dir" || echo 
		status=1
	else 
		echo "Detected lock $lock_dir... Will not create $file"
		status=0
	fi
return "$status"
}

#----
_get_service_info() {
local srv_array=$1
	$(sosadmin info "$srv" | grep -Po '^(Primary|Cache)\s+(\w+\s+)?(host|port|path):(\s+)?\K(\S+)')

	
}

#----
generate_lookup_file () {
db=$1
hostname=$(hostname)

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


	# test SOS command with 2s timeout
	if ! /usr/bin/timeout 2s sosadmin list; then
		echo "-F: Cliosoft command timeout occurred."
		return 1
	else
		readarray -t services < <(sosadmin list)
	fi

    # iterate each primary and cache service in array
    for service in "${services[@]}"
    do
        # Save input from command subtituion to variables at while .. done loop
        while read -r primary_host primary_port primary_path cache_host cache_port cache_path
        do
			# if.. elif .. else
            # case 1: primary's hostname matches with this monitoring host, aquire retrieve both primary and cache info
            # case 2: primary's hostname doesn't match but cache's hostname matches, retrieve ony cache info
            # write output out csv file
            if [[ $primary_host =~ $hostname ]]; then
                primary_host="${primary_host%%.*}"  # remove .<site>.intel.com; See bash variable expansion
                cache_host="${cache_host%%.*}"      # remove .<site>.intel.com; See bash variable expansion
                echo "$service,$primary_host,repo,$primary_port,$primary_path" >> "$db"  # output repo server metrics to file
                echo "$service,$cache_host,cache,$cache_port,$cache_path" >> "$db"		# output cache server metrics to file
            elif [[ $cache_host =~ $hostname ]]; then
                cache_host="${cache_host%%.*}"		# remove .<site>.intel.com; See bash variable expansion
                echo "$service,$cache_host,remote_cache,$cache_port,$cache_path" >> "$db"	# save remote cache server metrics to file
            else
                continue  # nexti iteration
            fi
		# inside of <<< $(...) command subtitution
		# run sosadmin info command on  each serivce and  pipe output to grep.
		# grep lines starting with word Primary or Cache following with \s+, optional (\w+\s+)?, host|port|path,colon (:)
		# the \K ignores all previous matched groups
		# print the last matched non-space (\S+) group
        done <<< $(sosadmin info "$service" | grep -Po '^(Primary|Cache)\s+(\w+\s+)?(host|port|path):(\s+)?\K(\S+)')
    done
	
	[[ "$?" -eq -0 ]] || { echo "-E: generate_csv_file was uncessful"; return 1; }
	return $?
}

