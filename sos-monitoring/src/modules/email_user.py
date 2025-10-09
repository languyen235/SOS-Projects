#!/usr/intel/pkgs/python3/3.11.1/bin/python3.11

import smtplib
from email.message import EmailMessage
from typing import List

def send_email(subject, body: List [str], to_email, from_email):
    """ Send email to user"""

    # with open(textfile) as fp:
    #   # Create a text/plain message
    #   msg = EmailMessage()
    #   msg.set_content(fp.read())

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email
    msg.set_content("\n".join(body))
    
    # Send the message via our own SMTP server.
    s = smtplib.SMTP('localhost')
    s.send_message(msg)
    s.quit()
    print("Email sent...")

