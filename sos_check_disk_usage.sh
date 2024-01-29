#!/bin/bash

# Purpose: get avaialble disk space and send email if space <= 250GB

#-------------------------

[[ -e /opt/cliosoft/latest  ]] || { echo '-F-: Path /opt/cliosoft/latest not found'; exit 1; }
export CLIOSOFT_DIR=/opt/cliosoft/latest
export PATH=$CLIOSOFT_DIR/bin:$PATH
#sos_disks=/tmp/sos_disks.txt
#myfile2=/opt/cliosoft/excluded_services.txt
#sos_msg_log=/tmp/sos_msg.log


#----
get_site_code() {
  local site
  [[ $EC_ZONE =~ ^sc([1468]+) ]] && site=sc${BASH_REMATCH[2]} || site="$EC_ZONE"
  echo $site
}

increase_space() {   # arguments $disk $Size
  local disk site size
  disk=$1
  add_size=$2
  site=$(get_site_code)  

  # find disk'areaid
  #areaid=$(/usr/intel/bin/stodstatus areas --cell "$site" --fie areaid --for sc "path=~'ddgipde.soscache.001'"
  #eval "$stod_status_cmd areas --cell $site --fie areaid::15,path \"path=~'$diskname'\""
  #echo "Example: stod modify --cell zsc11 --areaid zsc11.35746 --maxfiles 50000000"
 
  size=$(df -BG "$disk" --output=size | tail -1 | sed 's/ \+//')
  echo "Disk size was $size" 
  x=$((${size%?} + add_size))  # remove G letter before adding 2 numbers
  #new_size=$((new_size - (new_size % 2))) 

  # rounding down, example 251 wil become 250
  [[ $((x % 2)) -ne 0 ]] && new_size=$((x - (x % 2))) || new_size=$x

  echo "Increased size to ${new_size}G"
  areaid=$(/usr/intel/bin/stodstatus areas --cell "$site" --fie areaid --for sc "path=='$disk'")
  stod_cmd="/usr/intel/bin/stod resize --cell "$site" --areaid "$areaid" --size ${new_size}G --immediate --exceed-forecast"
  echo $stod_cmd > "$sos_msg_log"

  #error=$(eval "${stod_cmd}" 2>&1 >"$sos_msg_log")
  #[[ ${?} -eq 0 ]] && echo "Passed" || echo "Failed"
}

#----
exclude_service() { 
# remove  SOS service from service list if serivces need to be excluded
  local input_file=$1  # file 
  is_excluded=0

  # exit function if file empty or has only spaces
  [[ -z $(grep '[^[:space:]]' $input_file) ]] && return 0

  # remove service name from services array if found in the file
  while IFS= read -r line; do
    for index in "${!services[@]}"; do
      if [[ ${services[index]} = $line ]]; then
        echo "-I-: Excluding $line"
        unset services[index]  # Remove element from the array
        is_excluded=1
      fi
    done
  done < "$input_file"

  # reindex array if excluding is true
  [[ $is_excluded ]] && services=("${services[@]}")
}


#----
get_sos_disks() {
#Purppose: get disk names from sos command; write results to file

  declare -A found  # Associate array for tracking disk names

  shopt -s nocasematch   # enable the nocasematch option
  for service in "${services[@]}"
  do
    # < <(command) is process subtitution; <<< $(command) is here-string
    read -r ptype prpath cpath <<<$(sosadmin info "$service" ptype prpath cpath)
    #echo -e "Service: $service\nType: $ptype\nPrimep: $prpath\nCachep: $cpath\n"
    
    # get local repo disks;
    # case insensitive when setting  shopt -s nocasematch

    if [[ $ptype == local && ! -v found[$prpath] ]]; then 
      dirname "$prpath" >> "$sos_disks"
      found["$prpath"]=1
    fi

    # get all cache disks to file 
	if [[ -n "$cpath" && ! -v found["$cpath"] ]]; then
      dirname $cpath >> "$sos_disks"
	  found["$cpath"]=1
	fi
  done
  shopt -u nocasematch   # disable the nocasematch option

  # replace site names with site in disk path
  sed -i 's:^/nfs/.*/disks:/nfs/site/disks:g' "$sos_disks"

} # End get_sos_disks

#----
get_avail_space() {
# return current available space
    local disk=$1
    # df -BG output in GB
    size=$(df -BG "$disk" --output=avail | tail -1 | sed 's/ \+//')
    echo "$size"
}


#==================================
main() {
  LIMIT=250 # threshold value 250GB
  site=$(get_site_code) 
  recipient="linh.a.nguyen@intel.com"
  sos_disks=/tmp/sos_disks.txt
  myfile2=/opt/cliosoft/excluded_services.txt
  sos_msg_log=/tmp/sos_msg.log
  
  readarray -t services < <(sosadmin list)

  [[ -e $myfile2 ]] && exclude_service "$myfile2"
  
  [[ -e "$sos_disks" ]] && rm -f "$sos_disks"
  
  get_sos_disks "$sos_disks"

  for disk in $(sort -u < "$sos_disks")
  do
    [[ $disk =~ soscache ]] && disk_type=cache || disk_type=repo
    
    # get available space on cache and repo disks
    avail_space=$(get_avail_space "$disk")
    
    # email if space is less than LIMIT
    if [[ ${avail_space%?} -lt $LIMIT ]] ; then
      echo "$disk (Avail space: $avail_space)  *** Low disk space"
      increase_space $disk 200
	  subject="Alert: ${site^^} $disk_type disk is low on space ($avail_space)"
cat<< EOF | echo /usr/intel/bin/mutt -s "$subject" -- "$recipient"
${site^^} $disk_type disk in is less than ${LIMIT}GB
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
