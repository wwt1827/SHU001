"""
树莓派客户端 —— 跑在树莓派上
拍照并发送到 PC 后端进行裂缝检测，接收结果并显示/保存

启动方式: python raspi_client.py
使用前请修改下面的 SERVER_URL 为你的 PC 的 IP 地址
"""
import sys
import time
import json
import base64
import requests
from pathlib import Path
from datetime import datetime

# ═════════════════ 配置（上线前必须修改） ═════════════════
# TODO: 把 IP 地址改成你 PC 在局域网中的实际 IP
SERVER_URL = "http://192.168.43.224:5005"
SAVE_DIR = "crack_results"
CONF_THRESHOLD = 0.25
IOU_THRESHOLD = 0.7

# ═════════════════ 树莓派摄像头 ═════════════════
try:
    from picamera2 import Picamera2
    _has_picamera2 = True
except ImportError:
    _has_picamera2 = False
    print("[WARN] 未安装 picamera2，将使用 OpenCV 摄像头")

try:
    import cv2
except ImportError:
    cv2 = None
    print("[ERROR] 未安装 OpenCV，无法拍照")


def take_photo_picamera2():
    """树莓派官方摄像头（picamera2）拍照"""
    picam2 = Picamera2()
    config = picam2.create_still_configuration(main={"size": (1920, 1080)})
    picam2.configure(config)
    picam2.start()
    time.sleep(1)  # 等待曝光稳定
    img = picam2.capture_array()
    picam2.stop()
    picam2.close()
    print(f"  照片尺寸: {img.shape}")
    return img


def take_photo_cv2():
    """OpenCV 通用摄像头拍照（USB摄像头或备用）"""
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERROR] 无法打开摄像头")
        raise RuntimeError("摄像头不可用")
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print("[ERROR] 拍照失败")
        raise RuntimeError("拍照失败")
    print(f"  照片尺寸: {frame.shape}")
    # OpenCV 是 BGR，转 RGB
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def take_photo():
    """统一拍照入口：优先 picamera2，fallback OpenCV"""
    if _has_picamera2:
        try:
            return take_photo_picamera2()
        except Exception as e:
            print(f"  picamera2 拍照失败: {e}，尝试 OpenCV...")
    return take_photo_cv2()


def send_to_backend(image_rgb, server_url=SERVER_URL, conf=CONF_THRESHOLD, iou=IOU_THRESHOLD):
    """
    将图片发送到后端 API 进行裂缝检测

    Args:
        image_rgb: RGB 格式的 numpy 数组
        server_url: 后端 API 地址
        conf: 置信度阈值
        iou: IOU 阈值

    Returns:
        dict: 后端返回的检测结果
    """
    # RGB 转 BGR，再编码为 JPEG
    import cv2 as cv
    image_bgr = cv.cvtColor(image_rgb, cv.COLOR_RGB2BGR)
    _, buffer = cv.imencode('.jpg', image_bgr, [cv.IMWRITE_JPEG_QUALITY, 85])

    files = {
        'file': (
            f'crack_{datetime.now().strftime("%Y%m%d_%H%M%S")}.jpg',
            buffer.tobytes(),
            'image/jpeg'
        )
    }
    params = {'conf': conf, 'iou': iou, 'return_image': True}

    print(f"  正在发送到 {server_url}/detect ...")
    t_start = time.time()

    try:
        resp = requests.post(
            f"{server_url}/detect",
            files=files,
            params=params,
            timeout=30,
        )
    except requests.exceptions.ConnectionError:
        print(f"\n[ERROR] 无法连接到后端服务器 {server_url}")
        print("  请检查:")
        print("  1. PC 上的 backend_api.py 是否已启动")
        print("  2. 树莓派和 PC 是否在同一局域网")
        print("  3. PC 的 IP 地址是否正确")
        print("  4. PC 防火墙是否开放了 8000 端口\n")
        raise
    except requests.exceptions.Timeout:
        print(f"\n[ERROR] 请求超时（>30秒），可能网络不稳定\n")
        raise

    t_end = time.time()
    elapsed = round((t_end - t_start) * 1000, 1)

    if resp.status_code != 200:
        print(f"  [ERROR] 服务器返回错误: {resp.status_code}")
        print(f"  {resp.text}")
        raise RuntimeError(f"HTTP {resp.status_code}")

    data = resp.json()
    data['network_time_ms'] = elapsed
    return data


def save_result(result, image_rgb):
    """保存检测结果到本地"""
    os.makedirs(SAVE_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 保存标注图片
    if result.get('annotated_image'):
        img_data = base64.b64decode(result['annotated_image'])
        img_path = os.path.join(SAVE_DIR, f"result_{timestamp}.jpg")
        with open(img_path, 'wb') as f:
            f.write(img_data)
        print(f"  标注图片已保存: {img_path}")

    # 保存原始图片
    import cv2 as cv
    orig_bgr = cv.cvtColor(image_rgb, cv.COLOR_RGB2BGR)
    orig_path = os.path.join(SAVE_DIR, f"original_{timestamp}.jpg")
    cv.imwrite(orig_path, orig_bgr)
    print(f"  原始图片已保存: {orig_path}")

    # 保存 JSON 结果
    json_result = {k: v for k, v in result.items() if k != 'annotated_image'}
    json_path = os.path.join(SAVE_DIR, f"result_{timestamp}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_result, f, ensure_ascii=False, indent=2)
    print(f"  检测报告已保存: {json_path}")


def print_result(result):
    """在终端打印检测结果摘要"""
    print()
    print("=" * 50)
    print("  检测结果")
    print("=" * 50)
    print(f"  文件名: {result.get('filename', 'N/A')}")
    print(f"  图像尺寸: {result.get('image_size', {})}")
    print(f"  推理设备: {result.get('device', 'N/A')}")
    print(f"  使用模型: {result.get('model', 'N/A')}")
    print("-" * 50)
    print(f"  🛑 裂缝数量: {result.get('crack_count', 0)}")
    print(f"  ⚠️  严重程度: {result.get('severity', 'N/A')}")
    print(f"  📐 裂缝面积占比: {result.get('crack_ratio', 0)}%")
    print(f"  📊 平均置信度: {result.get('avg_confidence', 0)}")
    print(f"  ⏱️  推理耗时: {result.get('inference_time_ms', 0)} ms")
    print(f"  🌐 网络耗时: {result.get('network_time_ms', 0)} ms")
    total = result.get('inference_time_ms', 0) + result.get('network_time_ms', 0)
    print(f"  📡 总耗时: {total} ms")
    if result.get('confidences'):
        print(f"  🎯 各裂缝置信度: {result['confidences']}")
    print("=" * 50)


def interactive_mode():
    """交互式模式：持续拍照检测"""
    import os

    print("=" * 60)
    print("  墙面裂缝检测 - 树莓派客户端")
    print("=" * 60)
    print(f"  后端地址: {SERVER_URL}")
    print(f"  结果保存: {SAVE_DIR}/")
    print()

    # 检查后端连通性
    print("  检查后端连接...")
    try:
        resp = requests.get(f"{SERVER_URL}/health", timeout=5)
        if resp.status_code == 200:
            health = resp.json()
            print(f"  后端状态: {health['status']}")
            print(f"  使用模型: {health.get('model_path', 'N/A')}")
            print(f"  计算设备: {health.get('device', 'N/A')}")
        else:
            print(f"  [WARN] 健康检查返回 {resp.status_code}")
    except Exception as e:
        print(f"  [ERROR] 无法连接后端: {e}")
        print("  请先启动 PC 上的 backend_api.py 再运行本程序")
        return

    print()
    print("  指令说明:")
    print("    [回车] 拍照检测")
    print("    q      退出")
    print("    s      切换自动保存 (当前: 开启)")
    print("    v      切换 verbose")
    print()

    auto_save = True
    verbose = True

    while True:
        cmd = input(">>> ").strip().lower()

        if cmd == 'q':
            print("  退出客户端")
            break
        elif cmd == 's':
            auto_save = not auto_save
            print(f"  自动保存: {'开启' if auto_save else '关闭'}")
            continue
        elif cmd == 'v':
            verbose = not verbose
            print(f"  详细输出: {'开启' if verbose else '关闭'}")
            continue
        elif cmd != '':
            print("  未知命令，按回车拍照，q 退出")
            continue

        # 拍照 + 发送
        try:
            print("\n  📷 正在拍照...")
            img = take_photo()

            print("  📡 正在发送到后端...")
            result = send_to_backend(img)

            if verbose:
                print_result(result)

            if auto_save:
                save_result(result, img)

        except RuntimeError as e:
            print(f"  [ERROR] {e}")
        except Exception as e:
            print(f"  [ERROR] 未知错误: {e}")
            import traceback
            traceback.print_exc()


def single_shot_mode(image_path=None):
    """单次模式：拍一张照片并检测"""
    print("=" * 60)
    print("  墙面裂缝检测 - 树莓派客户端 (单次模式)")
    print("=" * 60)

    # 检查连通性
    print("  检查后端连接...")
    try:
        resp = requests.get(f"{SERVER_URL}/health", timeout=5)
        if resp.status_code != 200:
            print(f"  [ERROR] 后端不可用")
            return
    except Exception:
        print(f"  [ERROR] 无法连接后端 {SERVER_URL}")
        return

    if image_path and os.path.exists(image_path):
        # 使用已有图片
        print(f"  使用图片: {image_path}")
        img = cv2.imread(image_path)
        if img is None:
            print("[ERROR] 无法读取图片")
            return
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    else:
        # 拍照
        print("  📷 正在拍照...")
        try:
            img = take_photo()
        except Exception as e:
            print(f"  [ERROR] 拍照失败: {e}")
            return

    # 发送检测
    try:
        result = send_to_backend(img)
        print_result(result)
        save_result(result, img)
    except Exception as e:
        print(f"  [ERROR] 检测失败: {e}")


# ═════════════════ 主入口 ═════════════════
if __name__ == '__main__':
    import os

    # 检查依赖
    missing = []
    try:
        import requests
    except ImportError:
        missing.append('requests')
        print("[ERROR] 缺少 requests 库，请在树莓派上执行: pip install requests")
    try:
        import cv2
    except ImportError:
        missing.append('opencv-python')
        print("[ERROR] 缺少 opencv 库，请在树莓派上执行: pip install opencv-python")
    if missing:
        print(f"请先安装: pip install {' '.join(missing)}")
        sys.exit(1)

    # 判断模式
    if len(sys.argv) > 1:
        # 命令行单次模式
        img_path = sys.argv[1] if sys.argv[1] != '--single' else None
        single_shot_mode(img_path)
    else:
        # 交互式模式
        interactive_mode()