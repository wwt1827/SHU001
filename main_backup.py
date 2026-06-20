"""
CrackBot 后端服务 - 接收树莓派上传的照片

功能:
  - 接收树莓派上传的检测图片(multipart/form-data)
  - 保存图片到本地目录
  - 记录元数据到日志/数据库
  - 健康检查接口
  - 简单的用户身份管理
"""

import os
import json
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'crackbot_secret_key_2024'  # 用于 session 加密

# 配置
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}
USERS_FILE = os.path.join(UPLOAD_FOLDER, "users.json")
WORKORDERS_FILE = os.path.join(UPLOAD_FOLDER, "workorders.json")

# 确保目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, "images"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, "logs"), exist_ok=True)

# 初始化默认管理员账户
if not os.path.exists(USERS_FILE):
    default_users = {
        "admin": {
            "password": generate_password_hash("admin123"),
            "role": "admin",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    }
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(default_users, f, ensure_ascii=False, indent=2)

MODEL_PATH = r"E:\University_files\embed\runs\segment\crack_seg_finetune2\weights\last.pt"
RESULT_FOLDER = os.path.join(UPLOAD_FOLDER, "results")
os.makedirs(RESULT_FOLDER, exist_ok=True)

YOLO_MODEL = None


# ========== 用户身份管理 ==========

def load_users():
    """从 JSON 文件加载所有用户"""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_users(users):
    """保存用户数据到 JSON 文件"""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def login_required(f):
    """装饰器：要求用户登录后才能访问"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({"error": "未登录，请先登录"}), 401
        return f(*args, **kwargs)
    return decorated_function


# ========== 巡检工单管理 ==========

def load_workorders():
    """从 JSON 文件加载所有工单"""
    if os.path.exists(WORKORDERS_FILE):
        with open(WORKORDERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_workorders(workorders):
    """保存工单列表到 JSON 文件"""
    with open(WORKORDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(workorders, f, ensure_ascii=False, indent=2)


def generate_workorder_id():
    """生成工单 ID"""
    return datetime.now().strftime("WO%Y%m%d%H%M%S%f")[:-3]


def get_workorder_sessions_summary(workorder):
    """汇总工单关联的所有会话的检测数据"""
    sessions = workorder.get('sessions', [])
    total_images = 0
    total_cracks = 0
    sessions_with_cracks = set()
    logs_dir = os.path.join(UPLOAD_FOLDER, "logs")
    for session_id in sessions:
        log_path = os.path.join(logs_dir, f"{session_id}.json")
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    entries = json.load(f)
                total_images += len(entries)
                for entry in entries:
                    detection = entry.get('detection')
                    if detection and detection.get('num_cracks', 0) > 0:
                        total_cracks += detection['num_cracks']
                        sessions_with_cracks.add(session_id)
            except Exception:
                pass
    return {
        'total_images': total_images,
        'total_cracks': total_cracks,
        'sessions_with_cracks': len(sessions_with_cracks)
    }


# ========== 原有功能函数 ==========


def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def load_yolo_model():
    global YOLO_MODEL
    if YOLO_MODEL is not None:
        return YOLO_MODEL
    from ultralytics import YOLO
    YOLO_MODEL = YOLO(MODEL_PATH)
    app.logger.info(f"YOLO模型加载成功: {MODEL_PATH}")
    return YOLO_MODEL


def detect_cracks(image_path, conf_threshold=0.25, iou_threshold=0.7):
    model = load_yolo_model()
    if model is None:
        return None, None
    results = model.predict(
        source=image_path,
        conf=conf_threshold,
        iou=iou_threshold,
        verbose=False
    )
    result = results[0]
    annotated_img = result.plot()
    num_cracks = len(result.boxes)
    avg_confidence = 0.0
    crack_area_ratio = 0.0
    severity = "无裂缝"
    if num_cracks > 0:
        confidences = result.boxes.conf.cpu().numpy()
        avg_confidence = confidences.mean()
        if result.masks is not None:
            total_area = sum(mask.sum().item() for mask in result.masks.data)
            img_area = result.orig_img.shape[0] * result.orig_img.shape[1]
            crack_area_ratio = (total_area / img_area * 100)
            if crack_area_ratio > 5.0:
                severity = "严重"
            elif crack_area_ratio > 2.0:
                severity = "中等"
            else:
                severity = "轻微"
    return annotated_img, {
        'num_cracks': num_cracks,
        'avg_confidence': float(avg_confidence),
        'crack_area_ratio': float(crack_area_ratio),
        'severity': severity
    }


# ========== 用户认证 API ==========

@app.route('/api/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供用户名和密码"}), 400

    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400

    users = load_users()
    user = users.get(username)

    if user is None or not check_password_hash(user['password'], password):
        return jsonify({"error": "用户名或密码错误"}), 401

    session['username'] = username
    session['role'] = user.get('role', 'user')
    return jsonify({
        "status": "success",
        "message": f"欢迎回来，{username}！",
        "username": username,
        "role": user.get('role', 'user')
    })


@app.route('/api/register', methods=['POST'])
def register():
    """用户注册（仅管理员可注册新用户）"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供注册信息"}), 400

    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400
    if len(username) < 2:
        return jsonify({"error": "用户名至少需要2个字符"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码至少需要6个字符"}), 400

    users = load_users()
    if username in users:
        return jsonify({"error": "用户名已存在"}), 409

    # 只有登录的管理员才能注册新用户
    if 'username' not in session or session.get('role') != 'admin':
        return jsonify({"error": "只有管理员才能注册新用户"}), 403

    users[username] = {
        "password": generate_password_hash(password),
        "role": "user",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_users(users)
    return jsonify({
        "status": "success",
        "message": f"用户 {username} 注册成功"
    })


@app.route('/api/logout', methods=['POST'])
def logout():
    """用户登出"""
    username = session.pop('username', None)
    session.pop('role', None)
    return jsonify({
        "status": "success",
        "message": f"已登出{'，再见 ' + username if username else ''}"
    })


@app.route('/api/me', methods=['GET'])
@login_required
def current_user():
    """获取当前登录用户信息"""
    return jsonify({
        "username": session.get('username'),
        "role": session.get('role', 'user')
    })


@app.route('/login')
def login_page():
    """登录页面"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>登录 - 墙面裂缝检测系统</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;display:flex;justify-content:center;align-items:center;min-height:100vh}
.login-box{background:rgba(30,41,59,0.8);border:1px solid rgba(148,163,184,0.12);border-radius:16px;padding:40px;width:380px;backdrop-filter:blur(10px)}
.login-box h1{font-size:22px;text-align:center;margin-bottom:8px}
.login-box .subtitle{text-align:center;color:#64748b;font-size:13px;margin-bottom:28px}
.form-group{margin-bottom:18px}
.form-group label{display:block;font-size:13px;color:#94a3b8;margin-bottom:6px}
.form-group input{width:100%;padding:10px 14px;background:rgba(15,23,42,0.6);border:1px solid rgba(148,163,184,0.15);border-radius:8px;color:#e2e8f0;font-size:14px;outline:none;transition:border-color 0.2s}
.form-group input:focus{border-color:#38bdf8}
.btn{width:100%;padding:11px;background:#38bdf8;color:#0f172a;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;transition:background 0.2s}
.btn:hover{background:#7dd3fc}
.error-msg{color:#fca5a5;font-size:13px;text-align:center;margin-top:12px;display:none}
</style>
</head>
<body>
<div class="login-box">
<h1>&#128269; 墙面裂缝检测系统</h1>
<div class="subtitle">请登录以继续</div>
<form id="loginForm">
<div class="form-group">
<label>&#128100; 用户名</label>
<input type="text" id="username" placeholder="请输入用户名" required autofocus>
</div>
<div class="form-group">
<label>&#128274; 密码</label>
<input type="password" id="password" placeholder="请输入密码" required>
</div>
<button type="submit" class="btn">登 录</button>
<div class="error-msg" id="errorMsg"></div>
</form>
</div>
<script>
document.getElementById('loginForm').addEventListener('submit',async function(e){
e.preventDefault();
const errorEl=document.getElementById('errorMsg');
errorEl.style.display='none';
const username=document.getElementById('username').value.trim();
const password=document.getElementById('password').value;
try{
const r=await fetch('/api/login',{
method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify({username,password})
});
const d=await r.json();
if(r.ok){
window.location.href='/';
}else{
errorEl.textContent=d.error||'登录失败';
errorEl.style.display='block';
}
}catch(err){
errorEl.textContent='网络错误，请重试';
errorEl.style.display='block';
}
});
</script>
</body>
</html>"""


# ========== 巡检工单 API ==========

@app.route('/api/workorders', methods=['GET'])
@login_required
def list_workorders():
    """获取工单列表"""
    workorders = load_workorders()
    for wo in workorders:
        wo['_summary'] = get_workorder_sessions_summary(wo)
    workorders.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return jsonify({"workorders": workorders})


@app.route('/api/workorders', methods=['POST'])
@login_required
def create_workorder():
    """创建新工单"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供工单信息"}), 400

    title = data.get('title', '').strip()
    if not title:
        return jsonify({"error": "工单标题不能为空"}), 400

    workorder = {
        "id": generate_workorder_id(),
        "title": title,
        "location": data.get('location', '').strip(),
        "description": data.get('description', '').strip(),
        "status": "待巡检",
        "inspector": data.get('inspector', '').strip(),
        "sessions": [],
        "created_by": session.get('username', 'unknown'),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "notes": data.get('notes', '').strip()
    }
    workorders = load_workorders()
    workorders.append(workorder)
    save_workorders(workorders)
    return jsonify({"status": "success", "workorder": workorder}), 201


@app.route('/api/workorders/<workorder_id>', methods=['GET'])
@login_required
def get_workorder(workorder_id):
    """获取工单详情"""
    workorders = load_workorders()
    for wo in workorders:
        if wo['id'] == workorder_id:
            wo['_summary'] = get_workorder_sessions_summary(wo)
            return jsonify({"workorder": wo})
    return jsonify({"error": "工单不存在"}), 404


@app.route('/api/workorders/<workorder_id>', methods=['PUT'])
@login_required
def update_workorder(workorder_id):
    """更新工单"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供更新信息"}), 400

    workorders = load_workorders()
    for i, wo in enumerate(workorders):
        if wo['id'] == workorder_id:
            updatable_fields = ['title', 'location', 'description', 'status', 'inspector', 'notes']
            for field in updatable_fields:
                if field in data:
                    workorders[i][field] = data[field].strip() if isinstance(data[field], str) else data[field]
            workorders[i]['updated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_workorders(workorders)
            return jsonify({"status": "success", "workorder": workorders[i]})
    return jsonify({"error": "工单不存在"}), 404


@app.route('/api/workorders/<workorder_id>', methods=['DELETE'])
@login_required
def delete_workorder(workorder_id):
    """删除工单（仅管理员）"""
    if session.get('role') != 'admin':
        return jsonify({"error": "只有管理员才能删除工单"}), 403

    workorders = load_workorders()
    for i, wo in enumerate(workorders):
        if wo['id'] == workorder_id:
            deleted = workorders.pop(i)
            save_workorders(workorders)
            return jsonify({"status": "success", "message": f"工单 {deleted['title']} 已删除"})
    return jsonify({"error": "工单不存在"}), 404


@app.route('/api/workorders/<workorder_id>/sessions', methods=['POST'])
@login_required
def add_session_to_workorder(workorder_id):
    """将巡检会话关联到工单"""
    data = request.get_json()
    if not data or not data.get('session_id'):
        return jsonify({"error": "请提供会话 ID"}), 400

    session_id = data['session_id'].strip()
    workorders = load_workorders()
    for i, wo in enumerate(workorders):
        if wo['id'] == workorder_id:
            if 'sessions' not in workorders[i]:
                workorders[i]['sessions'] = []
            if session_id not in workorders[i]['sessions']:
                workorders[i]['sessions'].append(session_id)
                workorders[i]['updated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_workorders(workorders)
            return jsonify({"status": "success", "workorder": workorders[i]})
    return jsonify({"error": "工单不存在"}), 404


@app.route('/api/workorders/<workorder_id>/sessions/<session_id>', methods=['DELETE'])
@login_required
def remove_session_from_workorder(workorder_id, session_id):
    """从工单中移除关联的巡检会话"""
    workorders = load_workorders()
    for i, wo in enumerate(workorders):
        if wo['id'] == workorder_id:
            if session_id in wo.get('sessions', []):
                workorders[i]['sessions'].remove(session_id)
                workorders[i]['updated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_workorders(workorders)
            return jsonify({"status": "success", "workorder": workorders[i]})
    return jsonify({"error": "工单不存在"}), 404


# ========== 巡检历史数据查询 ==========

def get_all_inspection_records():
    """从所有日志文件中提取巡检记录，并关联工单信息"""
    logs_dir = os.path.join(UPLOAD_FOLDER, "logs")
    records = []
    if not os.path.exists(logs_dir):
        return records

    workorders = load_workorders()
    session_to_workorder = {}
    for wo in workorders:
        for sid in wo.get('sessions', []):
            if sid not in session_to_workorder:
                session_to_workorder[sid] = []
            session_to_workorder[sid].append({
                'workorder_id': wo['id'],
                'workorder_title': wo['title'],
                'workorder_location': wo.get('location', ''),
                'workorder_status': wo['status']
            })

    for log_file in os.listdir(logs_dir):
        if not log_file.endswith('.json'):
            continue
        session_id = log_file.replace('.json', '')
        try:
            with open(os.path.join(logs_dir, log_file), 'r', encoding='utf-8') as f:
                entries = json.load(f)
            for entry in entries:
                detection = entry.get('detection') or {}
                records.append({
                    'session_id': session_id,
                    'filename': entry.get('filename', ''),
                    'filepath': entry.get('filepath', ''),
                    'result_path': entry.get('result_path', ''),
                    'upload_time': entry.get('upload_time', ''),
                    'segment': entry.get('segment', 0),
                    'blur_score': entry.get('blur_score', 0.0),
                    'quality_ok': entry.get('quality_ok', False),
                    'num_cracks': detection.get('num_cracks', 0),
                    'avg_confidence': detection.get('avg_confidence', 0.0),
                    'crack_area_ratio': detection.get('crack_area_ratio', 0.0),
                    'severity': detection.get('severity', '无裂缝'),
                    'workorders': session_to_workorder.get(session_id, [])
                })
        except Exception:
            pass
    records.sort(key=lambda x: x.get('upload_time', ''), reverse=True)
    return records


@app.route('/api/history/records', methods=['GET'])
@login_required
def query_history_records():
    """查询巡检历史记录（支持多条件筛选和分页）"""
    records = get_all_inspection_records()

    session_filter = request.args.get('session', '').strip()
    severity_filter = request.args.get('severity', '').strip()
    workorder_filter = request.args.get('workorder_id', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    min_cracks = request.args.get('min_cracks', type=int)
    search = request.args.get('search', '').strip()
    quality = request.args.get('quality', '').strip()
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 50, type=int)
    sort_by = request.args.get('sort_by', 'upload_time')
    sort_order = request.args.get('sort_order', 'desc')

    if session_filter:
        records = [r for r in records if r['session_id'] == session_filter]
    if severity_filter:
        records = [r for r in records if r['severity'] == severity_filter]
    if workorder_filter:
        records = [r for r in records if any(wo['workorder_id'] == workorder_filter for wo in r['workorders'])]
    if date_from:
        records = [r for r in records if r['upload_time'] >= date_from]
    if date_to:
        records = [r for r in records if r['upload_time'] <= date_to + ' 23:59:59']
    if min_cracks is not None:
        records = [r for r in records if r['num_cracks'] >= min_cracks]
    if quality == 'ok':
        records = [r for r in records if r['quality_ok']]
    elif quality == 'bad':
        records = [r for r in records if not r['quality_ok']]
    if search:
        s = search.lower()
        records = [r for r in records if s in r['filename'].lower() or s in r['session_id'].lower() or any(s in wo.get('workorder_title', '').lower() or s in wo.get('workorder_location', '').lower() for wo in r['workorders'])]

    reverse = sort_order == 'desc'
    if sort_by == 'num_cracks':
        records.sort(key=lambda x: x['num_cracks'], reverse=reverse)
    elif sort_by == 'avg_confidence':
        records.sort(key=lambda x: x['avg_confidence'], reverse=reverse)
    elif sort_by == 'severity':
        sev_order = {'严重': 3, '中等': 2, '轻微': 1, '无裂缝': 0}
        records.sort(key=lambda x: sev_order.get(x['severity'], 0), reverse=reverse)
    elif sort_by == 'filename':
        records.sort(key=lambda x: x['filename'], reverse=reverse)
    else:
        records.sort(key=lambda x: x.get('upload_time', ''), reverse=reverse)

    total = len(records)
    total_pages = max(1, (total + limit - 1) // limit)
    start = (page - 1) * limit
    paged = records[start:start + limit]

    return jsonify({'records': paged, 'total': total, 'page': page, 'total_pages': total_pages, 'limit': limit})


@app.route('/api/history/stats', methods=['GET'])
@login_required
def get_history_stats():
    """获取巡检历史统计信息"""
    records = get_all_inspection_records()
    total = len(records)
    with_cracks = sum(1 for r in records if r['num_cracks'] > 0)
    severity_dist = {'严重': 0, '中等': 0, '轻微': 0, '无裂缝': 0}
    for r in records:
        sev = r.get('severity', '无裂缝')
        if sev in severity_dist:
            severity_dist[sev] += 1
    sessions = list(set(r['session_id'] for r in records))
    total_cracks = sum(r['num_cracks'] for r in records)
    avg_cracks_per_image = round(total_cracks / total, 2) if total > 0 else 0
    with_cracks_conf = [r for r in records if r['num_cracks'] > 0]
    avg_confidence = round(sum(r['avg_confidence'] for r in with_cracks_conf) / max(len(with_cracks_conf), 1) * 100, 1)
    quality_ok = sum(1 for r in records if r['quality_ok'])
    quality_bad = total - quality_ok
    date_groups = {}
    for r in records:
        if r['upload_time']:
            date_key = r['upload_time'][:10]
            if date_key not in date_groups:
                date_groups[date_key] = {'total': 0, 'cracks': 0}
            date_groups[date_key]['total'] += 1
            date_groups[date_key]['cracks'] += r['num_cracks']
    timeline = [{'date': k, 'total': v['total'], 'cracks': v['cracks']} for k, v in sorted(date_groups.items())]
    return jsonify({
        'total_records': total, 'total_sessions': len(sessions), 'total_workorders': len(load_workorders()),
        'with_cracks': with_cracks, 'total_cracks': total_cracks,
        'avg_cracks_per_image': avg_cracks_per_image, 'avg_confidence': avg_confidence,
        'quality_ok': quality_ok, 'quality_bad': quality_bad,
        'severity_distribution': severity_dist, 'timeline': timeline
    })


@app.route('/api/history/record/<session_id>/<path:filename>', methods=['GET'])
@login_required
def get_history_record_detail(session_id, filename):
    """获取单条巡检记录的详细信息"""
    logs_dir = os.path.join(UPLOAD_FOLDER, "logs")
    log_path = os.path.join(logs_dir, f"{session_id}.json")
    if not os.path.exists(log_path):
        return jsonify({"error": "记录不存在"}), 404
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            entries = json.load(f)
        for entry in entries:
            if entry.get('filename') == filename:
                detection = entry.get('detection') or {}
                workorders = load_workorders()
                related_wos = []
                for wo in workorders:
                    if session_id in wo.get('sessions', []):
                        related_wos.append({'workorder_id': wo['id'], 'workorder_title': wo['title'], 'workorder_location': wo.get('location', ''), 'workorder_status': wo['status']})
                return jsonify({
                    'session_id': session_id, 'filename': entry.get('filename', ''),
                    'filepath': entry.get('filepath', ''), 'result_path': entry.get('result_path', ''),
                    'upload_time': entry.get('upload_time', ''), 'segment': entry.get('segment', 0),
                    'blur_score': entry.get('blur_score', 0.0), 'quality_ok': entry.get('quality_ok', False),
                    'num_cracks': detection.get('num_cracks', 0), 'avg_confidence': detection.get('avg_confidence', 0.0),
                    'crack_area_ratio': detection.get('crack_area_ratio', 0.0), 'severity': detection.get('severity', '无裂缝'),
                    'crack_details': detection.get('crack_details', []), 'workorders': related_wos
                })
        return jsonify({"error": "记录不存在"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/history/export', methods=['GET'])
@login_required
def export_history_csv():
    """导出巡检历史数据为CSV"""
    records = get_all_inspection_records()
    session_filter = request.args.get('session', '').strip()
    severity_filter = request.args.get('severity', '').strip()
    workorder_filter = request.args.get('workorder_id', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    search = request.args.get('search', '').strip()
    if session_filter: records = [r for r in records if r['session_id'] == session_filter]
    if severity_filter: records = [r for r in records if r['severity'] == severity_filter]
    if workorder_filter: records = [r for r in records if any(wo['workorder_id'] == workorder_filter for wo in r['workorders'])]
    if date_from: records = [r for r in records if r['upload_time'] >= date_from]
    if date_to: records = [r for r in records if r['upload_time'] <= date_to + ' 23:59:59']
    if search:
        s = search.lower()
        records = [r for r in records if s in r['filename'].lower() or s in r['session_id'].lower()]
    import csv, io
    output = io.StringIO()
    output.write('﻿')
    writer = csv.writer(output)
    writer.writerow(['文件名', '会话ID', '上传时间', '严重程度', '裂缝数', '置信度(%)', '面积占比(%)', '模糊度', '质量合格', '关联工单'])
    for r in records:
        wos = ', '.join(wo['workorder_id'] for wo in r['workorders']) if r['workorders'] else ''
        writer.writerow([r['filename'], r['session_id'], r['upload_time'], r['severity'], r['num_cracks'], round(r['avg_confidence'] * 100, 1), round(r['crack_area_ratio'], 2), round(r['blur_score'], 2), '是' if r['quality_ok'] else '否', wos])
    output.seek(0)
    return Response(output.getvalue().encode('utf-8-sig'), mimetype='text/csv', headers={'Content-Disposition': 'attachment;filename=inspection_history.csv'})


# ========== 巡检报告生成 ==========

def build_report_data(records, title, subtitle=''):
    """构建报告数据结构"""
    total = len(records)
    with_cracks = sum(1 for r in records if r['num_cracks'] > 0)
    severity_dist = {'严重': 0, '中等': 0, '轻微': 0, '无裂缝': 0}
    for r in records:
        sev = r.get('severity', '无裂缝')
        if sev in severity_dist: severity_dist[sev] += 1
    total_cracks = sum(r['num_cracks'] for r in records)
    avg_cracks = round(total_cracks / total, 2) if total > 0 else 0
    with_cracks_conf = [r for r in records if r['num_cracks'] > 0]
    avg_confidence = round(sum(r['avg_confidence'] for r in with_cracks_conf) / max(len(with_cracks_conf), 1) * 100, 1)
    quality_ok = sum(1 for r in records if r['quality_ok'])
    quality_rate = round(quality_ok / total * 100, 1) if total > 0 else 0
    max_severity = '无裂缝'
    for sev in ['严重', '中等', '轻微']:
        if severity_dist[sev] > 0: max_severity = sev; break
    sessions = list(set(r['session_id'] for r in records))
    date_range = ''
    if records:
        dates = sorted(set(r['upload_time'][:10] for r in records if r['upload_time']))
        if dates: date_range = f"{dates[0]} ~ {dates[-1]}"
    severity_percent = {}
    for k, v in severity_dist.items():
        severity_percent[k] = round(v / total * 100, 1) if total > 0 else 0
    return {
        'title': title, 'subtitle': subtitle,
        'generated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'generated_by': session.get('username', 'unknown'),
        'total_records': total, 'total_sessions': len(sessions), 'date_range': date_range,
        'with_cracks': with_cracks, 'without_cracks': total - with_cracks,
        'total_cracks': total_cracks, 'avg_cracks_per_image': avg_cracks,
        'avg_confidence': avg_confidence, 'quality_ok': quality_ok,
        'quality_bad': total - quality_ok, 'quality_rate': quality_rate,
        'max_severity': max_severity, 'severity_distribution': severity_dist,
        'severity_percent': severity_percent, 'records': records[:200],
        'sample_images': [r for r in records[:8] if r['filepath']]
    }


@app.route('/api/report/workorder/<workorder_id>', methods=['GET'])
@login_required
def report_workorder(workorder_id):
    workorders = load_workorders()
    wo = next((w for w in workorders if w['id'] == workorder_id), None)
    if not wo: return jsonify({"error": "工单不存在"}), 404
    logs_dir = os.path.join(UPLOAD_FOLDER, "logs")
    records = []
    for session_id in wo.get('sessions', []):
        log_path = os.path.join(logs_dir, f"{session_id}.json")
        if not os.path.exists(log_path): continue
        try:
            with open(log_path, 'r', encoding='utf-8') as f: entries = json.load(f)
            for entry in entries:
                detection = entry.get('detection') or {}
                records.append({'session_id': session_id, 'filename': entry.get('filename', ''), 'filepath': entry.get('filepath', ''), 'result_path': entry.get('result_path', ''), 'upload_time': entry.get('upload_time', ''), 'segment': entry.get('segment', 0), 'blur_score': entry.get('blur_score', 0.0), 'quality_ok': entry.get('quality_ok', False), 'num_cracks': detection.get('num_cracks', 0), 'avg_confidence': detection.get('avg_confidence', 0.0), 'crack_area_ratio': detection.get('crack_area_ratio', 0.0), 'severity': detection.get('severity', '无裂缝')})
        except Exception: pass
    records.sort(key=lambda x: x.get('upload_time', ''), reverse=True)
    report = build_report_data(records, title="工单巡检报告", subtitle=f"工单编号: {wo['id']} | 标题: {wo['title']} | 地点: {wo.get('location', '未指定')} | 状态: {wo['status']}")
    report['workorder'] = wo
    return jsonify({"report": report})


@app.route('/api/report/session/<session_id>', methods=['GET'])
@login_required
def report_session(session_id):
    logs_dir = os.path.join(UPLOAD_FOLDER, "logs")
    log_path = os.path.join(logs_dir, f"{session_id}.json")
    if not os.path.exists(log_path): return jsonify({"error": "会话不存在"}), 404
    try:
        with open(log_path, 'r', encoding='utf-8') as f: entries = json.load(f)
    except Exception: return jsonify({"error": "读取日志失败"}), 500
    workorders = load_workorders()
    related_wos = [wo for wo in workorders if session_id in wo.get('sessions', [])]
    records = []
    for entry in entries:
        detection = entry.get('detection') or {}
        records.append({'session_id': session_id, 'filename': entry.get('filename', ''), 'filepath': entry.get('filepath', ''), 'result_path': entry.get('result_path', ''), 'upload_time': entry.get('upload_time', ''), 'segment': entry.get('segment', 0), 'blur_score': entry.get('blur_score', 0.0), 'quality_ok': entry.get('quality_ok', False), 'num_cracks': detection.get('num_cracks', 0), 'avg_confidence': detection.get('avg_confidence', 0.0), 'crack_area_ratio': detection.get('crack_area_ratio', 0.0), 'severity': detection.get('severity', '无裂缝')})
    records.sort(key=lambda x: x.get('upload_time', ''), reverse=True)
    wo_info = ''
    if related_wos: wo_info = ' | 关联工单: ' + ', '.join(f"{wo['id']} {wo['title']}" for wo in related_wos)
    report = build_report_data(records, title="会话巡检报告", subtitle=f"会话ID: {session_id}{wo_info}")
    report['session_id'] = session_id
    report['related_workorders'] = [{'id': wo['id'], 'title': wo['title']} for wo in related_wos]
    return jsonify({"report": report})


@app.route('/api/report/custom', methods=['GET'])
@login_required
def report_custom():
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    logs_dir = os.path.join(UPLOAD_FOLDER, "logs")
    records = []
    if os.path.exists(logs_dir):
        for log_file in os.listdir(logs_dir):
            if not log_file.endswith('.json'): continue
            session_id = log_file.replace('.json', '')
            try:
                with open(os.path.join(logs_dir, log_file), 'r', encoding='utf-8') as f: entries = json.load(f)
                for entry in entries:
                    upload_time = entry.get('upload_time', '')
                    if date_from and upload_time < date_from: continue
                    if date_to and upload_time > date_to + ' 23:59:59': continue
                    detection = entry.get('detection') or {}
                    records.append({'session_id': session_id, 'filename': entry.get('filename', ''), 'filepath': entry.get('filepath', ''), 'result_path': entry.get('result_path', ''), 'upload_time': upload_time, 'segment': entry.get('segment', 0), 'blur_score': entry.get('blur_score', 0.0), 'quality_ok': entry.get('quality_ok', False), 'num_cracks': detection.get('num_cracks', 0), 'avg_confidence': detection.get('avg_confidence', 0.0), 'crack_area_ratio': detection.get('crack_area_ratio', 0.0), 'severity': detection.get('severity', '无裂缝')})
            except Exception: pass
    records.sort(key=lambda x: x.get('upload_time', ''), reverse=True)
    subtitle = '自定义时间范围'
    if date_from and date_to: subtitle = f'时间范围: {date_from} ~ {date_to}'
    elif date_from: subtitle = f'起始日期: {date_from}'
    elif date_to: subtitle = f'截止日期: {date_to}'
    report = build_report_data(records, title="巡检报告", subtitle=subtitle)
    return jsonify({"report": report})


@app.route('/api/report/summary', methods=['GET'])
@login_required
def report_summary():
    logs_dir = os.path.join(UPLOAD_FOLDER, "logs")
    records = []
    if os.path.exists(logs_dir):
        for log_file in os.listdir(logs_dir):
            if not log_file.endswith('.json'): continue
            session_id = log_file.replace('.json', '')
            try:
                with open(os.path.join(logs_dir, log_file), 'r', encoding='utf-8') as f: entries = json.load(f)
                for entry in entries:
                    detection = entry.get('detection') or {}
                    records.append({'session_id': session_id, 'filename': entry.get('filename', ''), 'filepath': entry.get('filepath', ''), 'result_path': entry.get('result_path', ''), 'upload_time': entry.get('upload_time', ''), 'segment': entry.get('segment', 0), 'blur_score': entry.get('blur_score', 0.0), 'quality_ok': entry.get('quality_ok', False), 'num_cracks': detection.get('num_cracks', 0), 'avg_confidence': detection.get('avg_confidence', 0.0), 'crack_area_ratio': detection.get('crack_area_ratio', 0.0), 'severity': detection.get('severity', '无裂缝')})
            except Exception: pass
        records.sort(key=lambda x: x.get('upload_time', ''), reverse=True)
    workorders = load_workorders()
    report = build_report_data(records, title="全局巡检汇总报告", subtitle=f"工单总数: {len(workorders)} | 会话总数: {len(set(r['session_id'] for r in records))}")
    wo_summaries = []
    for wo in workorders:
        wo_records = []
        for sid in wo.get('sessions', []):
            wo_records.extend([r for r in records if r['session_id'] == sid])
        total_imgs = len(wo_records)
        total_cr = sum(r['num_cracks'] for r in wo_records)
        wo_summaries.append({'id': wo['id'], 'title': wo['title'], 'location': wo.get('location', ''), 'status': wo['status'], 'sessions': len(wo.get('sessions', [])), 'total_images': total_imgs, 'total_cracks': total_cr})
    report['workorder_summaries'] = wo_summaries
    return jsonify({"report": report})


@app.route('/api/upload', methods=['POST'])
@login_required
def upload_image():
    """接收树莓派上传的图片"""
    # 检查是否有文件部分
    if 'image' not in request.files:
        return jsonify({"error": "没有文件部分"}), 400

    file = request.files['image']

    # 检查文件名
    if file.filename == '':
        return jsonify({"error": "没有选择文件"}), 400

    # 检查文件类型
    if file and allowed_file(file.filename):
        # 获取元数据
        metadata = {
            "session": request.form.get('session', 'unknown'),
            "segment": int(request.form.get('segment', 0)),
            "blur_score": float(request.form.get('blur_score', 0.0)),
            "quality_ok": request.form.get('quality_ok', 'false').lower() == 'true',
            "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "client_ip": request.remote_addr,
        }

        # 生成保存路径
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        session_dir = os.path.join(UPLOAD_FOLDER, "images", metadata["session"])
        os.makedirs(session_dir, exist_ok=True)

        # 保存图片
        filename = f"{ts}_{metadata['segment']:03d}.jpg"
        filepath = os.path.join(session_dir, filename)
        file.save(filepath)

        # 自动裂缝检测
        annotated_img, result_info = detect_cracks(filepath)
        result_path = None
        if annotated_img is not None and result_info is not None:
            import cv2
            result_filename = f"{ts}_{metadata['segment']:03d}_result.jpg"
            session_result_dir = os.path.join(RESULT_FOLDER, metadata["session"])
            os.makedirs(session_result_dir, exist_ok=True)
            result_path = os.path.join(session_result_dir, result_filename)
            cv2.imwrite(result_path, annotated_img)
            app.logger.info(
                f"检测完成: {filename} -> 裂缝数={result_info['num_cracks']}, "
                f"严重程度={result_info['severity']}"
            )

        # 记录日志
        log_entry = {
            "filename": filename,
            "filepath": filepath,
            "result_path": result_path,
            "detection": result_info,
            **metadata
        }
        log_path = os.path.join(UPLOAD_FOLDER, "logs", f"{metadata['session']}.json")
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        else:
            logs = []
        logs.append(log_entry)
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)

        app.logger.info(f"图片上传成功: {filename} (session={metadata['session']}, segment={metadata['segment']})")

        response = {
            "status": "success",
            "message": "图片上传并检测完成",
            "filename": filename,
            "metadata": metadata
        }
        if result_path:
            response["result_path"] = result_path
        if result_info:
            response["detection"] = result_info

        return jsonify(response), 200

    return jsonify({"error": "不允许的文件类型"}), 400


@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    return jsonify({
        "status": "ok",
        "service": "crackbot-backend",
        "upload_count": len(os.listdir(os.path.join(UPLOAD_FOLDER, "images"))),
        "timestamp": datetime.now().isoformat()
    })


@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    """获取所有扫描会话列表"""
    sessions = []
    images_dir = os.path.join(UPLOAD_FOLDER, "images")
    if os.path.exists(images_dir):
        for session in os.listdir(images_dir):
            session_path = os.path.join(images_dir, session)
            if os.path.isdir(session_path):
                count = len([f for f in os.listdir(session_path) if f.endswith('.jpg')])
                sessions.append({
                    "session_id": session,
                    "image_count": count
                })
    return jsonify({"sessions": sessions})


def get_recent_images_from_logs(limit=100):
    """从日志文件中读取最近的图片记录（仅返回文件存在的）"""
    logs_dir = os.path.join(UPLOAD_FOLDER, "logs")
    all_images = []
    if os.path.exists(logs_dir):
        for log_file in os.listdir(logs_dir):
            if log_file.endswith('.json'):
                try:
                    with open(os.path.join(logs_dir, log_file), 'r', encoding='utf-8') as f:
                        entries = json.load(f)
                    for entry in entries:
                        filepath = entry.get('filepath', '')
                        if filepath and os.path.exists(filepath):
                            all_images.append(entry)
                except Exception:
                    pass
    all_images.sort(key=lambda x: x.get('upload_time', ''), reverse=True)
    return all_images[:limit]


@app.route('/api/images/recent', methods=['GET'])
def get_recent_images():
    """获取最近上传的图片及其检测结果"""
    limit = request.args.get('limit', 60, type=int)
    images = get_recent_images_from_logs(limit)
    return jsonify({"images": images})


@app.route('/uploads/images/<session>/<filename>')
def serve_image(session, filename):
    """提供原始图片访问"""
    return send_from_directory(os.path.join(UPLOAD_FOLDER, "images", session), filename)


@app.route('/uploads/results/<session>/<filename>')
def serve_result(session, filename):
    """提供检测结果图片访问"""
    return send_from_directory(os.path.join(RESULT_FOLDER, session), filename)


@app.route('/api/session/<session_id>', methods=['GET'])
def get_session_details(session_id):
    """获取特定会话的详细信息"""
    log_path = os.path.join(UPLOAD_FOLDER, "logs", f"{session_id}.json")
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            logs = json.load(f)
        return jsonify({
            "session_id": session_id,
            "total_images": len(logs),
            "images": logs
        })
    else:
        return jsonify({"error": "会话不存在"}), 404


@app.route('/api/predict', methods=['POST'])
@login_required
def predict_image():
    """接收图片并调用YOLO模型进行裂缝检测"""
    if 'image' not in request.files:
        return jsonify({"error": "没有文件部分"}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "没有选择文件"}), 400

    if file and allowed_file(file.filename):
        import cv2
        import base64

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        temp_path = os.path.join(UPLOAD_FOLDER, f"tmp_{ts}.jpg")
        file.save(temp_path)

        annotated_img, result_info = detect_cracks(temp_path)
        if annotated_img is None:
            try:
                os.remove(temp_path)
            except Exception:
                pass
            return jsonify({"error": "模型未加载"}), 500

        _, buffer = cv2.imencode('.jpg', annotated_img)
        img_base64 = base64.b64encode(buffer).decode('utf-8')

        result_filename = f"result_{ts}.jpg"
        result_path = os.path.join(RESULT_FOLDER, result_filename)
        cv2.imwrite(result_path, annotated_img)

        app.logger.info(f"检测完成: 裂缝数={result_info['num_cracks']}, 严重程度={result_info['severity']}")

        try:
            os.remove(temp_path)
        except Exception:
            pass

        return jsonify({
            "status": "success",
            "result_image": img_base64,
            "result_path": result_path,
            "detection": result_info
        }), 200

    return jsonify({"error": "不允许的文件类型"}), 400


@app.route('/workorders')
def workorders_page():
    """工单管理页面"""
    if 'username' not in session:
        return redirect(url_for('login_page'))
    current_username = session.get('username', 'unknown')
    current_role = session.get('role', 'user')

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>工单管理 - 墙面裂缝检测系统</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
.header{background:rgba(30,41,59,0.8);padding:16px 24px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid rgba(148,163,184,0.1);position:sticky;top:0;z-index:100;backdrop-filter:blur(10px);flex-wrap:wrap;gap:8px}
.header h1{font-size:20px;display:flex;align-items:center;gap:8px}
.nav-tabs{display:flex;gap:4px}
.nav-tab{padding:6px 16px;border-radius:8px;font-size:13px;cursor:pointer;text-decoration:none;color:#94a3b8;background:rgba(148,163,184,0.06);border:1px solid transparent;transition:all 0.2s}
.nav-tab:hover{color:#e2e8f0;background:rgba(148,163,184,0.12)}
.nav-tab.active{color:#38bdf8;background:rgba(56,189,248,0.1);border-color:rgba(56,189,248,0.25)}
.container{max-width:1200px;margin:0 auto;padding:20px 24px}
.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:12px}
.btn{padding:9px 20px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:none;transition:all 0.2s}
.btn-primary{background:#38bdf8;color:#0f172a}
.btn-primary:hover{background:#7dd3fc}
.btn-danger{background:rgba(239,68,68,0.2);color:#fca5a5;border:1px solid rgba(239,68,68,0.3)}
.btn-danger:hover{background:rgba(239,68,68,0.4)}
.btn-sm{padding:4px 10px;font-size:11px;border-radius:6px}
.btn-outline{background:transparent;color:#94a3b8;border:1px solid rgba(148,163,184,0.2)}
.btn-outline:hover{color:#e2e8f0;border-color:rgba(148,163,184,0.4)}
.wo-table{width:100%;border-collapse:collapse}
.wo-table th{text-align:left;padding:10px 14px;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid rgba(148,163,184,0.08)}
.wo-table td{padding:12px 14px;font-size:13px;border-bottom:1px solid rgba(148,163,184,0.05);vertical-align:middle}
.wo-table tr:hover td{background:rgba(148,163,184,0.03)}
.wo-table tr{cursor:pointer;transition:background 0.15s}
.wo-title{color:#e2e8f0;font-weight:600}
.wo-location{color:#94a3b8;font-size:12px}
.wo-id{font-family:monospace;font-size:11px;color:#64748b}
.status-badge{padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;display:inline-block}
.status-pending{background:rgba(245,158,11,0.15);color:#fcd34d;border:1px solid rgba(245,158,11,0.25)}
.status-running{background:rgba(56,189,248,0.15);color:#7dd3fc;border:1px solid rgba(56,189,248,0.25)}
.status-done{background:rgba(34,197,94,0.15);color:#86efac;border:1px solid rgba(34,197,94,0.25)}
.status-closed{background:rgba(100,116,139,0.15);color:#94a3b8;border:1px solid rgba(100,116,139,0.25)}
.modal-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);z-index:9999;display:flex;justify-content:center;align-items:center;opacity:0;visibility:hidden;transition:opacity 0.3s,visibility 0.3s}
.modal-overlay.active{opacity:1;visibility:visible}
.modal-content{background:rgba(30,41,59,0.95);border:1px solid rgba(148,163,184,0.15);border-radius:16px;width:90vw;max-width:640px;max-height:85vh;overflow-y:auto;position:relative;backdrop-filter:blur(10px);padding:28px}
.modal-close{position:absolute;top:12px;right:16px;background:rgba(239,68,68,0.2);color:#fca5a5;border:1px solid rgba(239,68,68,0.3);border-radius:50%;width:36px;height:36px;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all 0.2s;line-height:1}
.modal-close:hover{background:rgba(239,68,68,0.4);color:#fecaca}
.form-group{margin-bottom:16px}
.form-group label{display:block;font-size:12px;color:#94a3b8;margin-bottom:5px}
.form-group input,.form-group textarea,.form-group select{width:100%;padding:9px 12px;background:rgba(15,23,42,0.6);border:1px solid rgba(148,163,184,0.15);border-radius:8px;color:#e2e8f0;font-size:13px;outline:none;transition:border-color 0.2s;resize:vertical;font-family:inherit}
.form-group input:focus,.form-group textarea:focus,.form-group select:focus{border-color:#38bdf8}
.form-group textarea{min-height:80px}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.form-actions{display:flex;gap:10px;justify-content:flex-end;margin-top:20px}
.empty-state{text-align:center;padding:60px 20px;color:#475569}
.empty-state span{font-size:48px;display:block;margin-bottom:12px}
.detail-section{margin-bottom:20px}
.detail-label{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px}
.detail-value{font-size:14px;color:#e2e8f0}
.session-list{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.session-tag{background:rgba(56,189,248,0.1);color:#7dd3fc;padding:3px 10px;border-radius:6px;font-size:12px;font-family:monospace;display:flex;align-items:center;gap:6px}
.session-tag .remove-tag{cursor:pointer;color:#fca5a5;font-weight:700;font-size:14px;line-height:1}
.session-tag .remove-tag:hover{color:#f87171}
.summary-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:12px}
.summary-item{background:rgba(15,23,42,0.5);border-radius:8px;padding:12px;text-align:center}
.summary-num{font-size:20px;font-weight:700;color:#38bdf8}
.summary-label{font-size:10px;color:#64748b;margin-top:2px}
@media(max-width:600px){.form-row{grid-template-columns:1fr}.summary-grid{grid-template-columns:1fr}.wo-table{font-size:11px}}
</style>
</head>
<body>
<div class="header">
<h1>&#128196; 墙面裂缝检测系统</h1>
<div style="display:flex;align-items:center;gap:12px">
<div class="nav-tabs">
<a href="/" class="nav-tab">&#128247; 图片监控</a>
<a href="/workorders" class="nav-tab active">&#128196; 工单管理</a>
<a href="/history" class="nav-tab">&#128269; 历史查询</a>
<a href="/report" class="nav-tab">&#128202; 报告生成</a>
</div>
<span style="font-size:13px;color:#94a3b8">&#128100; __USERNAME__</span>
<button onclick="logout()" style="padding:5px 14px;background:rgba(239,68,68,0.15);color:#fca5a5;border:1px solid rgba(239,68,68,0.3);border-radius:6px;cursor:pointer;font-size:12px;transition:all 0.2s" onmouseover="this.style.background='rgba(239,68,68,0.3)'" onmouseout="this.style.background='rgba(239,68,68,0.15)'">退出登录</button>
</div>
</div>
<div class="container">
<div class="toolbar">
<h2 style="font-size:18px">&#128196; 巡检工单</h2>
<button class="btn btn-primary" onclick="openCreateModal()">+ 新建工单</button>
</div>
<div id="workorderList"></div>
<div class="empty-state" id="emptyState"><span>&#128203;</span>暂无工单，点击上方按钮创建</div>
</div>

<div class="modal-overlay" id="formModal" onclick="if(event.target===this)closeFormModal()">
<div class="modal-content">
<button class="modal-close" onclick="closeFormModal()">&times;</button>
<h3 id="formModalTitle" style="margin-bottom:20px">新建工单</h3>
<form id="woForm" onsubmit="submitWorkorder(event)">
<input type="hidden" id="woEditId">
<div class="form-group"><label>工单标题 *</label><input type="text" id="woTitle" required placeholder="例如：1号楼外墙巡检"></div>
<div class="form-row">
<div class="form-group"><label>巡检地点</label><input type="text" id="woLocation" placeholder="例如：1号楼东侧外墙"></div>
<div class="form-group"><label>巡检人员</label><input type="text" id="woInspector" placeholder="例如：张三"></div>
</div>
<div class="form-group"><label>描述</label><textarea id="woDescription" placeholder="工单详细描述..."></textarea></div>
<div class="form-row">
<div class="form-group"><label>状态</label><select id="woStatus"><option value="待巡检">待巡检</option><option value="巡检中">巡检中</option><option value="已完成">已完成</option><option value="已关闭">已关闭</option></select></div>
<div class="form-group"><label>备注</label><input type="text" id="woNotes" placeholder="备注信息"></div>
</div>
<div class="form-actions">
<button type="button" class="btn btn-outline" onclick="closeFormModal()">取消</button>
<button type="submit" class="btn btn-primary">保存</button>
</div>
</form>
</div>
</div>

<div class="modal-overlay" id="detailModal" onclick="if(event.target===this)closeDetailModal()">
<div class="modal-content">
<button class="modal-close" onclick="closeDetailModal()">&times;</button>
<div id="detailContent"></div>
</div>
</div>

<script>
const STATUS_CLASS={'待巡检':'status-pending','巡检中':'status-running','已完成':'status-done','已关闭':'status-closed'};
let allWorkorders=[];
let allSessions=[];

async function loadWorkorders(){
try{
const r=await fetch('/api/workorders');
const d=await r.json();
allWorkorders=d.workorders||[];
renderWorkorderList();
}catch(e){console.error(e)}
}

async function loadSessions(){
try{
const r=await fetch('/api/sessions');
const d=await r.json();
allSessions=d.sessions||[];
}catch(e){console.error(e)}
}

function renderWorkorderList(){
const el=document.getElementById('workorderList');
const empty=document.getElementById('emptyState');
if(!allWorkorders.length){el.innerHTML='';empty.style.display='block';return}
empty.style.display='none';
el.innerHTML=`<table class="wo-table"><thead><tr><th>工单编号</th><th>标题</th><th>地点</th><th>状态</th><th>会话数</th><th>图片数</th><th>创建时间</th><th>操作</th></tr></thead><tbody>`+
allWorkorders.map(wo=>{
let s=wo._summary||{};
return `<tr onclick="openDetail('${wo.id}')">
<td class="wo-id">${wo.id}</td>
<td class="wo-title">${escHtml(wo.title)}</td>
<td class="wo-location">${escHtml(wo.location||'-')}</td>
<td><span class="status-badge ${STATUS_CLASS[wo.status]||'status-closed'}">${wo.status}</span></td>
<td>${(wo.sessions||[]).length}</td>
<td>${s.total_images||0}</td>
<td style="font-size:11px;color:#64748b">${wo.created_at||''}</td>
<td onclick="event.stopPropagation()">
<button class="btn btn-outline btn-sm" onclick="openEditModal('${wo.id}')">编辑</button>
${'__ROLE__'==='admin'?`<button class="btn btn-danger btn-sm" style="margin-left:4px" onclick="deleteWorkorder('${wo.id}')">删除</button>`:''}
</td></tr>`;
}).join('')+'</tbody></table>';
}

function escHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

function openCreateModal(){
document.getElementById('formModalTitle').textContent='新建工单';
document.getElementById('woEditId').value='';
document.getElementById('woTitle').value='';
document.getElementById('woLocation').value='';
document.getElementById('woInspector').value='';
document.getElementById('woDescription').value='';
document.getElementById('woStatus').value='待巡检';
document.getElementById('woNotes').value='';
document.getElementById('formModal').classList.add('active');
document.body.style.overflow='hidden';
}

function openEditModal(id){
let wo=allWorkorders.find(w=>w.id===id);
if(!wo)return;
document.getElementById('formModalTitle').textContent='编辑工单';
document.getElementById('woEditId').value=wo.id;
document.getElementById('woTitle').value=wo.title||'';
document.getElementById('woLocation').value=wo.location||'';
document.getElementById('woInspector').value=wo.inspector||'';
document.getElementById('woDescription').value=wo.description||'';
document.getElementById('woStatus').value=wo.status||'待巡检';
document.getElementById('woNotes').value=wo.notes||'';
document.getElementById('formModal').classList.add('active');
document.body.style.overflow='hidden';
}

function closeFormModal(){
document.getElementById('formModal').classList.remove('active');
document.body.style.overflow='';
}

async function submitWorkorder(e){
e.preventDefault();
let id=document.getElementById('woEditId').value;
let data={
title:document.getElementById('woTitle').value.trim(),
location:document.getElementById('woLocation').value.trim(),
inspector:document.getElementById('woInspector').value.trim(),
description:document.getElementById('woDescription').value.trim(),
status:document.getElementById('woStatus').value,
notes:document.getElementById('woNotes').value.trim()
};
let url=id?'/api/workorders/'+id:'/api/workorders';
let method=id?'PUT':'POST';
try{
const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
if(r.ok){closeFormModal();loadWorkorders()}else{let d=await r.json();alert(d.error||'操作失败')}
}catch(err){alert('网络错误')}
}

async function deleteWorkorder(id){
if(!confirm('确定要删除这个工单吗？'))return;
try{
const r=await fetch('/api/workorders/'+id,{method:'DELETE'});
if(r.ok){loadWorkorders()}else{let d=await r.json();alert(d.error||'删除失败')}
}catch(err){alert('网络错误')}
}

async function openDetail(id){
let wo=allWorkorders.find(w=>w.id===id);
if(!wo)return;
let s=wo._summary||{};
let sessions=wo.sessions||[];
let html=`
<div class="detail-section"><div class="detail-label">工单编号</div><div class="detail-value" style="font-family:monospace">${escHtml(wo.id)}</div></div>
<div class="detail-section"><div class="detail-label">标题</div><div class="detail-value" style="font-size:18px;font-weight:600">${escHtml(wo.title)}</div></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
<div class="detail-section"><div class="detail-label">地点</div><div class="detail-value">${escHtml(wo.location||'-')}</div></div>
<div class="detail-section"><div class="detail-label">状态</div><div class="detail-value"><span class="status-badge ${STATUS_CLASS[wo.status]||'status-closed'}">${wo.status}</span></div></div>
<div class="detail-section"><div class="detail-label">巡检人员</div><div class="detail-value">${escHtml(wo.inspector||'-')}</div></div>
<div class="detail-section"><div class="detail-label">创建人</div><div class="detail-value">${escHtml(wo.created_by||'-')}</div></div>
</div>
<div class="detail-section"><div class="detail-label">描述</div><div class="detail-value">${escHtml(wo.description||'无')}</div></div>
<div class="detail-section"><div class="detail-label">备注</div><div class="detail-value">${escHtml(wo.notes||'无')}</div></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
<div class="detail-section"><div class="detail-label">创建时间</div><div class="detail-value">${wo.created_at||''}</div></div>
<div class="detail-section"><div class="detail-label">更新时间</div><div class="detail-value">${wo.updated_at||''}</div></div>
</div>
<div class="detail-section"><div class="detail-label">关联巡检会话</div>
<div class="session-list" id="detailSessions">${sessions.map(sid=>`<span class="session-tag">${escHtml(sid)} <span class="remove-tag" onclick="removeSession('${wo.id}','${sid}')">&times;</span></span>`).join('')||'<span style="color:#64748b;font-size:12px">暂无关联会话</span>'}</div>
<div style="margin-top:10px;display:flex;gap:8px;align-items:center">
<select id="addSessionSelect" style="padding:6px 10px;background:rgba(15,23,42,0.6);border:1px solid rgba(148,163,184,0.15);border-radius:6px;color:#e2e8f0;font-size:12px;min-width:200px"><option value="">选择会话...</option>${allSessions.map(s=>`<option value="${escHtml(s.session_id)}">${escHtml(s.session_id)} (${s.image_count}张)</option>`).join('')}</select>
<button class="btn btn-outline btn-sm" onclick="addSession('${wo.id}')">关联</button>
</div>
</div>
<div class="detail-section"><div class="detail-label">检测汇总</div>
<div class="summary-grid">
<div class="summary-item"><div class="summary-num">${s.total_images||0}</div><div class="summary-label">总图片数</div></div>
<div class="summary-item"><div class="summary-num">${s.total_cracks||0}</div><div class="summary-label">裂缝总数</div></div>
<div class="summary-item"><div class="summary-num">${s.sessions_with_cracks||0}</div><div class="summary-label">含裂缝会话</div></div>
</div>
</div>`;
document.getElementById('detailContent').innerHTML=html;
document.getElementById('detailModal').classList.add('active');
document.body.style.overflow='hidden';
}

function closeDetailModal(){
document.getElementById('detailModal').classList.remove('active');
document.body.style.overflow='';
}

async function addSession(woId){
let sel=document.getElementById('addSessionSelect');
let sid=sel.value;
if(!sid)return;
try{
const r=await fetch('/api/workorders/'+woId+'/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sid})});
if(r.ok){await loadWorkorders();openDetail(woId)}else{let d=await r.json();alert(d.error||'操作失败')}
}catch(err){alert('网络错误')}
}

async function removeSession(woId,sid){
if(!confirm('确定移除会话 '+sid+' 吗？'))return;
try{
const r=await fetch('/api/workorders/'+woId+'/sessions/'+sid,{method:'DELETE'});
if(r.ok){await loadWorkorders();openDetail(woId)}else{let d=await r.json();alert(d.error||'操作失败')}
}catch(err){alert('网络错误')}
}

async function logout(){
await fetch('/api/logout',{method:'POST'});
window.location.href='/login';
}

document.addEventListener('keydown',function(e){if(e.key==='Escape'){closeFormModal();closeDetailModal()}});
loadWorkorders();
loadSessions();
</script>
</body>
</html>"""
    html = html.replace('__USERNAME__', current_username).replace('__ROLE__', current_role)
    return html


# ========== 巡检历史查询页面 ==========

@app.route('/history')
def history_page():
    """巡检历史数据查询页面"""
    if 'username' not in session:
        return redirect('/login')
    current_username = session.get('username', '')
    current_role = session.get('role', 'user')
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'history_page.html')
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
    else:
        html = '<h1>模板文件 history_page.html 未找到</h1>'
    html = html.replace('__USERNAME__', current_username).replace('__ROLE__', current_role)
    return html


# ========== 巡检报告生成页面 ==========

@app.route('/report')
def report_page():
    """巡检报告生成页面"""
    if 'username' not in session:
        return redirect('/login')
    current_username = session.get('username', '')
    current_role = session.get('role', 'user')
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'report_page.html')
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
    else:
        html = '<h1>模板文件 report_page.html 未找到</h1>'
    html = html.replace('__USERNAME__', current_username).replace('__ROLE__', current_role)
    return html


@app.route('/')
def index():
    """网页仪表盘 - 实时显示上传图片和检测结果"""
    if 'username' not in session:
        return redirect(url_for('login_page'))
    images = get_recent_images_from_logs(60)
    current_username = session.get('username', 'unknown')
    current_role = session.get('role', 'user')

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>墙面裂缝检测系统</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
.header{background:rgba(30,41,59,0.8);padding:16px 24px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid rgba(148,163,184,0.1);position:sticky;top:0;z-index:100;backdrop-filter:blur(10px);flex-wrap:wrap;gap:8px}
.header h1{font-size:20px;display:flex;align-items:center;gap:8px}
.header .status{font-size:12px;color:#94a3b8}
.nav-tabs{display:flex;gap:4px}
.nav-tab{padding:6px 16px;border-radius:8px;font-size:13px;cursor:pointer;text-decoration:none;color:#94a3b8;background:rgba(148,163,184,0.06);border:1px solid transparent;transition:all 0.2s}
.nav-tab:hover{color:#e2e8f0;background:rgba(148,163,184,0.12)}
.nav-tab.active{color:#38bdf8;background:rgba(56,189,248,0.1);border-color:rgba(56,189,248,0.25)}
.stats{display:flex;gap:12px;padding:16px 24px;flex-wrap:wrap}
.stat-card{background:rgba(30,41,59,0.6);border:1px solid rgba(148,163,184,0.08);border-radius:12px;padding:14px 20px;min-width:130px;text-align:center}
.stat-value{font-size:24px;font-weight:700;color:#38bdf8}
.stat-label{font-size:11px;color:#64748b;margin-top:4px;text-transform:uppercase;letter-spacing:0.5px}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(480px,1fr));gap:20px;padding:0 24px 24px}
.card{background:rgba(30,41,59,0.6);border:1px solid rgba(148,163,184,0.08);border-radius:14px;overflow:hidden;transition:transform 0.15s,border-color 0.15s;cursor:pointer}
.card:hover{transform:translateY(-2px);border-color:rgba(56,189,248,0.3)}
.card-header{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;background:rgba(15,23,42,0.5);border-bottom:1px solid rgba(148,163,184,0.06)}
.card-filename{font-size:12px;color:#94a3b8;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60%}
.image-pair{display:grid;grid-template-columns:1fr 1fr}
.image-box{padding:10px}
.image-box img{width:100%;border-radius:10px;aspect-ratio:4/3;object-fit:cover;background:rgba(15,23,42,0.8)}
.image-label{font-size:11px;color:#64748b;text-align:center;margin-top:6px}
.card-footer{display:flex;justify-content:space-around;padding:10px 16px;border-top:1px solid rgba(148,163,184,0.06);background:rgba(15,23,42,0.3)}
.footer-item{text-align:center}
.footer-value{font-size:15px;font-weight:700;color:#38bdf8}
.footer-label{font-size:10px;color:#64748b;margin-top:2px}
.severity{padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;letter-spacing:0.3px}
.sev-serious{background:rgba(239,68,68,0.2);color:#fca5a5;border:1px solid rgba(239,68,68,0.3)}
.sev-moderate{background:rgba(245,158,11,0.2);color:#fcd34d;border:1px solid rgba(245,158,11,0.3)}
.sev-mild{background:rgba(34,197,94,0.2);color:#86efac;border:1px solid rgba(34,197,94,0.3)}
.sev-none{background:rgba(100,116,139,0.2);color:#94a3b8;border:1px solid rgba(100,116,139,0.2)}
.empty{text-align:center;padding:80px 20px;color:#475569;font-size:15px}
.empty span{font-size:40px;display:block;margin-bottom:12px}
.auto-refresh{font-size:11px;color:#64748b;position:fixed;bottom:12px;right:16px;background:rgba(30,41,59,0.8);padding:6px 12px;border-radius:8px}
.blinking{animation:blink 1s infinite}
@keyframes blink{50%{opacity:0.4}}
.modal-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);z-index:9999;display:flex;justify-content:center;align-items:center;opacity:0;visibility:hidden;transition:opacity 0.3s,visibility 0.3s}
.modal-overlay.active{opacity:1;visibility:visible}
.modal-content{background:rgba(30,41,59,0.95);border:1px solid rgba(148,163,184,0.15);border-radius:16px;width:90vw;max-height:90vh;overflow-y:auto;position:relative;backdrop-filter:blur(10px);padding:20px}
.modal-close{position:absolute;top:12px;right:16px;background:rgba(239,68,68,0.2);color:#fca5a5;border:1px solid rgba(239,68,68,0.3);border-radius:50%;width:36px;height:36px;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all 0.2s;z-index:10;line-height:1}
.modal-close:hover{background:rgba(239,68,68,0.4);color:#fecaca}
.modal-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding-right:40px}
.modal-title{font-size:15px;color:#e2e8f0;font-family:monospace;word-break:break-all}
.modal-image-pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.modal-image-box{text-align:center}
.modal-image-box img{width:100%;max-height:70vh;object-fit:contain;border-radius:10px;background:rgba(15,23,42,0.8)}
.modal-image-label{font-size:13px;color:#94a3b8;margin-top:8px}
.modal-footer{display:flex;justify-content:space-around;margin-top:16px;padding-top:14px;border-top:1px solid rgba(148,163,184,0.1)}
.modal-footer .footer-item{text-align:center}
.modal-footer .footer-value{font-size:18px;font-weight:700;color:#38bdf8}
.modal-footer .footer-label{font-size:11px;color:#64748b;margin-top:2px}
@media(max-width:600px){.image-pair{grid-template-columns:1fr}.gallery{grid-template-columns:1fr}.modal-image-pair{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="header">
<h1>&#128269; 墙面裂缝检测系统</h1>
<div style="display:flex;align-items:center;gap:12px">
<div class="nav-tabs">
<a href="/" class="nav-tab active">&#128247; 图片监控</a>
<a href="/workorders" class="nav-tab">&#128196; 工单管理</a>
<a href="/history" class="nav-tab">&#128269; 历史查询</a>
<a href="/report" class="nav-tab">&#128202; 报告生成</a>
</div>
<span style="font-size:13px;color:#94a3b8">&#128100; __USERNAME__ <span style="font-size:10px;background:rgba(56,189,248,0.15);color:#38bdf8;padding:2px 6px;border-radius:4px;margin-left:4px">__ROLE__</span></span>
<button onclick="logout()" style="padding:5px 14px;background:rgba(239,68,68,0.15);color:#fca5a5;border:1px solid rgba(239,68,68,0.3);border-radius:6px;cursor:pointer;font-size:12px;transition:all 0.2s" onmouseover="this.style.background='rgba(239,68,68,0.3)'" onmouseout="this.style.background='rgba(239,68,68,0.15)'">退出登录</button>
</div>
<div class="status">&#128994; 实时监控中 | 自动刷新</div>
</div>
<div class="stats" id="stats">
<div class="stat-card"><div class="stat-value" id="totalCount">0</div><div class="stat-label">总图片数</div></div>
<div class="stat-card"><div class="stat-value" id="crackCount">0</div><div class="stat-label">含裂缝图片</div></div>
<div class="stat-card"><div class="stat-value" id="avgCracks">0</div><div class="stat-label">平均裂缝数</div></div>
<div class="stat-card"><div class="stat-value" id="sessionCount">0</div><div class="stat-label">活跃会话</div></div>
</div>
<div class="gallery" id="gallery"></div>
<div class="empty" id="empty"><span>&#128247;</span>等待图片上传...</div>
<div class="modal-overlay" id="modalOverlay" onclick="if(event.target===this)closeModal()">
<div class="modal-content">
<button class="modal-close" onclick="closeModal()">&times;</button>
<div class="modal-header"><div class="modal-title" id="modalTitle"></div></div>
<div class="modal-image-pair">
<div class="modal-image-box">
<img id="modalOrigImg" src="" alt="原始图片">
<div class="modal-image-label">&#128247; 原始图片</div>
</div>
<div class="modal-image-box">
<img id="modalResultImg" src="" alt="检测结果">
<div class="modal-image-label">&#128300; 检测结果</div>
</div>
</div>
<div class="modal-footer" id="modalFooter"></div>
</div>
</div>
<div class="auto-refresh"><span id="refreshDot">&#128994;</span> 每2秒自动刷新</div>
<script>
const SEV_CLASS = {'严重':'sev-serious','中等':'sev-moderate','轻微':'sev-mild','无裂缝':'sev-none'};
async function loadData(){
try{
const r=await fetch('/api/images/recent?limit=60');
const d=await r.json();
const imgs=d.images;
renderStats(imgs);
renderGallery(imgs);
}catch(e){console.error(e)}
}
function renderStats(imgs){
document.getElementById('totalCount').textContent=imgs.length;
let withCracks=imgs.filter(i=>i.detection&&i.detection.num_cracks>0).length;
document.getElementById('crackCount').textContent=withCracks;
let totalCracks=imgs.reduce((s,i)=>s+(i.detection?i.detection.num_cracks:0),0);
document.getElementById('avgCracks').textContent=imgs.length?(totalCracks/imgs.length).toFixed(1):'0';
let sessions=new Set(imgs.map(i=>i.session)).size;
document.getElementById('sessionCount').textContent=sessions;
}
function renderGallery(imgs){
const g=document.getElementById('gallery');
const empty=document.getElementById('empty');
if(!imgs.length){g.innerHTML='';empty.style.display='block';return}
empty.style.display='none';
g.innerHTML=imgs.map(img=>{
let d=img.detection||{};
let session=img.session||'unknown';
let origFile=img.filename||'';
let resultFile=img.result_path?origFile.replace('.jpg','_result.jpg'):null;
let sev=d.severity||'无裂缝';
let sevClass=SEV_CLASS[sev]||'sev-none';
return `<div class="card" data-orig="/uploads/images/${session}/${origFile}" data-result="${resultFile?'/uploads/results/'+session+'/'+resultFile:''}" data-filename="${origFile}" data-detection='${JSON.stringify(d)}' onclick="openModalFromCard(this)">
<div class="card-header">
<div class="card-filename" title="${origFile}">${origFile}</div>
<span class="severity ${sevClass}">${sev}</span>
</div>
<div class="image-pair">
<div class="image-box">
<img src="/uploads/images/${session}/${origFile}" loading="lazy" onerror="this.parentElement.innerHTML='<div style=padding:20px;text-align:center;color:#475569>加载失败</div>'">
<div class="image-label">&#128247; 原始图片</div>
</div>
<div class="image-box">
<img src="${resultFile?'/uploads/results/'+session+'/'+resultFile:'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22300%22 height=%22225%22%3E%3Crect fill=%22%231e293b%22 width=%22300%22 height=%22225%22/%3E%3Ctext fill=%22%23475569%22 font-family=%22Arial%22 font-size=%2213%22 x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22 dominant-baseline=%22middle%22%3E检测中...%3C/text%3E%3C/svg%3E'}" loading="lazy" onerror="this.parentElement.innerHTML='<div style=padding:20px;text-align:center;color:#475569>检测中...</div>'">
<div class="image-label">&#128300; 检测结果</div>
</div>
</div>
<div class="card-footer">
<div class="footer-item"><div class="footer-value">${d.num_cracks||0}</div><div class="footer-label">裂缝数</div></div>
<div class="footer-item"><div class="footer-value">${d.crack_area_ratio?d.crack_area_ratio.toFixed(2):'0.00'}%</div><div class="footer-label">面积占比</div></div>
<div class="footer-item"><div class="footer-value">${d.avg_confidence?Math.round(d.avg_confidence*100):0}%</div><div class="footer-label">置信度</div></div>
<div class="footer-item"><div class="footer-value">${img.segment||'-'}</div><div class="footer-label">分段</div></div>
</div>
</div>`;
}).join('')
}
loadData();
setInterval(loadData,2000);
function openModalFromCard(card){
let orig=card.dataset.orig;
let result=card.dataset.result;
let filename=card.dataset.filename;
let detection=JSON.parse(card.dataset.detection||'{}');
openModal(orig,result,filename,detection);
}
function openModal(origSrc,resultSrc,filename,detection){
document.getElementById('modalTitle').textContent=filename;
document.getElementById('modalOrigImg').src=origSrc;
document.getElementById('modalResultImg').src=resultSrc||'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22300%22 height=%22225%22%3E%3Crect fill=%22%231e293b%22 width=%22300%22 height=%22225%22/%3E%3Ctext fill=%22%23475569%22 font-family=%22Arial%22 font-size=%2213%22 x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22 dominant-baseline=%22middle%22%3E检测中...%3C/text%3E%3C/svg%3E';
let d=detection||{};
let sev=d.severity||'无裂缝';
let sevClass=SEV_CLASS[sev]||'sev-none';
document.getElementById('modalFooter').innerHTML=`
<div class="footer-item"><div class="footer-value">${d.num_cracks||0}</div><div class="footer-label">裂缝数</div></div>
<div class="footer-item"><div class="footer-value">${d.crack_area_ratio?d.crack_area_ratio.toFixed(2):'0.00'}%</div><div class="footer-label">面积占比</div></div>
<div class="footer-item"><div class="footer-value">${d.avg_confidence?Math.round(d.avg_confidence*100):0}%</div><div class="footer-label">置信度</div></div>
<div class="footer-item"><div class="footer-value"><span class="severity ${sevClass}">${sev}</span></div><div class="footer-label">严重程度</div></div>`;
document.getElementById('modalOverlay').classList.add('active');
document.body.style.overflow='hidden';
}
function closeModal(){
document.getElementById('modalOverlay').classList.remove('active');
document.body.style.overflow='';
}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeModal()});
async function logout(){
await fetch('/api/logout',{method:'POST'});
window.location.href='/login';
}
</script>
</body>
</html>"""
    html = html.replace('__USERNAME__', current_username).replace('__ROLE__', current_role)
    return html


if __name__ == '__main__':
    # 获取本机IP地址
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    print(f"🚀 CrackBot 后端启动")
    print(f"📍 监听地址: http://{local_ip}:5050")
    print(f"📁 图片保存目录: {os.path.abspath(UPLOAD_FOLDER)}")

    app.run(host='0.0.0.0', port=5050, debug=False)