"""
Z-Image-Turbo 完整客户端示例脚本

演示从创建文生图任务到下载最终图片的完整流程：
  1. 通过 WebSocket 连接服务器
  2. 发送 create_job 消息创建文生图任务
  3. 监听实时进度和状态更新
  4. 任务完成后通过 HTTP API 下载生成的图片

使用方法：
  先启动服务器:  python server.py
  再运行脚本:    python example_client.py

依赖:  pip install websockets httpx
"""

import asyncio
import json
import os
import sys
import uuid

import httpx
import websockets

# ===== 配置区域 =====

BASE_URL = f"http://0.0.0.0:8000/z-image-turbo-app"
WS_URL = f"ws://0.0.0.0:8000/z-image-turbo-app/api/ws"

# 文生图参数
PROMPT = "一只戴着小礼帽的可爱猫咪，坐在一摞书上，水彩画风格"
WIDTH = 512 
HEIGHT = 512
STEPS = 9               # 推理步数，越多质量越高但越慢
GUIDANCE_SCALE = 0.0     # CFG 引导强度
SEED = 42                # 随机种子，相同种子生成相同图片
MODEL_TYPE = "uint4"     # 模型量化类型

# 图片保存目录
DOWNLOAD_DIR = "downloaded_images"


async def main():
    """主流程：连接 → 创建任务 → 监听进度 → 下载图片"""

    # 生成唯一的客户端 ID（用于断线重连时恢复订阅）
    client_id = f"example-client-{uuid.uuid4().hex[:8]}"
    # 生成唯一的请求 ID（用于追踪这个具体请求的响应）
    request_id = f"req-{uuid.uuid4().hex[:8]}"

    print("=" * 60)
    print("  Z-Image-Turbo 文生图客户端示例")
    print("=" * 60)
    print(f"  服务器地址:  {BASE_URL}")
    print(f"  客户端 ID:   {client_id}")
    print(f"  提示词:      {PROMPT}")
    print(f"  图片尺寸:    {WIDTH}x{HEIGHT}")
    print(f"  推理步数:    {STEPS}")
    print(f"  随机种子:    {SEED}")
    print("=" * 60)

    # ----- 第一步：检查服务器健康状态 -----
    print("\n[1/4] 检查服务器状态...")
    async with httpx.AsyncClient() as http_client:
        try:
            resp = await http_client.get(f"{BASE_URL}/api/health")
            resp.raise_for_status()
            health = resp.json()
            print(f"  ✓ 服务器状态: {health['status']}")
        except Exception as e:
            print(f"  ✗ 无法连接服务器: {e}")
            print("  请确认服务器已启动: python server.py")
            sys.exit(1)

    # ----- 第二步：通过 WebSocket 创建文生图任务 -----
    print(f"\n[2/4] 通过 WebSocket 连接服务器并创建任务...")

    # 连接时附带 client_id，支持断线重连
    ws_url_with_client = f"{WS_URL}?client_id={client_id}"

    result = None  # 存储最终结果

    async with websockets.connect(ws_url_with_client) as ws:
        print(f"  ✓ WebSocket 已连接")

        # 构造 create_job 消息
        create_job_message = {
            "type": "create_job",          # 消息类型：创建任务
            "task_type": "text_to_image",   # 任务类型：文生图
            "request_id": request_id,       # 请求 ID，服务端会在响应中回传
            "params": {
                "prompt": PROMPT,
                "width": WIDTH,
                "height": HEIGHT,
                "steps": STEPS,
                "guidance_scale": GUIDANCE_SCALE,
                "seed": SEED,
                "model_type": MODEL_TYPE,
            }
        }

        # 发送创建任务消息
        await ws.send(json.dumps(create_job_message))
        print(f"  ✓ 已发送 create_job 消息")

        # ----- 第三步：监听服务端推送的实时状态 -----
        print(f"\n[3/4] 等待任务完成（实时接收进度更新）...")
        print("-" * 60)

        job_id = None

        while True:
            # 接收服务端推送的消息
            raw = await ws.recv()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "job_status":
                # ---- 任务状态变更 ----
                job_id = msg.get("job_id", job_id)
                status = msg.get("status")

                if status == "pending":
                    # 任务已入队，等待执行
                    print(f"  [{status}]      任务已创建，等待调度...")
                    print(f"               Job ID: {job_id}")

                elif status == "processing":
                    # GPU 正在生成图片
                    print(f"  [{status}]  GPU 正在生成图片...")

                elif status == "completed":
                    # 任务完成！提取结果
                    result = msg.get("result", {})
                    filename = result.get("filename", "")
                    print(f"  [{status}]  任务完成!")
                    print(f"               图片文件:     {filename}")
                    break  # 退出监听循环

                elif status == "failed":
                    # 任务失败
                    error = msg.get("error", "未知错误")
                    print(f"  [{status}]     任务失败: {error}")
                    sys.exit(1)

                elif status == "cancelled":
                    print(f"  [{status}]  任务已被取消")
                    sys.exit(0)

                else:
                    print(f"  [{status}]  未知状态")

            elif msg_type == "job_progress":
                # ---- 进度更新 ----
                progress = msg.get("progress", {})
                stage = progress.get("stage", "")
                percent = progress.get("percent")
                step = progress.get("step")
                total = progress.get("total_steps")

                if step is not None and total is not None:
                    bar_len = 30
                    filled = int(bar_len * step / total)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    print(f"  [进度]       {stage}: [{bar}] {step}/{total}", end="\r")
                elif percent is not None:
                    print(f"  [进度]       {stage}: {percent}%", end="\r")

                # 进度更新后换行，以免下条消息覆盖
                if step == total or percent == 100:
                    print()

            elif msg_type == "error":
                # ---- 错误消息 ----
                print(f"  [错误]       {msg.get('message')}")
                sys.exit(1)

            else:
                # ---- 其他消息 ----
                print(f"  [其他]       {msg}")

        print("-" * 60)

    # ----- 第四步：通过 HTTP 下载图片 -----
    if result is None:
        print("\n未获取到结果，退出。")
        sys.exit(1)

    print(f"\n[4/4] 下载生成的图片...")

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    async with httpx.AsyncClient() as http_client:
        downloaded_files = []

        # 下载图片
        filename = result.get("filename")
        if filename:
            url = f"{BASE_URL}/api/image/{filename}"
            local_path = os.path.join(DOWNLOAD_DIR, filename)
            print(f"  下载图片:     {url}")
            resp = await http_client.get(url)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(resp.content)
            size_kb = len(resp.content) / 1024
            print(f"  ✓ 已保存:     {local_path} ({size_kb:.1f} KB)")
            downloaded_files.append(local_path)

    # ----- 完成 -----
    print("\n" + "=" * 60)
    print("  全部完成!")
    print(f"  共下载 {len(downloaded_files)} 张图片到 ./{DOWNLOAD_DIR}/")
    for f in downloaded_files:
        print(f"    - {f}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
