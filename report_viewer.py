"""
本地检测报告查看器 - 完全离线，不依赖网络
用法: python report_viewer.py
"""
import os
import json
import base64
import webbrowser
import shutil
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

SESSION = "20260615_164938"
BASE_DIR = Path(r"C:\Users\86135\Desktop\embed\uploads")
IMG_DIR = BASE_DIR / "images" / SESSION
RES_DIR = BASE_DIR / "results" / SESSION
LOG_PATH = BASE_DIR / "logs" / f"{SESSION}.json"
PORT = 5099


def load_data():
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def make_thumbnail(path, size=280):
    import cv2
    img = cv2.imread(str(path))
    if img is None:
        return ""
    h, w = img.shape[:2]
    scale = size / max(h, w)
    if scale < 1.0:
        new_w, new_h = int(w * scale), int(h * scale)
        img = cv2.resize(img, (new_w, new_h))
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return base64.b64encode(buf).decode()


def build_html(data):
    total_images = len(data)
    total_cracks = sum(d["detection"]["num_cracks"] for d in data)
    images_with_cracks = sum(1 for d in data if d["detection"]["num_cracks"] > 0)
    images_without_cracks = total_images - images_with_cracks
    total_area = sum(d["detection"]["crack_area_ratio"] for d in data)
    avg_area = total_area / total_images if total_images > 0 else 0

    severity_counts = {"严重": 0, "中等": 0, "轻微": 0, "无裂缝": 0}
    for d in data:
        sev = d["detection"]["severity"]
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    confs = [d["detection"]["avg_confidence"] for d in data if d["detection"]["num_cracks"] > 0]
    avg_conf = sum(confs) / len(confs) * 100 if confs else 0

    max_cracks_entry = max(data, key=lambda d: d["detection"]["num_cracks"])
    max_area_entry = max(data, key=lambda d: d["detection"]["crack_area_ratio"])

    data_reversed = list(reversed(data))
    cards_parts = []
    for d in data_reversed:
        orig_name = d["filename"]
        res_name = orig_name.replace(".jpg", "_result.jpg")
        det = d["detection"]
        sev = det["severity"]
        sev_color = {"严重": "#ef4444", "中等": "#f59e0b", "轻微": "#22c55e", "无裂缝": "#64748b"}
        short_name = orig_name if len(orig_name) <= 28 else orig_name[:27] + "..."

        orig_thumb = make_thumbnail(IMG_DIR / orig_name)
        res_thumb = make_thumbnail(RES_DIR / res_name)

        cards_parts.append(
            '<div class="card">'
            f'<div class="card-header"><span class="filename" title="{orig_name}">{short_name}</span><span class="seg">S{d["segment"]}</span></div>'
            '<div class="image-pair">'
            f'<div class="img-box" onclick="showLightbox(\'{orig_name}\',\'{res_name}\')"><img src="data:image/jpeg;base64,{orig_thumb}" loading="lazy"><span class="label">原图</span></div>'
            f'<div class="img-box" onclick="showLightbox(\'{orig_name}\',\'{res_name}\')"><img src="data:image/jpeg;base64,{res_thumb}" loading="lazy"><span class="label">检测结果</span></div>'
            '</div>'
            '<div class="card-footer">'
            f'<div class="stat"><span class="stat-val" style="color:{sev_color.get(sev, "#64748b")}">{det["num_cracks"]}</span><span class="stat-label">裂缝数</span></div>'
            f'<div class="stat"><span class="stat-val">{det["crack_area_ratio"]:.2f}%</span><span class="stat-label">面积占比</span></div>'
            f'<div class="stat"><span class="stat-val">{det["avg_confidence"] * 100:.0f}%</span><span class="stat-label">置信度</span></div>'
            f'<div class="stat"><span class="stat-val severity sev-{sev}">{sev}</span><span class="stat-label">严重程度</span></div>'
            '</div>'
            '</div>'
        )

    upload_time = data[-1]["upload_time"] if data else "N/A"
    mc_name = max_cracks_entry["filename"][:20] if total_images > 0 else "-"
    ma_name = max_area_entry["filename"][:20] if total_images > 0 else "-"
    mc_count = max_cracks_entry["detection"]["num_cracks"] if total_images > 0 else 0
    ma_ratio = max_area_entry["detection"]["crack_area_ratio"] if total_images > 0 else 0

    html = _HTML_TOP.replace("__SESSION__", SESSION)
    html = html.replace("__UPLOAD_TIME__", upload_time)
    html = html.replace("__TOTAL_IMAGES__", str(total_images))
    html = html.replace("__TOTAL_CRACKS__", str(total_cracks))
    html = html.replace("__WITH_CRACKS__", str(images_with_cracks))
    html = html.replace("__WITHOUT_CRACKS__", str(images_without_cracks))
    html = html.replace("__AVG_AREA__", f"{avg_area:.2f}%")
    html = html.replace("__AVG_CONF__", f"{avg_conf:.0f}%")
    html = html.replace("__SEV_SERIOUS__", str(severity_counts.get("严重", 0)))
    html = html.replace("__SEV_MODERATE__", str(severity_counts.get("中等", 0)))
    html = html.replace("__SEV_MILD__", str(severity_counts.get("轻微", 0)))
    html = html.replace("__SEV_NONE__", str(severity_counts.get("无裂缝", 0)))
    html = html.replace("__MAX_CRACKS_COUNT__", str(mc_count))
    html = html.replace("__MAX_CRACKS_NAME__", mc_name)
    html = html.replace("__MAX_AREA_RATIO__", f"{ma_ratio:.2f}%")
    html = html.replace("__MAX_AREA_NAME__", ma_name)
    html = html.replace("__CARDS__", "\n".join(cards_parts))
    return html


_HTML_TOP = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>裂缝检测报告 - __SESSION__</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0b1120;color:#e2e8f0}
.header{background:linear-gradient(135deg,#1e293b,#0f172a);padding:28px 32px;border-bottom:1px solid rgba(148,163,184,0.1)}
.header h1{font-size:22px;margin-bottom:4px}
.header .sub{font-size:13px;color:#64748b}
.report-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;padding:20px 32px}
.r-card{background:rgba(30,41,59,0.6);border:1px solid rgba(148,163,184,0.08);border-radius:12px;padding:18px;text-align:center}
.r-card .val{font-size:28px;font-weight:700;color:#38bdf8}
.r-card .lbl{font-size:11px;color:#64748b;margin-top:4px;text-transform:uppercase;letter-spacing:0.5px}
.r-card .val.red{color:#f87171}
.r-card .val.amber{color:#fbbf24}
.r-card .val.green{color:#4ade80}
.section{padding:0 32px 8px}
.section h2{font-size:16px;color:#94a3b8;border-bottom:1px solid rgba(148,163,184,0.1);padding-bottom:8px;margin-bottom:12px}
.detail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;padding:0 32px 20px}
.d-card{background:rgba(30,41,59,0.4);border:1px solid rgba(148,163,184,0.06);border-radius:10px;padding:14px}
.d-card .d-val{font-size:18px;font-weight:600;color:#e2e8f0}
.d-card .d-lbl{font-size:11px;color:#64748b}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:18px;padding:0 32px 32px}
.card{background:rgba(30,41,59,0.5);border:1px solid rgba(148,163,184,0.08);border-radius:14px;overflow:hidden;transition:transform 0.15s,border-color 0.15s}
.card:hover{transform:translateY(-2px);border-color:rgba(56,189,248,0.3)}
.card-header{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:rgba(15,23,42,0.5);border-bottom:1px solid rgba(148,163,184,0.06)}
.filename{font-size:11px;color:#94a3b8;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.seg{font-size:11px;color:#64748b;background:rgba(148,163,184,0.1);padding:2px 8px;border-radius:10px}
.image-pair{display:grid;grid-template-columns:1fr 1fr;cursor:pointer}
.img-box{padding:8px;position:relative}
.img-box img{width:100%;border-radius:8px;aspect-ratio:4/3;object-fit:cover;background:#0b1120}
.img-box .label{font-size:10px;color:#64748b;text-align:center;display:block;margin-top:4px}
.card-footer{display:flex;justify-content:space-around;padding:8px 14px;border-top:1px solid rgba(148,163,184,0.06)}
.stat{text-align:center}
.stat-val{font-size:14px;font-weight:700;color:#38bdf8;display:block}
.stat-label{font-size:10px;color:#64748b}
.severity{padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600}
.sev-严重{background:rgba(239,68,68,0.2);color:#fca5a5}
.sev-中等{background:rgba(245,158,11,0.2);color:#fcd34d}
.sev-轻微{background:rgba(34,197,94,0.2);color:#86efac}
.sev-无裂缝{background:rgba(100,116,139,0.2);color:#94a3b8}
.lightbox{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.92);z-index:1000;flex-direction:column;align-items:center;justify-content:center}
.lightbox.active{display:flex}
.lightbox .close{position:absolute;top:20px;right:30px;font-size:32px;color:#fff;cursor:pointer;z-index:1001;width:44px;height:44px;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,0.1);border-radius:50%}
.lightbox .close:hover{background:rgba(255,255,255,0.2)}
.lightbox .lb-container{display:flex;gap:30px;align-items:flex-start;max-width:95vw;max-height:85vh}
.lightbox .lb-panel{text-align:center}
.lightbox .lb-panel img{max-height:70vh;max-width:45vw;border-radius:10px;object-fit:contain}
.lightbox .lb-panel .lb-label{color:#94a3b8;font-size:13px;margin-top:8px}
.lightbox .lb-info{color:#94a3b8;font-size:13px;margin-top:16px;text-align:center}
@media(max-width:768px){.lightbox .lb-container{flex-direction:column;max-height:90vh;overflow-y:auto}.lightbox .lb-panel img{max-width:90vw;max-height:40vh}.gallery{grid-template-columns:1fr}}
.footer-note{text-align:center;padding:24px;color:#475569;font-size:12px;border-top:1px solid rgba(148,163,184,0.06)}
</style>
</head>
<body>
<div class="header">
<h1>&#128202; 裂缝检测报告</h1>
<div class="sub">会话: __SESSION__ | 扫描时间: __UPLOAD_TIME__ | 共 __TOTAL_IMAGES__ 张图片</div>
</div>
<div class="report-grid">
<div class="r-card"><div class="val">__TOTAL_IMAGES__</div><div class="lbl">总检测图片</div></div>
<div class="r-card"><div class="val red">__TOTAL_CRACKS__</div><div class="lbl">裂缝总数</div></div>
<div class="r-card"><div class="val amber">__WITH_CRACKS__</div><div class="lbl">含裂缝图片</div></div>
<div class="r-card"><div class="val green">__WITHOUT_CRACKS__</div><div class="lbl">无裂缝图片</div></div>
<div class="r-card"><div class="val">__AVG_AREA__</div><div class="lbl">平均裂缝面积</div></div>
<div class="r-card"><div class="val">__AVG_CONF__</div><div class="lbl">平均置信度</div></div>
</div>
<div class="section"><h2>&#9888; 严重程度分布</h2></div>
<div class="detail-grid">
<div class="d-card"><div class="d-val" style="color:#fca5a5">__SEV_SERIOUS__</div><div class="d-lbl">严重裂缝</div></div>
<div class="d-card"><div class="d-val" style="color:#fcd34d">__SEV_MODERATE__</div><div class="d-lbl">中等裂缝</div></div>
<div class="d-card"><div class="d-val" style="color:#86efac">__SEV_MILD__</div><div class="d-lbl">轻微裂缝</div></div>
<div class="d-card"><div class="d-val" style="color:#94a3b8">__SEV_NONE__</div><div class="d-lbl">无裂缝</div></div>
<div class="d-card"><div class="d-val">__MAX_CRACKS_COUNT__</div><div class="d-lbl">单图最多裂缝 (__MAX_CRACKS_NAME__)</div></div>
<div class="d-card"><div class="d-val">__MAX_AREA_RATIO__</div><div class="d-lbl">单图最大面积 (__MAX_AREA_NAME__)</div></div>
</div>
<div class="section"><h2>&#128444; 图片详情 (点击放大)</h2></div>
<div class="gallery">__CARDS__</div>
<div id="lightbox" class="lightbox" onclick="closeLightbox(event)">
<div class="close" onclick="closeLightbox()">&times;</div>
<div class="lb-container">
<div class="lb-panel"><img id="lb-orig"><div class="lb-label">&#128247; 原始图片</div></div>
<div class="lb-panel"><img id="lb-res"><div class="lb-label">&#128300; 检测结果</div></div>
</div>
<div class="lb-info">点击任意位置或按 ESC 关闭</div>
</div>
<div class="footer-note">&#128204; 本地离线报告 | 生成时间: <span id="genTime"></span></div>
<script>
var IMG_DIR="images/__SESSION__";
var RES_DIR="results/__SESSION__";
document.getElementById("genTime").textContent=new Date().toLocaleString();
function showLightbox(orig,res){
document.getElementById("lb-orig").src=IMG_DIR+"/"+orig;
document.getElementById("lb-res").src=RES_DIR+"/"+res;
document.getElementById("lightbox").classList.add("active");
document.body.style.overflow="hidden";
}
function closeLightbox(e){
if(e && e.target !== document.getElementById("lightbox") && !e.target.classList.contains("close")) return;
document.getElementById("lightbox").classList.remove("active");
document.body.style.overflow="";
}
document.addEventListener("keydown",function(e){if(e.key==="Escape") closeLightbox()});
</script>
</body>
</html>"""


def start_server():
    data = load_data()
    html = build_html(data)

    print("生成报告中...")
    with open("_report.html", "w", encoding="utf-8") as f:
        f.write(html)

    img_target = Path(f"images/{SESSION}")
    res_target = Path(f"results/{SESSION}")
    img_target.mkdir(parents=True, exist_ok=True)
    res_target.mkdir(parents=True, exist_ok=True)

    for f in IMG_DIR.iterdir():
        dst = img_target / f.name
        if not dst.exists():
            shutil.copy2(str(f), str(dst))

    for f in RES_DIR.iterdir():
        dst = res_target / f.name
        if not dst.exists():
            shutil.copy2(str(f), str(dst))

    print(f"\n报告已生成: {Path('_report.html').absolute()}")
    print(f"打开浏览器: http://localhost:{PORT}")
    print("按 Ctrl+C 停止服务器\n")

    webbrowser.open(f"http://localhost:{PORT}/_report.html")

    server = HTTPServer(("", PORT), SimpleHTTPRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.shutdown()


if __name__ == "__main__":
    start_server()
