import smtplib

server = smtplib.SMTP("smtp.qq.com", 587)
server.starttls()

server.login("3149156597@qq.com", "rikodwitsvhudfii")

print("SMTP login success")
