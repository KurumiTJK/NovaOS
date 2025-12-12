#!/usr/bin/env python3
# setup_council.py
"""
Nova Council — Installation Script

Usage:
    python setup_council.py /path/to/nova-os
    
This script:
1. Copies council and providers directories to NovaOS
2. Creates __init__.py files if missing
3. Shows patch instructions
"""

import os
import sys
import shutil
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("Usage: python setup_council.py /path/to/nova-os")
        print("")
        print("This script copies Nova Council files to your NovaOS installation.")
        sys.exit(1)
    
    novaos_path = Path(sys.argv[1]).resolve()
    
    if not novaos_path.exists():
        print(f"Error: Path does not exist: {novaos_path}")
        sys.exit(1)
    
    # Check for NovaOS indicators
    indicators = ["nova_api.py", "kernel", "backend"]
    found = [i for i in indicators if (novaos_path / i).exists()]
    
    if len(found) < 2:
        print(f"Warning: {novaos_path} doesn't look like a NovaOS directory")
        print(f"  Found: {found}")
        print(f"  Expected: {indicators}")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            sys.exit(1)
    
    # Get source directory
    source_dir = Path(__file__).parent
    
    # Copy directories
    dirs_to_copy = ["council", "providers"]
    
    for dir_name in dirs_to_copy:
        src = source_dir / dir_name
        dst = novaos_path / dir_name
        
        if not src.exists():
            print(f"Warning: Source directory not found: {src}")
            continue
        
        if dst.exists():
            print(f"Directory exists: {dst}")
            response = input(f"  Overwrite? (y/N): ")
            if response.lower() == 'y':
                shutil.rmtree(dst)
            else:
                print(f"  Skipping {dir_name}")
                continue
        
        shutil.copytree(src, dst)
        print(f"Copied: {dir_name}/ -> {dst}")
    
    # Check for .env
    env_file = novaos_path / ".env"
    if env_file.exists():
        with open(env_file, 'r') as f:
            content = f.read()
        
        if 'GEMINI_API_KEY' not in content:
            print("")
            print("Note: GEMINI_API_KEY not found in .env")
            print("Add the following to your .env file:")
            print("")
            print("  GEMINI_API_KEY=your-api-key-here")
            print("  GEMINI_ENABLED=true")
    else:
        print("")
        print("Note: .env file not found")
        print("Create .env with:")
        print("")
        print("  GEMINI_API_KEY=your-api-key-here")
        print("  GEMINI_ENABLED=true")
    
    # Print patch instructions
    print("")
    print("=" * 60)
    print("NEXT STEPS: Apply patches to existing files")
    print("=" * 60)
    print("")
    print("You need to manually apply these patches:")
    print("")
    print("1. kernel/dashboard_handlers.py")
    print("   See: patches/patch_dashboard_handlers.py")
    print("")
    print("2. core/mode_router.py")
    print("   See: patches/patch_mode_router.py")
    print("")
    print("3. nova_api.py")
    print("   See: patches/patch_nova_api.py")
    print("")
    print("Each patch file contains detailed instructions.")
    print("")
    print("4. Install dependencies:")
    print("   pip install google-generativeai --break-system-packages")
    print("")
    print("5. Run tests:")
    print("   python -m pytest tests/test_council.py -v")
    print("")
    print("Done!")


if __name__ == "__main__":
    main()
