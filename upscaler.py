
import os
import torch
from PIL import Image
import patches # Apply runtime patches for basicsr
from realesrgan import RealESRGANer
from basicsr.archs.rrdbnet_arch import RRDBNet
import logging

logger = logging.getLogger(__name__)

class Upscaler:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = Upscaler()
        return cls._instance

    def __init__(self):
        self.model = None
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'mps' if torch.backends.mps.is_available() else 'cpu')
        
    def load_model(self):
        if self.model is not None:
            return

        logger.info(f"Loading Real-ESRGAN model on {self.device}...")
        try:
            # simple usage with default model
            # We use RealESRGAN_x4plus
            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
            # RealESRGANer will download weights automatically if not present
            self.model = RealESRGANer(
                scale=4,
                model_path='https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
                model=model,
                tile=512,  # Use tiling to avoid OOM
                tile_pad=10,
                pre_pad=0,
                half=False, # Use fp32 for better compatibility on Mac
                device=self.device,
            )
            logger.info("Real-ESRGAN model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Real-ESRGAN model: {e}")
            raise

    def upscale_image(self, image: Image.Image) -> Image.Image:
        """
        Upscale the image if its dimensions are smaller than 1024x1024.
        Returns the upscaled image, or None if no upscaling was performed.
        """
        w, h = image.size
        min_dim = min(w, h)
        
        if min_dim >= 1024:
            logger.info(f"Image size {w}x{h} is large enough, skipping upscale.")
            return None
            
        logger.info(f"Upscaling image from {w}x{h}...")
        self.load_model()
        
        try:
            # RealESRGANer expects numpy array (cv2 format) usually, but enhance() handles it?
            # actually enhance() takes cv2 image (BGR).
            # We need to convert PIL (RGB) to cv2 (BGR)
            import numpy as np
            import cv2
            
            img_np = np.array(image)
            # Convert RGB to BGR
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            
            # Calculate desired scale to reach 1024 on min dimension
            # We want min(new_w, new_h) = 1024
            # new_w = w * scale
            # new_h = h * scale
            # min(w*scale, h*scale) = scale * min(w, h) = 1024
            # scale = 1024 / min(w, h)
            
            min_dim = min(w, h)
            outscale = 1024 / min_dim
            
            output, _ = self.model.enhance(img_bgr, outscale=outscale)
            
            # output is BGR, convert back to RGB
            output_rgb = cv2.cvtColor(output, cv2.COLOR_BGR2RGB)
            output_pil = Image.fromarray(output_rgb)
            
            # Now we might have upscaled 4x, which could be too huge if input was e.g. 512 -> 2048.
            # The requirement is "upscale to at least 1024".
            # If we just accept the 4x result, it's fine.
            # But maybe we want to resize down if it's excessively large? 
            # User said: "将生成出的图的最小width/height放大到1024px"
            # If we have 512x512 -> 2048x2048. That satisfies ">= 1024".
            # If we have 256x256 -> 1024x1024.
            # So 4x model is good for general use.
            
            logger.info(f"Upscaled to {output_pil.size}")
            return output_pil
            
        except Exception as e:
            logger.error(f"Error during upscaling: {e}")
            return None

upscaler = Upscaler.get_instance()
