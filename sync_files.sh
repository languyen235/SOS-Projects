#!/bin/bash

iil=("iapp523.iil" "iapp524.iil" "iapp567.iil" "iapp620.iil" "isyn056.iil" "isyn057.iil")
iind=("inlapp436.iind" "inlapp437.iind" "inlapp476.iind" "inlapp477.iind")
imu=("musxl0350.imu")
pdx=("plxs1706.pdx" "plxs1707.pdx" "plxs1708.pdx" "plxs1710.pdx")
png=("pglhdk62.png" "pglhdk64.png")
sc1=("scysync114.sc" "scysync115.sc")
sc=("scyhdk060.sc" "scyhdk066.sc" "scysync30.sc")
vr=("vrsxdm01.vr")
zsc10=("scy0375.zsc10" "scy0376.zsc10" "scysync142.zsc10" "scysync143.zsc10")
zsc11=("scycliosoft001.zsc11" "scycliosoft002.zsc11")
zsc12=("scysync212.zsc12" "scysync213.zsc12")
zsc3=("scysync162.zsc3" "scysync163.zsc3")
zsc7=("scysync164.zsc7" "scysync165.zsc7")

allhosts=("${iil[@]}" "${iind[@]}" "${imul[@]}" "${pdx[@]}" "${png[@]}" "${sc1[@]}" "${sc[@]}" "${zsc10[@]}" "${zsc11[@]}" "${zsc12[@]}" "${zsc3[@]}" "${zsc7[@]}")

#----
check_host() {
local host=$1
match=0
	#for h in "${iil[@]}" "${iind[@]}" "${imu[@]}" "${pdx[@]}" "${png[@]}" "${sc1[@]}" "${sc[@]}" "${vr[@]}" "${zsc10[@]}" "${zsc11[@]}" "${zsc12[@]}" "${zsc3[@]}" "${zsc7[@]}";
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
}

#----
push_files() {
	arr=("$@")
	for i in "${arr[@]}"; do
	rm -f /opt/cliosoft/monitoring/tmp/*
	rsync -av /opt/cliosoft/monitoring --delete --exclude={.git,data.csv,sync_files.sh} "$i".intel.com:/opt/cliosoft/ &
	done
	wait
}

#----
insert_cron() {
host=$1

#/usr/bin/crontab -l >& ~/CRON/CRONTAB.`uname -n`
#crontab ~/CRON/CRONTAB.###

	comm1='# Prometheus monitoring'
	ssh  -T ${host}.intel.com 'bash -s' <<-EOL
	(crontab -l > /tmp/crontab_new) >/dev/null 2>&1
	[[ -s /tmp/crontab_new ]] || echo "#" >> /tmp/crontab_new  
	sed -i '1s:^:$comm1\n*/5 * * * * /opt/cliosoft/monitoring/scripts/cliosoft_metrics.bash  >/dev/null 2>\&1\n#\n:' /tmp/crontab_new
	crontab /tmp/crontab_new
	rm -f /tmp/crontab_new
	EOL

	#ssh "${host}.intel.com" "crontab -l > /tmp/tmpcron; \
	#		sed -i '1s:^:$comm1\n*/5 * * * * /opt/cliosoft/monitoring/scripts/sos_monitor_metrics.bash >/dev/null 2>\&1\n:' /tmp/tmpcron; \
	#		crontab /tmp/tmpcron; \"
	#		rm -f /tmp/tmpcron"
	#echo -e "${cmd[*]}"
	
	# test
	#ssh "${host}".intel.com 'ls /opt/cliosoft'
	#1echo "${cmd[@]}"
	
	[[ $? == 0 ]] || { echo "-E-: Error with insert_cron result"; exit 1; }
} # End insert_cron

#----
if [[ "$#" -eq 1 ]]; then
	case "$1" in
		iil) push_files "${iil[@]}";;
		iind) push_files "${iind[@]}";;
		imu) push_files "${imul[@]}";;
		pdx) push_files "${pdx[@]}";;
		png) push_files "${png[@]}";;
		sc1) push_files "${sc1[@]}";;
		sc) push_files "${sc[@]}";;
		zsc10) push_files "${zsc10[@]}";;
		zsc11) push_files "${zsc11[@]}";;
		zsc12) push_files "${zsc12[@]}";;
		zsc3) push_files "${zsc3[@]}";;
		zsc7) push_files "${zsc7[@]}";;
		vr) push_files "${vr[@]}";;
		*) echo "-E-: Incorrect usage";;
	esac
elif [[ "$#" -eq 2 ]]; then
	case "$1" in 
		insert_cron)
			if [[ $2 == --all ]]; then
				# do all
				for srv in "${allhosts[@]}"; do 
					[[ $srv =~ imu ]] && continue || true 
					"$1" "$srv"
				done
			else
				# do by host
				check_host "$2"
				"$@"
			fi
		;;
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
	push_files "${allhosts[@]}"
fi
