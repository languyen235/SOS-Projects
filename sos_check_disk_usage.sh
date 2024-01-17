#!/bin/bash

# Purpose: get avaialble disk space and send email if space <= 250GB

#-------------------------

[[ -e /opt/cliosoft/latest  ]] || { echo '-F-: Path /opt/cliosoft/latest not found'; exit 1; }
export CLIOSOFT=/opt/cliosoft/latest
export PATH=$CLIOSOFT/bin:$PATH

get_site_code() {
  local site
  [[ $EC_ZONE =~ ^sc([1468]+) ]] && site=sc${BASH_REMATCH[2]} || site="$EC_ZONE"
  echo $site
}

increase_space() {   # arguments $disk $Size
  disk=$1
  add_size=$2
  site=$(get_site_code)  

  # find disk'areaid
  #areaid=$(/usr/intel/bin/stodstatus areas --cell "$site" --fie areaid --for sc "path=~'ddgipde.soscache.001'"
  #eval "$stod_status_cmd areas --cell $site --fie areaid::15,path \"path=~'$diskname'\""
  #echo "Example: stod modify --cell zsc11 --areaid zsc11.35746 --maxfiles 50000000"
 
  local size
  size=$(echo $(df -BG "$disk" --output=size | tail -1))
  echo "Disk size was $size" 
  new_size=$((${size%?} + add_size))  # remove G letter before adding 2 numbers
  new_size=$((new_size - (new_size % 2))) # rounding down the new size
  echo "Increased size to ${new_size}G"
  cmd="/usr/intel/bin/stod resize --cell "$site" --path "$disk" --size ${new_size}G --immediate --exceed-forecast"
  echo $cmd

  #error=$(eval "${cmd}" 2>&1 >"/dev/null")
  #[[ ${?} -eq 0 ]] && echo "Passed" || echo "Failed"
}

#----
exclude_service() { 
# Exclude SOS service from list
# input file /opt/clisoft/excluded_services.txt. Each service per line 

  for srv_name in $(cat excluded_services.txt); do
    for i in "${!services[@]}"; do
      if [[ ${services[$i]} == "$srv_name" ]]; then
        echo "-I-: Excluding $srv_name"
        unset services[$i]  # Remove service from the array
	    break               # break inner loop
      fi
    done
  done

  # We must re-index the array after deleting element in array
  temp_array=()
  for element in "${services[@]}"; do
    temp_array+=("$element")
  done
  services=("${temp_array[@]}")
}

#----
get_sos_disks() {
#Purppose: get disk names from sos command; write results to file

  myfile=$1
  declare -A found  # Associate array for tracking disk names
  readarray -t services < <(sosadmin list)

  # run function to exclude service if input file exits
  [[ -f 'excluded_services.txt' ]] && exclude_service

  for service in "${services[@]}"
  do
    # < <(command) is process subtitution; <<< $(command) is here-string
    read -r ptype prpath cpath <<< $(sosadmin info "$service" ptype prpath cpath)
    #echo -e "Service: $service\nType: $ptype\nPrimep: $prpath\nCachep: $cpath\n"
    
    # get local repo disks
    if [[ $ptype == LOCAL && ! -v found["$prpath"] ]]; then
      echo $(dirname $prpath) >> "$myfile"
      found["$prpath"]=1
    fi

    # get all cache disks to file 
	if [[ -n "$cpath" && ! -v found["$cpath"] ]]; then
      echo $(dirname $cpath) >> "$myfile"
	  found["$cpath"]=1
	fi
  done

  # replace site names with site in disk path
  sed -i 's:^/nfs/.*/disks:/nfs/site/disks:g' "$myfile"
} # End get_sos_disks

#----
get_avail_space() {
# return current available space
    local disk=$1
    # df -BG output in GB
    size=$(df -BG "$disk" --output=avail | tail -1 | sed 's/ //')
    echo "$size"
}

#----
scrub_cache_disk() {
#function to scrub service's cache disk and send email
#
local disk=$1

#[[ -z $disk ]] || { echo "Function received a null value."; return; }
## exit function if disk is not a cache disk
#[[ $disk =~ cac[he]? ]] || return

local log=/tmp/scrubbed_${disk##*/}.log
    
	# if scurbbed log older than 1 day; create the log and scrubb a cache disk 
    if [[ -e $log && $(find "$log" -mmin +1440) ]]; then
      rm -f "$log" && touch "$log"
    else
	  return   # exit function if log time less than a day 
    fi

    # outter loop for service names; inner loop for project names 
    for srv in $(ls $disk | grep -Po '.*(?=\.cache)'); do
      for prj in $(sosadmin projects $srv); do
        # clean up cache data when 'older_than_days' is 30 and 'link_count' is <= 2 with 2 versions
        sosadmin cachecleanup $srv $prj 2 30 2 >/dev/null 2>&1
      done
    done

	echo "-I: Completed scurbbing cache disk $disk"

} # End scrub_cache_disk


#==================================
main() {
LIMIT=250 # limit 250GB 
site=$(get_site_code)

  file=/tmp/sos_disks.txt
  [[ -e "$file" ]] && printf '' > "$file" ||  mkdir -p "$file" 
  
  get_sos_disks "$file"

  for disk in $(sort -u < "$file")
  do
    [[ $disk =~ soscache ]] && disk_type=cache || disk_type=repo
    
    # get available space on cache and repo disks
    avail_space=$(get_avail_space "$disk")
    
    # email if space is low
    if [[ ${avail_space%?} -le $LIMIT ]] ; then
      echo "$disk (Avail space: $avail_space)  *** Low disk space"
      increase_space $disk 200
cat<<- EOF | mail -s "Alert: ${disk_type^} disk in ${site^^} is low space ($avail_space)" linh.a.nguyen@intel.com
${disk_type^} disk space is low
$disk (Avail space: $avail_space)
EOF
    else
      echo "$disk (Avail space: $avail_space)"
    fi
  done
} # End main

# only once instane of this script running at any given time
exec 200>/tmp/sos_chekdisk.lock || exit 1
flock 200 || exit 1
trap "flock -u 200;rm -rf /tmp/sos_chekdisk.lock" INT TERM EXIT

case "$1" in
  "")
    main
  ;;
  "increase_space")
    shift
    increase_space "$@"
    exit
  ;;
  *)
    echo -e "-E: Wrong usage.\nUsage: $0" 
    exit 1
  ;;
esac
