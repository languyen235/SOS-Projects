#!/usr/intel/pkgs/python3/3.12.3/bin/python3.12

from UsrIntel.R1 import os, sys
import subprocess


def get_number_services():
    number_services: int
    # for s in ${sites[@]}; do
    #   # inner function returns service number; outer function add  number to variable; the & running job in background
    #   services=$((services + $(ssh -t sosmgr-"$s".sync.intel.com "/opt/cliosoft/latest/bin/sosadmin list | wc -l" &)))

    return number_services


def main():
    import calendar
    import datetime
    import argparse
    today = datetime.date.today()
    days = calendar.monthrange(today.year, today.month)[1]  # days in current month
    month_name = calendar.month_name[today.month]  # current month name
    
    parser = argparse.ArgumentParser(
        description='Script returns a percentage uptime of current month',
        epilog='Example usage: {} 399 38 5'.format(os.path.basename(__file__))
    )
    parser.add_argument("num_services", type=int, help='Number of services')
    parser.add_argument("num_hits", type=int, help='Number of services were impacted')
    parser.add_argument("lost_hours", type=int, help='Number of hours lost') 
    
    if len(sys.argv) == 1:
        parser.print_help()
        # parser.print_usage() # for just the usage line
        parser.exit()  
    args = parser.parse_args()
    
    
    # (services) x (days in month) x 24 hrs = potential uptime of the the month
    potential_uptime = (args.num_services * days * 24)
    total_downtime = (args.num_hits * args.lost_hours)
    actual_uptime = (potential_uptime - total_downtime)
    
    array = []
    array.append('Expecting 24x7 uptime in {} = {}'.format(month_name, potential_uptime))
    array.append('Number services affected by downtime/incident = {}'.format(args.num_hits))
    array.append('Total offline hours = {} hour(s)'.format(args.lost_hours))
    array.append('Percentage uptime in {} = {:.2f}%'.format(
        month_name, (actual_uptime / potential_uptime * 100)))
    
    decor = f"{'-'* len(max(array, key=len))}"  # max() for a longest string
    print(f"{decor}\n" + f"{'\n'.join(array)}\n" + f"{decor}\n")

if __name__ == '__main__':
    main()


