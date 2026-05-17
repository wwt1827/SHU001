
from flask import Flask

# 创建 Flask 应用
app = Flask(__name__)

# 首页路由
@app.route('/')
def home():
    return "Building Crack Detection System Running!"

# 启动服务器
if __name__ == '__main__':
    app.run(debug=True)