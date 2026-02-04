# Z-Image-Turbo

高性能文生图服务器，基于 FastAPI + WebSocket 实时任务管理系统。

- 模型：[Z-Image-Turbo-SDNQ](https://huggingface.co/Disty0/Z-Image-Turbo-SDNQ-uint4-svd-r32)（量化 Stable Diffusion）
- 超分辨率：Real-ESRGAN x4
## 快速开始

```bash
# 安装依赖并启动服务器
bash start.sh
```

服务运行在 `http://0.0.0.0:8004`，API 文档访问 `/docs`。

## API 参考

### REST 接口

#### 健康检查

```
GET /api/health
```

响应：

```json
{ "status": "ok" }
```

#### 获取图片

```
GET /api/image/{filename}
```

返回生成的图片文件（PNG）。

---

### WebSocket API

```
WebSocket /api/ws?client_id={client_id}
```

- `client_id`（可选）：客户端标识符。使用相同的 `client_id` 重连时，订阅关系会保持。

所有消息均为 JSON 格式。客户端发送带有 `type` 字段的消息，服务器返回相应的响应消息。

---

## 图片生成完整流程

### 第一步：连接 WebSocket

```javascript
const ws = new WebSocket("ws://localhost:8004/api/ws?client_id=my-client-001");
```

### 第二步：发送 `create_job` 消息

```json
{
  "type": "create_job",
  "task_type": "text_to_image",
  "request_id": "req-001",
  "params": {
    "prompt": "a cute cat wearing sunglasses, digital art",
    "width": 1024,
    "height": 1024,
    "steps": 9,
    "guidance_scale": 0.0,
    "seed": 42,
    "model_type": "uint4"
  }
}
```

**参数说明：**

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `prompt` | string | **必填** | 图片的文本描述 |
| `width` | int | 1024 | 图片宽度（像素） |
| `height` | int | 1024 | 图片高度（像素） |
| `steps` | int | 9 | 推理步数（越多质量越高，速度越慢） |
| `guidance_scale` | float | 0.0 | 无分类器引导比例 |
| `seed` | int | 42 | 随机种子，用于结果复现 |
| `model_type` | string | "uint4" | 量化类型：`"uint4"` 或 `"int8"` |

### 第三步：接收状态更新

服务器按以下顺序推送消息：

**1) 任务已创建**

```json
{
  "type": "job_status",
  "job_id": "abc123...",
  "status": "pending",
  "request_id": "req-001"
}
```

**2) 开始处理**

```json
{
  "type": "job_status",
  "job_id": "abc123...",
  "status": "processing",
  "request_id": "req-001"
}
```

**3) 进度更新（每个推理步骤）**

```json
{
  "type": "job_progress",
  "job_id": "abc123...",
  "progress": {
    "stage": "generating",
    "percentage": 44,
    "current_step": 4,
    "total_steps": 9,
    "elapsed": "00:15",
    "remaining": "00:18",
    "speed": "3.75s/it",
    "type": "progress"
  }
}
```

**4) 图片已生成（超分辨率处理前）**

```json
{
  "type": "job_status",
  "job_id": "abc123...",
  "status": "generated",
  "result": {
    "filename": "20260204-a-cute-cat-wearing-sunglasses-abc12345.png",
    "local_path": "outputs/20260204-a-cute-cat-wearing-sunglasses-abc12345.png"
  },
  "request_id": "req-001"
}
```

**5) 任务完成（包含超分辨率图片）**

```json
{
  "type": "job_status",
  "job_id": "abc123...",
  "status": "completed",
  "result": {
    "filename": "20260204-a-cute-cat-wearing-sunglasses-abc12345.png",
    "path": "outputs/20260204-a-cute-cat-wearing-sunglasses-abc12345.png",
    "upscaled_filename": "20260204-a-cute-cat-wearing-sunglasses-abc12345-upscaled.png"
  },
  "request_id": "req-001"
}
```

### 第四步：获取图片

```
GET http://localhost:8004/api/image/20260204-a-cute-cat-wearing-sunglasses-abc12345-upscaled.png
```

---

### 完整 JavaScript 示例

```javascript
const ws = new WebSocket("ws://localhost:8004/api/ws?client_id=my-client-001");

ws.onopen = () => {
  ws.send(JSON.stringify({
    type: "create_job",
    task_type: "text_to_image",
    request_id: "req-001",
    params: {
      prompt: "a cute cat wearing sunglasses, digital art",
      width: 1024,
      height: 1024,
      steps: 9,
      guidance_scale: 0.0,
      seed: 42
    }
  }));
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  switch (msg.type) {
    case "job_status":
      console.log(`[${msg.status}]`, msg.job_id);
      if (msg.status === "completed") {
        const filename = msg.result.upscaled_filename || msg.result.filename;
        console.log(`图片就绪: http://localhost:8004/api/image/${filename}`);
      }
      break;

    case "job_progress":
      console.log(`进度: ${msg.progress.percentage}% (${msg.progress.current_step}/${msg.progress.total_steps})`);
      break;

    case "error":
      console.error("错误:", msg.message);
      break;
  }
};
```

---

## 其他 WebSocket 消息

### 查询任务状态

```json
{
  "type": "get_status",
  "job_id": "abc123...",
  "request_id": "req-002"
}
```

### 取消任务

```json
{
  "type": "cancel_job",
  "job_id": "abc123...",
  "request_id": "req-003"
}

```

仅 `pending` 或 `processing` 状态的任务可以被取消。

### 获取客户端所有任务

```json
{
  "type": "get_client_jobs",
  "request_id": "req-004"
}
```

需要在 WebSocket 连接时设置 `client_id`。返回：

```json
{
  "type": "client_jobs",
  "jobs": [
    {
      "job_id": "abc123...",
      "task_type": "text_to_image",
      "status": "completed",
      "created_at": 1738627200.0,
      "result": { "filename": "...", "path": "...", "upscaled_filename": "..." }
    }
  ],
  "request_id": "req-004"
}
```

---

## 任务状态流转

```
pending → processing → generated → completed
                    ↘ cancelled
                    ↘ failed
```

| 状态 | 说明 |
|---|---|
| `pending` | 已入队，等待执行 |
| `processing` | GPU 正在生成图片 |
| `generated` | 图片已保存，超分辨率处理中 |
| `completed` | 完成（原图 + 超分辨率图片可用） |
| `failed` | 执行出错 |
| `cancelled` | 已被客户端取消 |

## 关键特性

- **去重**：相同参数会生成相同的 `job_id`（SHA-256 哈希）。重复请求会返回已有任务的状态，而不是创建新任务。
- **缓存**：已完成的结果会被缓存。使用相同参数再次请求时会立即返回缓存结果。
- **断线重连**：使用 `client_id` 时，订阅关系在 WebSocket 断开后依然保持。使用相同的 `client_id` 重连后调用 `get_client_jobs` 即可恢复。
- **并发控制**：GPU 操作通过锁串行化执行。最多 4 个任务可同时处理（I/O 操作并行执行）。
