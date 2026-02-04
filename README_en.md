# Z-Image-Turbo

High-performance Text-to-Image generation server, based on FastAPI + WebSocket real-time job management system.

- Model: [Z-Image-Turbo-SDNQ](https://huggingface.co/Disty0/Z-Image-Turbo-SDNQ-uint4-svd-r32) (quantized Stable Diffusion)
- Upscaling: Real-ESRGAN x4
## Quick Start

```bash
# Install dependencies and start server
bash start.sh
```

Server runs on `http://0.0.0.0:8004`. API docs available at `/docs`.

## API Reference

### REST Endpoints

#### Health Check

```
GET /api/health
```

Response:

```json
{ "status": "ok" }
```

#### Get Image

```
GET /api/image/{filename}
```

Returns the generated image file (PNG).

---

### WebSocket API

```
WebSocket /api/ws?client_id={client_id}
```

- `client_id` (optional): Client identifier. Subscriptions persist across reconnections with the same `client_id`.

All messages are JSON. Client sends a message with `type` field, server responds with corresponding messages.

---

## How to Generate an Image (End-to-End)

### Step 1: Connect WebSocket

```javascript
const ws = new WebSocket("ws://localhost:8004/api/ws?client_id=my-client-001");
```

### Step 2: Send `create_job` message

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

**params:**

| Field | Type | Default | Description |
|---|---|---|---|
| `prompt` | string | **required** | Text description of the image |
| `width` | int | 1024 | Image width (px) |
| `height` | int | 1024 | Image height (px) |
| `steps` | int | 9 | Inference steps (more = higher quality, slower) |
| `guidance_scale` | float | 0.0 | Classifier-free guidance scale |
| `seed` | int | 42 | Random seed for reproducibility |
| `model_type` | string | "uint4" | Quantization type: `"uint4"` or `"int8"` |

### Step 3: Receive status updates

Server pushes the following messages in order:

**1) Job created**

```json
{
  "type": "job_status",
  "job_id": "abc123...",
  "status": "pending",
  "request_id": "req-001"
}
```

**2) Processing started**

```json
{
  "type": "job_status",
  "job_id": "abc123...",
  "status": "processing",
  "request_id": "req-001"
}
```

**3) Progress updates (per inference step)**

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

**4) Image generated (before upscaling)**

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

**5) Completed (with upscaled image)**

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

### Step 4: Fetch the image

```
GET http://localhost:8004/api/image/20260204-a-cute-cat-wearing-sunglasses-abc12345-upscaled.png
```

---

### Complete JavaScript Example

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
        console.log(`Image ready: http://localhost:8004/api/image/${filename}`);
      }
      break;

    case "job_progress":
      console.log(`Progress: ${msg.progress.percentage}% (${msg.progress.current_step}/${msg.progress.total_steps})`);
      break;

    case "error":
      console.error("Error:", msg.message);
      break;
  }
};
```

---

## Other WebSocket Messages

### Get Job Status

```json
{
  "type": "get_status",
  "job_id": "abc123...",
  "request_id": "req-002"
}
```

### Cancel Job

```json
{
  "type": "cancel_job",
  "job_id": "abc123...",
  "request_id": "req-003"
}

```

Only jobs in `pending` or `processing` status can be cancelled.

### Get All Client Jobs

```json
{
  "type": "get_client_jobs",
  "request_id": "req-004"
}
```

Requires `client_id` to be set during WebSocket connection. Returns:

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

## Job Status Flow

```
pending → processing → generated → completed
                    ↘ cancelled
                    ↘ failed
```

| Status | Description |
|---|---|
| `pending` | Queued, waiting for execution |
| `processing` | GPU is generating the image |
| `generated` | Image saved locally, upscaling in progress |
| `completed` | Done (original + upscaled images available) |
| `failed` | Execution error |
| `cancelled` | Cancelled by client |

## Key Behaviors

- **Deduplication**: Same params produce the same `job_id` (SHA-256 hash). Duplicate requests return existing job status instead of creating a new job.
- **Caching**: Completed results are cached. Re-requesting the same params returns the cached result immediately.
- **Reconnection**: When using `client_id`, subscriptions survive WebSocket disconnections. Reconnect with the same `client_id` and call `get_client_jobs` to resume.
- **Concurrency**: GPU operations are serialized via lock. Up to 4 jobs can be in-flight concurrently (I/O operations run in parallel).
