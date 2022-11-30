#!/bin/bash

# Purpose: get avaialble disk space and send email if space < 250GB

#-------------------------
print_to_file() {
  local disk
  disk=$1
  MESSAGE="/tmp/disk-usage.out"
  # df -GB always in GB
  df -BG $disk | tail -n +2 >> $MESSAGE
  cat $MESSAGE | grep G | column -t | while read output;
  do
    Sname=$(echo $output | awk '{print $1}')
    Fsystem=$(echo $output | awk '{print $2}')
    Size=$(echo $output | awk '{print $3}')
    Used=$(echo $output | awk '{print $4}')
    Avail=$(echo $output | awk '{print $5}')
    Use=$(echo $output | awk '{print $6}')
    Mnt=$(echo $output | awk '{print $7}')
    echo "Server Name, Filesystem, Size, Used, Avail, Use%, Mounted on"
    echo "$Sname,$Fsystem,$Size,$Used,$Avail,$Use,$Mnt"
  done
}

#----
increase_space() {   # arguments $disk $Size
  disk=$1
  diskSize=$2
  newDiskSize=$((diskSize + 100))
  #site=$EC_ZONE
  if [[ $EC_ZONE =~ ^p_sc_([1468]+) ]]; then
    site=sc${BASH_REMATCH[2]}
  else
    site="$EC_ZONE"
  fi
  
  # find disk'areaid
  #areaid=$(/usr/intel/bin/stodstatus areas --cell "$site" --fie areaid --for sc "path=~'ddgipde.soscache.001'"
  #eval "$stod_status_cmd areas --cell $site --fie areaid::15,path \"path=~'$diskname'\""
  #echo "Example: stod modify --cell zsc11 --areaid zsc11.35746 --maxfiles 50000000"
  /usr/intel/bin/stod resize --cell "$site" --path "$disk" --size "$newDiskSize" --immediate --exceed-forecast
}

#----
get_disks() {
  # get disk names from sos command; write results to file
  myfile=$1
  [[ -e "$myfile" ]] && printf '' > "$myfile" # discard content
  declare -A found  # Associate array for traking disks that already being worked on.
  
  readarray -t services < <(sosadmin list)
  for service in "${services[@]}"
  do
		read -r ptype prpath cpath <<< $(sosadmin info "$service" ptype prpath cpath)
		prpath="$(dirname $prpath)" && cpath="$(dirname $cpath)"

		case "$ptype" in
		LOCAL)
			if [[ ! -v found["$prpath"] ]]
			then
				echo "$prpath" >> "$myfile"
				found["$prpath"]=1
				echo "$cpath" >> "$myfile"
				found["$cpath"]=1
			fi
		;;
		REMOTE)
			if [[ ! -v found["$cpath"] ]]
			then
				echo "$cpath" >> "$myfile"
				found["$cpath"]=1
			fi
		;;
		*) { echo "-E: Disk informaion not found"; exit 1; }
		;;
		esac
	done

	# replace site names with site alias
	sed -i 's:^/nfs/.*/disks:/nfs/site/disks:g' "$myfile"
} # End get_disks

#----
size_cmd() {
# return current available space
local disk=$1
	# df -BG output always in GB
    size=$(df -BG "$disk" --output=avail | tail -1 | sed 's/ //')
    echo "$size"
}

#----
scrub_cache_disk() {
#function to scrub service's cache disk
#
# disk=ddgipde.soscache.001; for srv in $(ls /nfs/site/disks/${disk} | grep -Po '.*(?=\.cache)'); do for prj in $(sosadmin projects $srv); do sosadmin cachecleanup $srv $prj 30 2; done; done

local disk=$1
# exit if variable is null
#[[ -z $disk ]] || { echo "Function received a null value."; return; }
## exit function if disk is not a cache disk
[[ $disk =~ cac[he]? ]] || return

local log=/tmp/scrubbed_${disk##*/}.log
touch $log
retry=0

    # if log exists and older than 1 day
    if [[ -e $log && $(find "$log" -mmin +1440) ]]; then
      rm -f "$log"
    else
      retry=$(cat $log)
    fi

    for srv in $(ls $disk | grep -Po '.*(?=\.cache)'); do
        for prj in $(sosadmin projects $srv); do
            # clean up cache data when 'older_than_days' is 30 and 'link_count' is 2
            sosadmin cachecleanup $srv $prj 2 30 2 >/dev/null 2>&1
        done
    done

    ((retry++)); echo "$retry" > $log
    echo -e "Alert: Cache $disk was low space and scrubbed $retry $( [[ $retry > 1 ]] && echo times || echo time)" |
    mail -s "Alert: $disk low disk space $avail_space" linh.a.nguyen@intel.com

} # End scrub_cache_disk

#==================================
main() {
threshold=250
site="$EC_ZONE"

	file=/tmp/sos_disks.txt
	get_disks "$file"

	for disk in $(sort -u < "$file")
	do
		# get availalespace on disk
		avail_space=$(size_cmd "$disk")
		if [[ ${avail_space%?} -lt $threshold ]]; then
		  scrub_cache_disk "$disk"
		  #echo -e "${site^^} disk space is low\n$disk ($avail_space) as of $(date)" |
		  #mail -s "Alert: $disk low disk space $avail_space" linh.a.nguyen@intel.com
		fi
	      echo "$disk (Avail space: $avail_space)"
	done

} # End main

# only once instane of this script running at any given time
exec 200>/tmp/sos_chekdisk.lock || exit 1
flock 200 || exit 1
trap "flock -u 200;rm -rf /tmp/sos_chekdisk.lock" INT TERM EXIT

case "$1" in
	"") 
        main ;;
	scrub_cache_disk) 
	    exec "$@"; exit;;
	*)
		echo -e "-E: Wrong usage.\nUsage: $0 [cleancache <disk>]"
		exit 1
	;;
esac
