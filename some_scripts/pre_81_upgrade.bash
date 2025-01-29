#!/bin/bash
#
# : '
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

function Get_Repo_Disk() {
  local service=$1
  #dir=$(dirname "$(sosadmin info "$service" prpath)")
  sosadmin info "$service" prpath
}

function Update_Project_ACL() {
  # get folder names inside repo disk for project names
  local disk=$1
  local projects=()
  # -d $'\0' tells read to use the null character as the delimiter, 
  # which is safer for directory names that may contain spaces or newlines.
  while IFS= read -r -d $'\0' folder; do
    folder=$(basename "$folder")
    if [[ $folder == pg_data ]]; then
      continue
    else
      projects+=("$folder")
    fi
  # -print0 tells find to separate the directory names with a null character, 
  # which matches the delimiter used by read.
  done < <(find "$disk" -mindepth 1 -maxdepth 1 -type d -print0)
  
  # for project in "${projects[@]}"; do
  #   # # rename sosd.cfg file
  #   # ls "$disk/$project/setup/sosd.cfg" | xargs -I @ mv @ @.preUpgrade
    
  #   # # write to new sosd.cfg
  #   # dir=$(ls -d "$disk"/"$project"/setup)
  #   # echo -e "-----\n-- 8.1.x upgrade prereqs --\nDEFAULT_GROUP no_group;\nADMIN hlxp4usr;\n-----\n\n" > "$dir"/sosd.cfg
  #   # # append orignal file to sosd.cfg
  #   # cat "$dir"/sosd.cfg.preUpgrade >> "$dir"/sosd.cfg

  #   # # search and replce all matches in the sos.tcl
  #   # tcl_file=$(ls "$disk"/"$project"/setup/sos.tcl)
  #   # cp "$tcl_file" "${tcl_file}".preUpgrade
  #   # sed -i 's/return "all_my_groups"/return ""/g' "$tcl_file" 
  # done

  for project in "${projects[@]}"; do
    #List_sosdcfg_sostcl "$disk" "$project"
    Update_ssodcfg_sostcl "$disk" "$project"
  done
}

function List_sosdcfg_sostcl() {
  local disk=$1
  local project=$2
  ls "$disk/$project/setup/sosd.cfg"
  ls "$disk"/"$project"/setup/sos.tcl
}

function Update_ssodcfg_sostcl() {
  local disk=$1
  local project=$2
    # rename sosd.cfg file
    ls "$disk/$project/setup/sosd.cfg" | xargs -I @ mv @ @.preUpgrade
    
    # write to new sosd.cfg
    dir=$(ls -d "$disk"/"$project"/setup)
    echo -e "-----\n-- 8.1.x upgrade prereqs --\nDEFAULT_GROUP no_group;\nADMIN hlxp4usr;\n-----\n\n" > "$dir"/sosd.cfg
    # append orignal file to sosd.cfg
    cat "$dir"/sosd.cfg.preUpgrade >> "$dir"/sosd.cfg

    # search and replce all matches in the sos.tcl
    tcl_file=$(ls "$disk"/"$project"/setup/sos.tcl)
    cp "$tcl_file" "${tcl_file}".preUpgrade
    sed -i 's/return "all_my_groups"/return ""/g' "$tcl_file" 
}

function Main() {
  local services=()
  local disks=()
  services+=("$@")
  
  for service in "${services[@]}"; do
    disks+=("$(Get_Repo_Disk "$service")")
  done

  echo "${disks[@]}"

  for disk in "${disks[@]}"; do
    Update_Project_ACL "$disk"
  done
}

#----------
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  Main "$@"
fi
