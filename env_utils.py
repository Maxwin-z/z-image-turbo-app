import platform

def is_macos():
    """Detect if the current operating system is macOS."""
    return platform.system() == "Darwin"

IS_MACOS = is_macos()
