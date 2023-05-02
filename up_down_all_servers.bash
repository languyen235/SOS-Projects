#!/bin/bash
# Script stop SOS service at all sites

#set -exuo pipefail
#set -x
#export PS4='Line $LINENO: '

## global $CLIOSOFT_DIR variables
[[ -z $CLIOSOFT_DIR ]] && { export CLIOSOFT_DIR=/opt/cliosoft/latest; export PATH=$CLIOSOFT_DIR/bin:$PATH; } || true
[[ -e "$CLIOSOFT_DIR"/bin ]] || { echo '-F: Cliosoft binary not found'; exit 1; }

[[ $EC_ZONE ]] && export site="$EC_ZONE" || export site=$(hostname -y)

LOG=/tmp/sos_shutdown_all.txt
[[ -d logUP ]] || mkdir -p logUP
[[ -d logDOWN ]] || mkdir -p logDOWN
[[ -d logTEST ]] || mkdir -p logTEST

SHUTDOWN_INFO_LOG=/tmp/sos_shutdown_info.log
SHUTDONW_DEBUG_LOG=/tmp/sos_shutdown_debug.log


SOS_SERVICE_REMOTE='/nfs/site/disks/sos_adm/share/SERVERS7/REMOTE'
SOS_SERVICE_LOCAL='/nfs/site/disks/sos_adm/share/SERVERS7/LOCAL'
service_local='/opt/cliosoft/latest/SERVERS/REMOTE'
service_remote='/opt/cliosoft/latest/SERVERS/LOCAL'


shutdown_srvs='/opt/cliosoft/latest/bin/stop_all_servers.sh'
startup_srvs='/opt/cliosoft/latest/bin/start_all_servers.sh'
shutdown_sosmgr='/opt/cliosoft/latest/bin/sosmgr site stop'
startup_sosmgr='/opt/cliosoft/latest/bin/sosmgr site start'
test_sosmgr='/opt/cliosoft/latest/bin/sosmgr site ping'


declare -A sites
declare -a sc sc1 sc4 sc8 zsc3 zsc7 zsc9 zsc10 zsc11 zsc12 zsc14 zsc15 zsc16 pdx png iind iil imu

#sc=(scyhdk060.sc scyhdk066.sc)
sc=(scyhdk060.sc scyhdk066.sc)
sc1=(scysync114.sc scysync115.sc)
sc4=(scysync132.sc scysync133.sc)
sc8=(scyhlx029 scyhlx030)
zsc3=(scysync162.zsc3 scysync163.zsc3)
zsc7=(scysync164.zsc7 scysync165.zsc7)
zsc9=(scysync144.zsc9 scysync145.zsc9)
zsc10=(scysync142.zsc10 scysync143.zsc10)
zsc11=(scycliosoft001.zsc11 scycliosoft002.zsc11)
zsc12=(scysync212.zsc12 scysync213.zsc12)
zsc14=(scysync146.zsc14 scysync147.zsc14)
zsc15=(scysync150.zsc15 scysync151.zsc15)
zsc16=(scysync152.zsc16 scysync153.zsc16)
pdx=(plxs1706.pdx plxs1707.pdx plxs1708.pdx plxs1710.pdx plxs1711.pdx)
png=(pglhdk62.png pglhdk64.png)
iind=(inlapp436.iind inlapp437.iind)
iil=(isyn056.iil isyn057.iil iapp523.iil iapp524.iil iapp567.iil iapp620.iil)
imu=musxl0350.imu

sos_hosts=(scyhdk060.sc scysync114.sc scysync132.sc scysync162.zsc3 scysync164.zsc7 scysync144.zsc9 scysync142.zsc10 scycliosoft001.zsc11 scysync212.zsc12 scysync146.zsc14 scysync150.zsc15 plxs1708.pdx pglhdk62.png inlapp436.iind isyn056.iil musxl0350.imu)

us_hosts=(scyhdk060.sc scysync114.sc scysync132.sc scysync162.zsc3 scysync164.zsc7 scysync144.zsc9 scysync142.zsc10 scycliosoft001.zsc11 scysync212.zsc12 scysync146.zsc14 scysync150.zsc15 plxs1708.pdx)

other_hosts=(pglhdk62.png inlapp436.iind isyn056.iil musxl0350.imu)

host1=(scysync30.sc)
host2=(inlapp476.iind)
testhosts=(scysync30.sc inlapp476.iind)

declare -gA list_pid

shutdown() {
local hosts=("$@")
    for host in ${hosts[@]}; do
    #for host in "$sos_hosts[@]"; do
        echo "-I: Shutting down SOS on $host"
        ssh hlxp4usr@"${host}.intel.com" "eval $shutdown_srvs; eval $shutdown_sosmgr" 2>&1  | tee "logDOWN/$host"_shutdown.txt &
        list_pid[$host]=$!
    done
}

startup() {
local hosts=("$@")
    for host in ${hosts[@]}; do
        echo "-I: Starting up SOS on $host"
        ssh hlxp4usr@"${host}".intel.com "eval $startup_srvs; eval $startup_sosmgr" 2>&1 | tee "logUP/$host"_startup.txt &
        list_pid[$host]=$!
    done
}

testing() {
local hosts=("$@")
    for host in "${hosts[@]}"; do
        echo "-I: Tesing SOS on $host"
        ssh hlxp4usr@"${host}".intel.com  "eval $test_sosmgr" 2>&1 | tee "logTEST/$host"_testing.txt &
        list_pid[$host]=$!
    done
}

#----
help() {
cat <<-EOF | sed '4,10s:^:\t:g'
Usuage: ${0##*/} [--function | (-h|-help)]

functions:
[-h|-help] : Print help()
-up us|others|testhosts
-down us|others|testhosts
-test us|others|testhosts
EOF
exit
}

#----
fail() {
    printf '%s\n' "$1" "$2"
    exit "${2-1}"
}

########################################
while [[ $# -gt 0 ]]; do
    case "$1" in
    "")
        echo -e "\n-E: Missing argument"
        help
        ;;
    -h|-help)
        help
        ;;
    -down)
        [[ -z ${2+.} ]] && fail "No site(s) site specified to '$1'."
        [[ ${2} == us ]] && shutdown "${us_hosts[@]}"
        [[ ${2} == others ]] && shutdown "${other_hosts[@]}" 
        [[ ${2} == testhosts ]] && shutdown "${testhosts[@]}"
        shift
        ;;
    -up)
        [[ -z ${2+.} ]] && fail "No site(s) site specified to '$1'."
        [[ ${2} == us ]] && startup "${us_hosts[@]}"
        [[ ${2} == others ]] && startup "${other_hosts[@]}"
        [[ ${2} == testhosts ]] && startup "${testhosts[@]}"
        shift
        ;;
    -test)
        [[ -z ${2+.} ]] && fail "No site(s) site specified to '$1'."
        [[ ${2} == us ]] && testing "${us_hosts[@]}"
        [[ ${2} == others ]] && testing "${other_hosts[@]}"
        [[ ${2} == testhosts ]] && testing "${testhosts[@]}"
        shift
        ;;
    esac
    shift
done


for srv in "${!list_pid[@]}"
do
  wait "${list_pid[$srv]}"
  test $? -ne 0 && { echo "-E: $srv had problem" >&2 && continue; } 
  unset "list_pid[$srv]"
done
exit $?
