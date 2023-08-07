#!/bin/bash

srv=${1?Need service name}
[[ $(ps -elf |grep soscd | grep "$srv") ]] || { echo "-E: Cache deamon for $srv not found on this host... "; exit 1; }

export workdir=/opt/cliosoft/orphaned_files_OUT/${srv}
echo "-I: mkdir -p ${workdir}"
mkdir -p ${workdir} || { echo "-E: Cannot mkdir ${workdir}"; exit 1; }

## listing SOS projects to array
declare -a projects=($(sosadmin projects "$srv"))

find_ophans() {
   for p in "${projects[@]}"; do
        echo "-I: ${workdir}/${p}.txt"
        ./sosGetCacheInfo "$srv" "$p" | tee  ${workdir}/${p}.txt &
   done
   wait
}

remove_orphans() {
# remove ophaned files in cache disks
# # search files matches for ORPHANED words; repleacing matches with rm -f changes to *.sh file
pushd ${workdir} >/dev/null 2>&1
echo "-I: Workdir $(pwd)"
files+=($(ls *.txt))
    for file in "${files[@]}"; do
        # search files matches content and cyange matched keywords to rm -r and output 
        if grep '^ORPHANED' "$file" ; then
            exc_file="${file/.txt/.sh}"
            chmod +x "$exc_file"
            tail -n +5 $file | sed 's|ORPHANED FILE :|rm -f|g' > "$exc_file"
            chmod +x "$exc_file"
            #./"$exc_file" &
        else
            continue
        fi
    done
wait
popd >/dev/null 2>&1
}

find_ophans
remove_orphans
