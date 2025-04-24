#!/bin/bash
#
#
# ls */setup/sosd.cfg | xargs -I @ mv @ @.preUpgrade
# foreach proj (`ls -d */setup`)
#   echo "-----\n-- 8.1.0 upgrade prereqs --\nDEFAULT_GROUP no_group;\nADMIN hlxp4usr;\n-----\n\n" > $proj/sosd.cfg
#   cat $proj/sosd.cfg.preUpgrade >> $proj/sosd.cfg
# end

# foreach tcl_file (`ls */setup/sos.tcl`)
#   cp $tcl_file ${tcl_file}.preUpgrade
#   sed -i 's/return "all_my_groups"/return ""/g' $tcl_file
# end
# '

export CLIOSOFT_DIR=/opt/cliosoft/latest
export PATH=$CLIOSOFT_DIR/bin:$PATH
# export SOS_SERVERS_DIR=/nfs/site/disks/sos_adm/share/SERVERS7
export SOS_SERVERS_DIR=/opt/cliosoft/latest/SERVERS
export LOG_FILE=/tmp/sos_upgrade.log
[[ -e "$LOG_FILE" ]] && rm -f "$LOG_FILE"
export SOS_RELEASE=8.1.1.p2


SOS_SERVERS+=("scysync36" "isyn056" "iapp105" "iapp523" "iapp567" \
"inlapp436" "musxl0350" "plxs1708" \
"pglhdk62" "scyhdk060" "scysync114" "scysync132" "scyhlx029" \
"vrsxdm01" "scysync142" "scycliosoft001" "scysync212" "scysync146" \
"scysync150" "scysync152" "scy20280" "scysync162" "scysync164" "scysync144")


function log() {
  local log_level=$1
  local message=$2
  local time_stamp; time_stamp=$(date +"%Y-%m-%d %H:%M:%S")
  echo "[$time_stamp][$log_level] $message" | tee -a "$LOG_FILE"
}

function get_repo_disk() {
  local service=$1
  #dir=$(dirname "$(sosadmin info "$service" prpath)")
  sosadmin info "$service" prpath
  if [[ $? -ne 0 ]]; then
    log "ERROR" "Failed to get repo disk for service $service"
    exit 1
  fi
}


function get_projects() {
  # get folder names inside repo disk for project names
  local disk=$1
  local projects=()
  # -d $'\0' tells read to use the null character as the delimiter,
  # which is safer for directory names that may contain spaces or newlines.
  while IFS= read -r -d $'\0' folder; do
    folder=$(basename "$folder")

    if [[ $folder != pg_data ]]; then
      projects+=("$folder")
    fi
  # -print0 tells find to separate the directory names with a null character,
  # which matches the delimiter used by read.
  done < <(find "$disk" -mindepth 1 -maxdepth 1 -type d -print0)

  echo "${projects[@]}"
}

function update_project_acl() {
  local disk="$1"
  local projects=()
  # shellcheck disable=SC2207
  projects=($(get_projects "$disk"))

  for project in "${projects[@]}"; do
    update_sosdcfg "$disk" "$project"
    update_sostcl "$disk" "$project"
  done
}

function list_project_acl() {
  local disk=$1
  local projects=()
  # shellcheck disable=SC2207
  projects=($(get_projects "$disk"))

  for project in "${projects[@]}"; do
    list_soscfg_sostcl "$disk" "$project"
  done
}

function list_soscfg_sostcl() {
  local disk=$1
  local project=$2

  for file in sosd.cfg sos.tcl; do
    local filepath="$disk/$project/setup/$file"
    if [[ ! -e "$filepath" ]]; then
      log "WARNING" "$filepath not found"
    else
      log "INFO" "$filepath"
    fi
  done

}

function update_sosdcfg() {
  local disk=$1
  local project=$2
  dir=$(ls -d "$disk"/"$project"/setup)

    # rename sosd.cfg file
    if [[ ! -f "$dir/sosd.cfg" ]]; then
      log "WARNING" "$dir/sosd.cfg not found"
      return 1
    else
      ls "$dir/sosd.cfg" | xargs -I @ mv @ @.preUpgrade
      # write to new sosd.cfg
      echo -e "-----\n-- 8.1.x upgrade prereqs --\nDEFAULT_GROUP no_group;\nADMIN hlxp4usr;\n-----\n\n" > "$dir"/sosd.cfg
      # append original file to sosd.cfg
      cat "$dir"/sosd.cfg.preUpgrade >> "$dir"/sosd.cfg
      log "INFO" "$dir/sosd.cfg is updated"
    fi
}

function update_sostcl() {
  local disk=$1
  local project=$2
  dir=$(ls -d "$disk"/"$project"/setup)

  # search and replace all matches in the sos.tcl
  tcl_file="$dir"/sos.tcl
  if [[ ! -f "$tcl_file" ]]; then
    log "WARNING" "$tcl_file not found"
    return 1
  else
    cp "$tcl_file" "${tcl_file}".preUpgrade
    sed -i 's/return "all_my_groups"/return ""/g' "$tcl_file"
    log "INFO" "$tcl_file is updated"
  fi
}

function exit_clients() {
  # exit clients
  for service in "${services[@]}"; do
    sosadmin exitclients "$service"
  done

}

function check_server() {
  # checking for server existence
  local server
  server=$(hostname)
  if echo "${SOS_SERVERS[@]}" | grep -qw "$server"; then
    return 0
  else
    log "ERROR" "This is not a primary server"
    return 1
  fi
}

function stop_service() {
  local service=$1
  sosadmin exitclients "$service"
  sosmgr service stop -s "$service"

}

function start_service() {
  local service=$1
  sosmgr service start -s "$service"
}

function upgrade_sos_version() {
  local service=$1
  # sosmgr service change_release --release "$SOS_RELEASE" -s "$service"
  # sosmgr service change_release --cache_only --release "$SOS_RELEASE" -s "$service"
}

function main() {
  local option="$1"
  shift
  local services=("$@")
  local disks=()

  if ! check_server; then
    exit 1
  fi

  if [[ ! "$option" =~ ^-(list|update|start|stop|upgrade)$ ]]; then
    log "ERROR" "Required option: -list, -update"
    exit 1
  fi

  if [[ ${#services[@]} -eq 0 ]]; then
    log "ERROR" "Missing service name(s)"
    exit 1
  fi

  for service in "${services[@]}"; do
    disks+=("$(get_repo_disk "$service")")
  done

  case "$option" in
    -start)
      for service in "${services[@]}"; do
        start_service "$service"
      done
      ;;
    -stop)
      for service in "${services[@]}"; do
        stop_service "$service"
      done
      ;;
    -upgrade)
      for i in "${!services[@]}"; do
        update_project_acl "${disks[i]}"
        upgrade_sos_version "${services[i]}"
      done
      ;;
    -list)
      for disk in "${disks[@]}"; do
        list_project_acl "$disk"
      done
      ;;
    -update)
      for disk in "${disks[@]}"; do
        update_project_acl "$disk"
      done
      ;;
  esac
}

#----------
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
