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

push_files() {
	arr=("$@")
	for i in "${arr[@]}"; do
	echo "$i "
	rm -f /opt/cliosoft/monitoring/tmp/*
	rsync -av /opt/cliosoft/monitoring --delete --exclude={.git,data.csv,sync_files.sh} "$i".intel.com:/opt/cliosoft/
	done
}

#my_function "${array[@]}"
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
	esac
else
	allhosts=("${iil[@]}" "${iind[@]}" "${imul[@]}" "${pdx[@]}" "${png[@]}" "${sc1[@]}" "${sc[@]}" "${zsc10[@]}" "${zsc11[@]}" "${zsc12[@]}" "${zsc3[@]}" "${zsc7[@]}")
	push_files "${allhosts[@]}"
fi
