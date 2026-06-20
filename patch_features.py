# -*- coding: utf-8 -*-
"""
自动补丁脚本 —— 为 main_backup.py 添加历史查询 + 报告生成功能
使用方法：python patch_features.py
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(BASE_DIR, 'main_backup.py')
BACKUP = os.path.join(BASE_DIR, 'main_backup.py.bak')

with open(TARGET, 'r', encoding='utf-8') as f:
    content = f.read()

with open(BACKUP, 'w', encoding='utf-8') as f:
    f.write(content)
print(f'已备份到 {BACKUP}')

# ========== 插入 API 路由 ==========
MARKER1 = "    return jsonify({\"error\": \"工单不存在\"}), 404\n\n\n@app.route('/api/upload', methods=['POST'])"

API_CODE = '''    return jsonify({"error": "工单不存在"}), 404


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
    output.write('\ufeff')
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


@app.route('/api/upload', methods=['POST'])'''

if 'def get_all_inspection_records():' in content:
    print('已打过补丁，跳过 API 路由')
else:
    if MARKER1 in content:
        content = content.replace(MARKER1, API_CODE, 1)
        print('已插入 API 路由 (历史查询 + 报告生成)')
    else:
        print('错误: 找不到插入点 MARKER1，文件可能已被修改')
        exit(1)

# ========== 插入页面路由 ==========
MARKER2 = "    return html\n\n\n@app.route('/')"

PAGE_ROUTES = '''    return html


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


@app.route('/')'''

if 'def history_page():' in content:
    print('已打过补丁，跳过页面路由')
else:
    if MARKER2 in content:
        content = content.replace(MARKER2, PAGE_ROUTES, 1)
        print('已插入页面路由 (history + report)')
    else:
        print('错误: 找不到插入点 MARKER2')
        exit(1)

# ========== 插入导航标签 (workorders 页面) ==========
MARKER3 = '<a href="/workorders" class="nav-tab active">&#128196; 工单管理</a>\n</div>\n<span style="font-size:13px;color:#94a3b8">&#128100; __USERNAME__</span>'
INSERT3 = '<a href="/workorders" class="nav-tab active">&#128196; 工单管理</a>\n<a href="/history" class="nav-tab">&#128269; 历史查询</a>\n<a href="/report" class="nav-tab">&#128202; 报告生成</a>\n</div>\n<span style="font-size:13px;color:#94a3b8">&#128100; __USERNAME__</span>'

if MARKER3 in content:
    content = content.replace(MARKER3, INSERT3, 1)
    print('已插入导航标签 (workorders 页面)')
else:
    print('警告: 未找到 workorders 页面导航标签，请手动添加')

# ========== 插入导航标签 (index 页面) ==========
MARKER4 = '<a href="/workorders" class="nav-tab">&#128196; 工单管理</a>\n</div>\n<span style="font-size:13px;color:#94a3b8">&#128100; __USERNAME__ <span'
INSERT4 = '<a href="/workorders" class="nav-tab">&#128196; 工单管理</a>\n<a href="/history" class="nav-tab">&#128269; 历史查询</a>\n<a href="/report" class="nav-tab">&#128202; 报告生成</a>\n</div>\n<span style="font-size:13px;color:#94a3b8">&#128100; __USERNAME__ <span'

if MARKER4 in content:
    content = content.replace(MARKER4, INSERT4, 1)
    print('已插入导航标签 (index 页面)')
else:
    print('警告: 未找到 index 页面导航标签，请手动添加')

# ========== 写回 ==========
with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(content)

print(f'\n补丁应用完成! 已修改: {TARGET}')
print('请重启 Flask 服务后访问:')
print('  http://localhost:5000/history  - 历史查询')
print('  http://localhost:5000/report   - 报告生成')