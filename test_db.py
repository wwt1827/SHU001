import pymysql

# 连接数据库
db = pymysql.connect(
    host="localhost",      # 数据库地址
    user="root",           # 数据库用户名
    password="123456",     # 你的MySQL密码
    database="crack_system" # 数据库名
)

print("数据库连接成功！")