#!/bin/bash

declare -a iil=("iapp523.iil" "iapp524.iil" "iapp567.iil" "iapp620.iil" "isyn056.iil" "isyn057.iil")
declare -a iind=("inlapp436.iind" "inlapp437.iind" "inlapp476.iind" "inlapp477.iind")
declare -a imu=("musxl0350.imu")
declare -a pdx=("plxs1706.pdx" "plxs1707.pdx" "plxs1708.pdx" "plxs1710.pdx")
declare -a png=("pglhdk62.png" "pglhdk64.png")
declare -a sc1=("scysync114.sc" "scysync115.sc")
declare -a sc4=("scysync132.sc" "scysync133.sc")
declare -a sc8=("scyhlx029.sc" "scyhlx030.sc")
declare -a sc=("scyhdk060.sc" "scyhdk066.sc" "scysync30.sc")
declare -a vr=("vrsxdm01.vr")
declare -a zsc10=("scy0375.zsc10" "scy0376.zsc10" "scysync142.zsc10" "scysync143.zsc10")
declare -a zsc11=("scycliosoft001.zsc11" "scycliosoft002.zsc11")
declare -a zsc12=("scysync212.zsc12" "scysync213.zsc12")
declare -a zsc14=("scysync146.zsc14" "scysync147.zsc14")
declare -a zsc15=("scysync150.zsc15" "scysync151.zsc15")
declare -a zsc16=("scysync152.zsc16" "scysync153.zsc16")
declare -a zsc3=("scysync162.zsc3" "scysync163.zsc3")
declare -a zsc7=("scysync164.zsc7" "scysync165.zsc7")
declare -a zsc9=("scysync144.zsc9" "scysync145.zsc9")

declare -A [moni_host]=("isyn056.iil" "inlapp436.iind" "musxl0350.imu" "plxs1708.pdx"  "pglhdk62.png" "scysync114.sc" "scysync132.sc" "scyhlx029.sc" "scyhdk060.sc" "vrsxdm01.vr" "scysync142.zsc10" "scycliosoft001.zsc11" "scysync212.zsc12" "scysync146.zsc14" "scysync150.zsc15" "scysync152.zsc16" "scysync162.zsc3" "scysync164.zsc7" "scysync144.zsc9")


allhosts=("${iil[@]}" "${iind[@]}" "${imu[@]}" "${pdx[@]}" "${png[@]}" "${sc1[@]}" "${sc[@]}" "${zsc10[@]}" "${zsc11[@]}" "${zsc12[@]}" "${zsc3[@]}" "${zsc7[@]}" "${zsc9[@]}")

#----
check_host() {
  # checking for server existance.
  local host=$1
  match=0
  for h in "${allhosts[@]}";
  do
    if [[ $host =~ $h ]]; then
      echo "-I-: $host found"
      match=1
      break
    fi
  done
  
  [[ $match == 1 ]] || { echo "-E-: hostname not found"; exit 1; }
} # End check_host

#----
view_cron() {
  local host=$1
  file=/tmp/view_cron.txt
  
  echo -e "$host\n======" >> "$file"
  ssh "${host}".intel.com crontab -l >> "$file"
  echo "=====" >> "$file"
  echo "-I: Output cron file to $file"
}

#----
push_files() {
  # copy script(s) to local folder  of each SOS server
  arr=("$@")
  for i in "${arr[@]}"; do
    rm -f /opt/cliosoft/monitoring/tmp/*
    echo -e "${i}.intel.com\n================\n"
    #rsync -av /opt/cliosoft/monitoring --delete --exclude={.git,data.csv,sync_files.sh,sos_check_disk_usage.sh,test.sh} "$i".intel.com:/opt/cliosoft/ &
    rsync -av /opt/cliosoft/monitoring/scripts/{cliosoft_metrics.bash,creat_files_time} --delete  "$i".intel.com:/opt/cliosoft/scripts/ &
    rsync -av /opt/cliosoft/monitoring/{prom_files,tmp} "$i".intel.com:/opt/cliosoft/ &
  done
  wait
}

#----
insert_cron() {
  # this function inserts the texts into cron file.
  host=$1
  
  #/usr/bin/crontab -l >& ~/CRON/CRONTAB.`uname -n`
  #crontab ~/CRON/CRONTAB.###
  
  comm1='# Prometheus monitoring'
  ssh -T ${host}.intel.com 'bash -s' <<-EOL
  (crontab -l > /tmp/crontab_new) >/dev/null 2>&1
  [[ -s /tmp/crontab_new ]] || echo "#" >> /tmp/crontab_new
  sed -i '1s:^:$comm1\n*/5 * * * * /opt/cliosoft/monitoring/scripts/cliosoft_metrics.bash  >/dev/null 2>\&1\n:' /tmp/crontab_new
  crontab /tmp/crontab_new
  rm -f /tmp/crontab_new
  EOL
  
  #ssh "${host}.intel.com" "crontab -l > /tmp/tmpcron; \
  #   sed -i '1s:^:$comm1\n*/5 * * * * /opt/cliosoft/monitoring/scripts/sos_monitor_metrics.bash >/dev/null 2>\&1\n:' /tmp/tmpcron; \
  #   crontab /tmp/tmpcron; \"
  #   rm -f /tmp/tmpcron"
  #echo -e "${cmd[*]}"
  
  # test
  #ssh "${host}".intel.com 'ls /opt/cliosoft'
  #1echo "${cmd[@]}"
  
  [[ $? == 0 ]] || { echo "-E-: Error with insert_cron result"; exit 1; }
} # End insert_cron

#----
update_cron() {
  # funtion udate email line in cron file
  local host=$1
  ssh -T ${host}.intel.com 'bash -s' <<-EOL2
  (crontab -l > /tmp/crontab_new) >/dev/null 2>&1
  sed -i 's:linh.a.nguyen:it.ddm.sos.adm:' /tmp/crontab_new
  crontab /tmp/crontab_new
  rm -f /tmp/crontab_new
  EOL2
} # end update_cron

#----
if [[ "$#" -eq 1 ]]; then
  case "$1" in
    iil) push_files "${iil[@]}";;
    iind) push_files "${iind[@]}";;
    imu) push_files "${imul[@]}";;
    pdx) push_files "${pdx[@]}";;
    png) push_files "${png[@]}";;
    sc1) push_files "${sc1[@]}";;
    sc4) push_files "${sc4[@]}";;
    sc8) push_files "${sc8[@]}";;
    sc) push_files "${sc[@]}";;
    zsc10) push_files "${zsc10[@]}";;
    zsc11) push_files "${zsc11[@]}";;
    zsc12) push_files "${zsc12[@]}";;
    zsc3) push_files "${zsc3[@]}";;
    zsc7) push_files "${zsc7[@]}";;
    zsc9) push_files "${zsc7[@]}";;
    vr) push_files "${vr[@]}";;
    *) echo "-E-: Incorrect usage";;
  esac
  elif [[ "$#" -eq 2 ]]; then
  case "$1" in
    # I want to insert the cron only
    insert_cron)
      if [[ $2 == --all ]]; then
        # do all
        for srv in "${allhosts[@]}"; do
          # skip imu side because cron is too crowded with P4 configs.
          [[ $srv =~ imu ]] && continue || true
          "$1" "$srv"
        done
      else
        # do by host
        check_host "$2"
        "$@"
      fi
    ;;
    # I want to update cron only
    update_cron)
      if [[ $2 == --all ]]; then
        for srv in "${allhosts[@]}"; do
          # skip imu side because cron is too crowded with P4 configs.
          [[ $srv =~ imu ]] && continue || true
          "$1" "$srv"
        done
      else
        check_host "$2"
        "$@"
      fi
    ;;
    # I want to view the cron file of all or by server name
    view_cron)
      if [[ $2 == --all ]]; then
        for srv in "${allhosts[@]}"; do "$1" "$srv"; done
      else
        check_host "$2"
        "$@"
      fi
    ;;
    *)
      echo -e "-E-: Incorrect usage\n" \
      "[insert_cron | view_cron][ host|--all]"
    ;;
  esac
else
  # no option specified, default is to update script to all sites.
  push_files "${allhosts[@]}"
fi
