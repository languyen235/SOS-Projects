#!/bin/bash
#
# scritp validate  NFS read/write performance and output time value to promp file
# 
set -exuo pipefail

# turn debug mode. Script will not copy the new promp file to /dsm/prom../testfile if DEBUG=on
set +u; arg=$1
DEBUG=off
[[ $arg == -d ]] && { echo '-I: Debug mode is on'; DEBUG=on; } && set -u

# global variable $CLIOSOFT_DIR must have been set
[[ -z $CLIOSOFT_DIR ]] && { export CLIOSOFT_DIR=/opt/cliosoft/latest; export PATH=$CLIOSOFT_DIR/bin:$PATH; } || true

site="$EC_ZONE"

#----
create_dummy_files () {
# Process to create/delete thousand of test files in the given path.
# Measure elapsed time from start to finish process.
# Usage : create_dummy_files <dir>
#
dir=FiLe-CrEaTe
	if [ $# -eq 1 ]
		then
		dir=$1/$dir
	fi

	num_files=1000
	start_time=$(date +%s.%N)
	mkdir -p $dir
	
	if [ $? -ne 0 ]
		then
    	echo "Could not modify $dir, test failed"
    	exit 1
	fi
	
	while [ $num_files -ge 0 ]
	do
    	dd if=/dev/zero of=$dir/time_file.$num_files count=10 bs=2 2>>/dev/null
    	num_files=$(expr $num_files - 1)
	done

rm -r $dir 1>>/dev/null 2>&1
time_used=$(echo "$(date +%s.%N) - $start_time" | bc)
exec_time=`printf "%.2f seconds" $time_used`
#echo "$dir = $exec_time"
echo "$exec_time"
}

#----
status_of_nfs () {
float=$1

# round up decimal to integer number
number=$(echo "($float+0.5)/1" | bc)

	if [[ "$number" -le 3 ]]; then
		echo "normal"]
	elif [[ "$number" -gt 3 && "$number" -le 5 ]]; then
		echo 'slow'
	elif [[ "$number" -gt 5 ]]; then
		echo 'extremely_slow'
	fi

} # End of nfs_status

#----
generate_prom_file () {
# perfom read/write NFS disk and write latency number to prom file
# 
local db=$1
	fname=$(dirname "$0")/sos_nfs_latency.prom

	echo "# HELP sos_nfs_latency Monitoring of NFS disk latency" > "$fname"
	echo "# TYPE sos_nfs_latency gauge" >> "$fname"

	#  1          2      3    4          5
	#ddm_srv1,scysync29,repo,6004,/infrastructure/sos_storage/ddm_srv1.repo
	while IFS=','  read -r _service _host _role _port _path 
	do
		# Test NFS latency
		latency=$(create_dummy_files $_path)

		# 
		latency="${latency%% *}"

		dstatus=$(status_of_nfs $latency)

		# save metrics with latency value to prom file
		echo "sos_nfs_latency{site="$site",server="$_host",service="$_service",path="$_path",status="$dstatus"}" "$latency" >> "$fname" 
	done <"$db"

	# cp promp fie to dsm location
	if [[ $DEBUG == off ]]; then
		chmod 644 "$fname"  
		mv "$fname" $prom_files || rm -f "$prom_files"/sos_nfs_latency.prom
	fi
}

#----
remove_lock () {
    echo "-I: Remove lock dir"
	rm -rf "$LOCK_DIR"  || echo "-F: Cannot remore lock dir"
}


#----
main() {
source $(dirname "$0")/utils.bash
script_path=/opt/cliosoft/monitoring/scripts
db_file="${script_path}/data.csv"
prom_file="${script_path}/sos_nfs_latency.prom"
prom_location=/dsm/prom_exporter/textfile
LOCK_DIR=/tmp/sos_lockdir

		# Create lookul file if check function fails
	    if ! check_lookup_file "$db_file" "$LOCK_DIR";  then
        echo '-I: Create lock dir'
        mkdir -p "$LOCK_DIR" ||  { echo "-F: Cannot create lock dir"; exit 2; }
        trap cleanup INT KILL
        generate_lookup_file "$db_file"
		remove_lock
    fi
	
	generate_prom_file "$db"
}

main

exit $?
