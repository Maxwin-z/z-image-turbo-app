from job_system.base_job import BaseJob
import hashlib
import json
import os
from t2i_model import t2i_model
from slugify import slugify
from datetime import datetime
from job_system.registry import JobStatus
from job_system.resources import gpu_lock
import asyncio

class TextToImageJob(BaseJob):
    """
    Job for generating images from text prompts.
    """
    
    def generate_job_id(self, params):
        """
        Generate a unique job ID based on sorted parameters.
        """
        # Create a deterministic string representation of params
        # Sort keys to ensure consistent order
        param_str = json.dumps(params, sort_keys=True)
        return hashlib.sha256(param_str.encode("utf-8")).hexdigest()
        
    async def execute(self):
        """
        Execute the text-to-image generation.
        """
        prompt = self.params.get("prompt")
        if not prompt:
             raise ValueError("Missing 'prompt' in parameters")
             
        width = self.params.get("width", 1024)
        height = self.params.get("height", 1024)
        steps = self.params.get("steps", 9)
        guidance_scale = self.params.get("guidance_scale", 0.0)
        seed = self.params.get("seed", 42)
        model_type = self.params.get("model_type", "uint4")
        
        loop = asyncio.get_running_loop()
        
        filename = ""
        output_path = ""
        upscaled_filename = ""
        
        # --- GPU Phase (Critical Section) ---
        async with gpu_lock:
            # Broadcast state
            if self.on_progress:
                self.on_progress({"stage": "generating", "percent": 0})
                
            def _generate():
                return t2i_model.generate_image(
                    prompt=prompt,
                    width=width,
                    height=height,
                    num_inference_steps=steps,
                    guidance_scale=guidance_scale,
                    seed=seed,
                    progress_callback=self.on_progress,
                    job_id=self.job_id,
                    model_type=model_type
                )
            
            # Generate Image (Blocks GPU)
            image = await loop.run_in_executor(None, _generate)
            
            # Save original output (Local IO)
            output_dir = "outputs"
            os.makedirs(output_dir, exist_ok=True)
            
            date_str = datetime.now().strftime("%Y%m%d")
            slug_name = slugify(prompt)[:32]
            filename = f"{date_str}-{slug_name}-{self.job_id[:8]}.png"
            output_path = os.path.join(output_dir, filename)
            
            image.save(output_path)
            
            # 1. Notify client: Generated locally
            self.update_status(JobStatus.GENERATED.value, {
                "filename": filename,
                "local_path": output_path
            })
            
            # 2. Execute Magnification (Upscaling) - Still holding GPU lock
            upscaled_image = None
            upscaled_output_path = ""
            
            try:
                # Unload T2I model to free VRAM for upscaler if needed
                await loop.run_in_executor(None, t2i_model.unload_model)
                
                from upscaler import upscaler
                
                if self.on_progress:
                    self.on_progress({"stage": "upscaling", "percent": 0})
                
                def _upscale():
                    return upscaler.upscale_image(image)
                    
                upscaled_image = await loop.run_in_executor(None, _upscale)
                
                if upscaled_image:
                    upscaled_filename = f"{date_str}-{slug_name}-{self.job_id[:8]}-upscaled.png"
                    upscaled_output_path = os.path.join(output_dir, upscaled_filename)
                    upscaled_image.save(upscaled_output_path)
            except Exception as e:
                print(f"Upscaling failed: {e}")
                # Don't fail the whole job if upscaling fails

        # --- End of GPU Critical Section ---
        # GPU is now free for the next job.
        
        # Return result with filenames (no OSS upload)
        return {
            "filename": filename,
            "path": output_path,
            "upscaled_filename": upscaled_filename if upscaled_filename else None
        }
