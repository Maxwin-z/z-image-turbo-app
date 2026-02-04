import os
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

import torch
import diffusers
from sdnq import SDNQConfig # import sdnq to register it into diffusers and transformers
from sdnq.loader import apply_sdnq_options_to_model
from slugify import slugify
from datetime import datetime
import time

pipe = diffusers.ZImagePipeline.from_pretrained("Disty0/Z-Image-Turbo-SDNQ-uint4-svd-r32", torch_dtype=torch.float32)
pipe.enable_model_cpu_offload()
pipe.transformer = apply_sdnq_options_to_model(pipe.transformer, use_quantized_matmul=False)
pipe.text_encoder = apply_sdnq_options_to_model(pipe.text_encoder, use_quantized_matmul=False)

prompts = [
    "一位男士和他的贵宾犬穿着配套的服装参加狗狗秀，室内灯光，背景中有观众。",
    "一只猫坐在窗台上看着外面的雨，由于是在室内，光线柔和舒适。",
    "未来城市的赛博朋克街道，霓虹灯闪烁，飞行汽车穿梭其中。",
    "夕阳下的海滩，海浪轻轻拍打着沙滩，远处有几只海鸥。"
]

output_dir = "outputs"
os.makedirs(output_dir, exist_ok=True)
date_str = datetime.now().strftime("%Y%m%d")

for i, prompt in enumerate(prompts):
    print(f"Generating image {i+1}/{len(prompts)} for prompt: {prompt[:20]}...")
    
    start_time = time.time()
    image = pipe(
        prompt=prompt,
        height=1024,
        width=1024,
        num_inference_steps=9,
        guidance_scale=0.0,
        generator=torch.manual_seed(42),
    ).images[0]
    end_time = time.time()
    
    duration = end_time - start_time
    print(f"Generation time: {duration:.2f} seconds")
    
    slug_name = slugify(prompt)[:32]
    filename = f"{date_str}-{slug_name}.png"
    output_path = os.path.join(output_dir, filename)
    image.save(output_path)
    print(f"Saved to {output_path}\n")