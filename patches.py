
import sys
import logging
import types

logger = logging.getLogger(__name__)

def apply_patches():
    """
    Apply runtime patches to fix dependency issues.
    """
    # Patch 1: Basicsr compatibility with newer torchvision
    # Basicsr tries to import 'functional_tensor' which was removed in torchvision 0.18+
    try:
        import torchvision.transforms.functional
        
        target_module_name = "torchvision.transforms.functional_tensor"
        if target_module_name not in sys.modules:
            logger.info(f"Patching {target_module_name} for basicsr compatibility...")
            mock_module = types.ModuleType(target_module_name)
            mock_module.rgb_to_grayscale = torchvision.transforms.functional.rgb_to_grayscale
            sys.modules[target_module_name] = mock_module
            
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Failed to apply basicsr patch: {e}")

# Apply immediately on import
apply_patches()
