#!/bin/bash

# Purpose: get avaialble disk space and send email if space < 250GB

#-------------------------

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
get_sos_disks() {
  # get disk names from sos command; write results to file
  myfile=$1
  declare -A found  # Associate array for traking disks that already being worked on.
  
  readarray -t services < <(sosadmin list)
  for service in "${services[@]}"
  do
    read -r ptype prpath cpath <<< $(sosadmin info "$service" ptype prpath cpath)
    prpath="$(dirname $prpath)" && cpath="$(dirname $cpath)"

    case "$ptype" in
    LOCAL)
      if [[ ! -v found["$prpath"] ]]; then
        echo "$prpath" >> "$myfile"
        found["$prpath"]=1
        echo "$cpath" >> "$myfile"
        found["$cpath"]=1
      fi
    ;;
    REMOTE)
      if [[ ! -v found["$cpath"] ]]; then
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
} # End get_sos_disks

#----
check_disk_size() {
# return current available space
local disk=$1
  # df -BG output in GB
    size=$(df -BG "$disk" --output=avail | tail -1 | sed 's/ //')
    
    # remove letter G at the end.
    echo "${size%?}"
}

#----
scrub_cache_disk() {
#function to scrub service's cache disk and send email
#
local disk=$1

# exit if variable is null
#[[ -z $disk ]] || { echo "Function received a null value."; return; }
## exit function if disk is not a cache disk
#[[ $disk =~ cac[he]? ]] || return

local log=/tmp/scrubbed_${disk##*/}.log
retry=0

    # if log exists and older than 1 day
    if [[ -e $log ]]; then
        if [[ $(find "$log" -mmin +1440) ]]; then
            rm -f "$log"
            touch "$log"
        else
            retry=$(cat $log)
            echo "-I: $retry" 
        fi
    else
        touch "$log"
    fi

    # outter loop for service names; inner loop for project names 
    for srv in $(ls $disk | grep -Po '.*(?=\.cache)'); do
        for prj in $(sosadmin projects $srv); do
            # clean up cache data when 'older_than_days' is 30 and 'link_count' is 2
            sosadmin cachecleanup $srv $prj 2 7 2 >/dev/null 2>&1
        done
    done

    # Send email that cache disk was srubbed
    echo "$((retry += 1))" > $log
    echo -e "Alert: Disk $disk was low space and scrubbed $retry $( [[ $retry > 1 ]] && echo times || echo time)" |
    mail -s "Alert: $disk at "$EC_ZONE" is low disk space (${avail_space}GB)" linh.a.nguyen@intel.com

} # End scrub_cache_disk

#==================================
main() {
LIMIT=250
site="$EC_ZONE"

  file=/tmp/sos_disks.txt
  [[ -e "$file" ]] && printf '' > "$file" # discard content
  get_sos_disks "$file"

  for disk in $(sort -u < "$file")
  do
    # get availale space on cache or repo disks
    avail_space=$(check_disk_size "$disk")
    if [[ $avail_space -lt $LIMIT && $disk =~ cac[he]? ]]; then  # scrubbing if cache disk space is below LIMIT
        scrub_cache_disk "$disk"
        echo "$disk (Avail space: $avail_space)  *** Low disk space"
    elif [[ $avail_space -lt $LIMIT && $disk =~ rep[o]? ]]; then
        echo "$disk (Avail space: $avail_space)  *** Low disk space"
        echo -e "${site^^} disk space is low\n$disk ($avail_space) as of $(date)" |
        mail -s "Alert: Repo $disk low disk space ($avail_space)" linh.a.nguyen@intel.com 
    else 
        echo "$disk (Avail space: $avail_space)"
    fi
  done

#    if [[ $avail_space -lt $LIMIT ]]; then
#      case $disk in
#        cac[he]?)   # scrubbing cache disk if disk space is below LIMIT
#          scrub_cache_disk "$disk" 
#          echo "$disk (Avail space: $avail_space)  *** Low disk space"
#        ;;
#        rep[o]?)   # sending alert to incrase repo disk space
#          echo "$disk (Avail space: $avail_space)  *** Low disk space"
#          echo -e "${site^^} disk space is low\n$disk ($avail_space) as of $(date)" |
#                mail -s "Alert: Repo $disk low disk space ($avail_space)" linh.a.nguyen@intel.com
#        ;;
#      esac
#    else
#      echo "$disk (Avail space: $avail_space)"
#    fi
#  done

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
    echo -e "-E: Wrong usage.\nUsage: $0 [scrub_cache_disk <disk>]"
    exit 1
  ;;
esac
