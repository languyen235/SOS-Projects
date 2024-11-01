#!/usr/intel/pkgs/python3/3.11.1/bin/python3.11

def send_email(subject, body, to_email, from_email):
    import smtplib
    # Import the email modules we'll need
    from email.message import EmailMessage

    # with open(textfile) as fp:
    #   # Create a text/plain message
    #   msg = EmailMessage()
    #   msg.set_content(fp.read())

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email
    msg.set_content(body)
    
    # Send the message via our own SMTP server.
    s = smtplib.SMTP('localhost')
    s.send_message(msg)
    s.quit()
    print("Email sent...")

