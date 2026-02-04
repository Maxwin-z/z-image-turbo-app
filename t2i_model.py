import os
import torch
import diffusers
from sdnq import SDNQConfig
from sdnq.loader import apply_sdnq_options_to_model
import logging
import time
from env_utils import IS_MACOS

import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def parse_tqdm_log(log_line):
    """
    Parses a tqdm log line into a dictionary of progress data.
    Example: "  5% 1/20 [00:22<07:12, 22.74s/it]"
    """
    pattern = r"\s*(\d+)%\s+(\d+)/(\d+)\s+\[([\d:]+)<([\d:]+),\s+([\d.]+s/it)\]"
    match = re.search(pattern, log_line)
    if match:
        return {
            "percentage": int(match.group(1)),
            "current_step": int(match.group(2)),
            "total_steps": int(match.group(3)),
            "elapsed": match.group(4),
            "remaining": match.group(5),
            "speed": match.group(6)
        }
    return None

# Ensure MPS fallback is enabled only on macOS
if IS_MACOS:
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    logger.info("Running on macOS configuration")
else:
    logger.info("Running on non-macOS configuration (Colab/T4)")

class T2IModel:
    _instance = None
    _pipe = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = T2IModel()
        return cls._instance

    def __init__(self):
        self._current_model_type = None
        self._pipe = None

    def load_model(self, model_type="uint4"):
        if self._current_model_type == model_type and self._pipe is not None:
            return

        logger.info(f"Switching model to {model_type}...")
        
        # Unload existing model if any
    def unload_model(self):
        if self._pipe is not None:
            logger.info("Unloading current model...")
            # Delete components explicitly to free memory
            if hasattr(self._pipe, 'transformer'):
                del self._pipe.transformer
            if hasattr(self._pipe, 'text_encoder'):
                del self._pipe.text_encoder
            del self._pipe
            self._pipe = None
            self._current_model_type = None
            
            import gc
            gc.collect()
            torch.cuda.empty_cache()
            if torch.cuda.is_available():
                torch.cuda.synchronize()

    def load_model(self, model_type="uint4"):
        if self._current_model_type == model_type and self._pipe is not None:
            return

        logger.info(f"Switching model to {model_type}...")
        
        # Unload existing model if any
        self.unload_model()

        try:
            # Environment-specific settings
            if IS_MACOS:
                torch_dtype = torch.float32
                device_map = None
                use_quantized_matmul = False # Keep safe default for Mac
            else:
                # Parameters for Colab T4
                torch_dtype = torch.float32
                device_map = "cuda"
                use_quantized_matmul = True

            model_id = "Disty0/Z-Image-Turbo-SDNQ-uint4-svd-r32"
            if model_type == "int8":
                model_id = "Disty0/Z-Image-Turbo-SDNQ-int8"

            logger.info(f"Loading model: {model_id}")

            # Load pipeline
            self._pipe = diffusers.ZImagePipeline.from_pretrained(
                model_id, 
                torch_dtype=torch_dtype,
                device_map=device_map
            )

            if IS_MACOS:
                # For macOS, model cpu offload is often better for handled shared memory
                self._pipe.enable_model_cpu_offload()
            
            # Apply SDNQ options
            self._pipe.transformer = apply_sdnq_options_to_model(
                self._pipe.transformer, 
                use_quantized_matmul=use_quantized_matmul
            )
            self._pipe.text_encoder = apply_sdnq_options_to_model(
                self._pipe.text_encoder, 
                use_quantized_matmul=use_quantized_matmul
            )
            
            self._current_model_type = model_type
            logger.info(f"T2I model {model_type} loaded successfully with {torch_dtype} (quantized_matmul={use_quantized_matmul})")
            
        except Exception as e:
            logger.error(f"Failed to load T2I model: {e}")
            self._current_model_type = None
            self._pipe = None
            raise

    def generate_image(self, prompt, width=1024, height=1024, num_inference_steps=9, guidance_scale=0.0, seed=None, progress_callback=None, job_id=None, model_type="uint4"):
        # Ensure correct model is loaded
        self.load_model(model_type)
        
        logger.info(f"Generating image for prompt: {prompt[:50]}... (Model: {model_type})")
        
        generator = None
        if seed is not None:
            generator = torch.manual_seed(seed)
        else:
            # Use random seed if none provided
            generator = torch.manual_seed(torch.randint(0, 1000000, (1,)).item())

        start_time = time.time()

        def diffusion_callback(pipe, step, timestep, callback_kwargs):
            # Check for cancellation
            if job_id:
                from job_system import JobRegistry
                if JobRegistry.is_cancelled(job_id):
                    raise Exception("Job cancelled by user")

            if progress_callback:
                current_step = step + 1
                percentage = int((current_step / num_inference_steps) * 100)
                
                elapsed = time.time() - start_time
                speed = elapsed / current_step if current_step > 0 else 0
                remaining = speed * (num_inference_steps - current_step)
                
                # Format times like tqdm (MM:SS)
                def format_time(seconds):
                    m, s = divmod(int(seconds), 60)
                    return f"{m:02d}:{s:02d}"

                progress_callback({
                    "percentage": min(percentage, 100),
                    "current_step": current_step,
                    "total_steps": num_inference_steps,
                    "elapsed": format_time(elapsed),
                    "remaining": format_time(remaining),
                    "speed": f"{speed:.2f}s/it",
                    "type": "progress"
                })
            return callback_kwargs

        image = self._pipe(
            prompt=prompt,
            height=height,
            width=width,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            generator=generator,
            callback_on_step_end=diffusion_callback,
            callback_on_step_end_tensor_inputs=["latents"]
        ).images[0]
        
        return image

# Singleton access
t2i_model = T2IModel.get_instance()
