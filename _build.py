"""Build the new main.py"""
import os

DEST = "main.py"

# We'll write the file in sections
with open(DEST, 'w', encoding='utf-8') as f:
    
    f.write('''"""
主启动脚本 - 统一入口
提供菜单选择不同功能
集成 CrackBot 后端服务（接收树莓派上传照片）
包含用户管理、巡检工单、报告生成等完整功能
"""
import os
import sys
import json
import sqlite3
import hashlib
import secrets
from datetime import datetime
from threading import Thread

os.environ['OMP_NUM_THREADS'] = '2'

_VENV_PYTHON = r'E:\\\\torch\\\\.venv\\\\Scripts\\\\python.exe'
DB_PATH = 'crackbot.db'

flask_app = None
flask_thread = None
BACKEND_STARTED = False
LOCAL_IP = "127.0.0.1"
NEW_IMAGE_FLAG = False
LAST_IMAGE_ID = 0
YOLO_MODEL = None
MODEL_LOADED = False
AUTH_TOKENS = {}

''')

    f.write('''
def init_database():
    """Initialize SQLite database"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Create sessions table
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        image_count INTEGER DEFAULT 0)''')

    # Create images table with detection fields
    c.execute('''CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        filepath TEXT NOT NULL,
        result_path TEXT,
        segment INTEGER DEFAULT 0,
        blur_score REAL DEFAULT 0.0,
        quality_ok INTEGER DEFAULT 0,
        num_cracks INTEGER DEFAULT 0,
        avg_confidence REAL DEFAULT 0.0,
        crack_area_ratio REAL DEFAULT 0.0,
        severity TEXT,
        upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        detect_time TIMESTAMP,
        client_ip TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions(session_id))''')

    # Create users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'inspector',
        display_name TEXT,
        email TEXT,
        phone TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP)''')

    # Create work_orders table
    c.execute('''CREATE TABLE IF NOT EXISTS work_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        building_name TEXT,
        floor TEXT,
        inspector_id INTEGER,
        inspector_name TEXT,
        session_id TEXT,
        status TEXT DEFAULT 'pending',
        priority TEXT DEFAULT 'normal',
        image_count INTEGER DEFAULT 0,
        crack_count INTEGER DEFAULT 0,
        max_severity TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        notes TEXT,
        FOREIGN KEY (inspector_id) REFERENCES users(id),
        FOREIGN KEY (session_id) REFERENCES sessions(session_id))''')

    # Create inspection_reports table
    c.execute('''CREATE TABLE IF NOT EXISTS inspection_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_order_id INTEGER,
        report_number TEXT UNIQUE NOT NULL,
        summary TEXT,
        total_images INTEGER DEFAULT 0,
        images_with_cracks INTEGER DEFAULT 0,
        max_crack_ratio REAL DEFAULT 0.0,
        overall_severity TEXT,
        report_html TEXT,
        generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (work_order_id) REFERENCES work_orders(id))''')

    # Create default admin user
    admin_hash = hashlib.sha256('admin123'.encode()).hexdigest()
    c.execute('''INSERT OR IGNORE INTO users (username, password_hash, role, display_name, email, phone)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              ('admin', admin_hash, 'admin', 'System Admin', 'admin@crackbot.com', '13800000000'))

    # Create default inspector
    ins_hash = hashlib.sha256('inspector1'.encode()).hexdigest()
    c.execute('''INSERT OR IGNORE INTO users (username, password_hash, role, display_name, email, phone)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              ('inspector', ins_hash, 'inspector', 'Inspector Zhang', 'zhang@crackbot.com', '13900000001'))

    conn.commit()
    conn.close()
    print(f"[INFO] Database initialized: {DB_PATH}")
''')

print("Phase 1 complete - database schema written")
''')
```

Now let me run this build script to check it works, then continue adding more sections.我们用更高效的方法：直接通过 Python 解释器执行一个完整的生成脚本。让我用 `python -c` 执行一个紧凑的生成器：



```tool
TOOL_NAME: run_terminal_command
BEGIN_ARG: command
"python _build.py"