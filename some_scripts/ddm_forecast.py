#!/usr/intel/pkgs/python3/3.12.3/bin/python3.12

from UsrIntel.R1 import os, sys
import datetime as dt
import argparse

def increase_value_by_month(value, start_date, end_date, increase_percentage):
    """Increases a value by a given percentage each month between two dates.
    Args:
        value: The initial value.
        start_date: The starting date (datetime.date object).
        end_date: The ending date (datetime.date object).
        increase_percentage: The percentage increase per month.
    Returns:
        The final value after applying the monthly increases.
    """
    current_date = start_date
    while current_date <= end_date:
        monthly_increase = value * (increase_percentage / 100)
        value +=  monthly_increase
        print('{}: {:0.2f}'.format(current_date.strftime("%b-%Y"), value))

        # move to next month 
        current_date += dt.timedelta(days=31)
        
    

def main():
    today = dt.date.today()
    
    parser = argparse.ArgumentParser(
        description='Increases a value by a given percentage each month between two months',
        epilog='Example usage: {} 105.5 2.5 3 12'.format(os.path.basename(__file__))
    )
    parser.add_argument('init_value', type=float, help='Integer or float number for initial value')
    parser.add_argument('increase_percent', type=float, help='Integer or float number for increase percents')
    parser.add_argument('from_month', type=int, help='Integer between 1 and 12 for month; Jan=1, Feb=2, .... Dec=12')
    parser.add_argument('to_month', type=int , help='Integer between 1 and 12 for month; Jan=1, Feb=2, ... Dec=12')
    
    if len(sys.argv) == 1:
        parser.print_help()
        # parser.print_usage() # for just the usage line
        parser.exit() 
    
    args = parser.parse_args()
    
    if not 1 <= args.from_month <=12: parser.error("Value must be in the range 1-12 for month. Example:Jan=1, Feb=2, ... Dec=12")
    
    initial_value= args.init_value
    increase_percentage = args.increase_percent
    start_month = args.from_month
    end_month = args.to_month


    start_date = dt.date(today.year, start_month, 1)
    
    # if end < start then end_month  is in the next year
    if end_month <= start_month: 
        end_date = dt.date(today.year + 1, end_month, 31) # must specify the last day in the end_month
    else:
        end_date = dt.date(today.year, end_month, 31)  # must specify the last day in the end_month 

    increase_value_by_month(initial_value, start_date, end_date, increase_percentage)



if __name__ == '__main__':
    main()