#!/usr/bin/env python3
"""
SEED-RECOVERY Electrum 2 - GPU-accelerated seed recovery
Wallet: 16RGFo6hjq9ym6Pj7N5H7L1NR1rVPJyw2v
Seed: 12-word Electrum 2 English
"""

import subprocess
import sys
import json
import os
from datetime import datetime
from pathlib import Path

WALLET_ADDRESS = "16RGFo6hjq9ym6Pj7N5H7L1NR1rVPJyw2v"
PUBLIC_KEY = "02145d2611c823a396ef6712ce0f712f09b9b4f3135e3e0aa3230fb9b6d08d1e16"
SEED_LENGTH = "12"
WALLET_TYPE = "electrum2"
LANGUAGE = "english"

BASE_DIR = Path("/app/recovery")
WORDLIST = BASE_DIR / "electrum_wordlist.txt"
ADDRESSLIST = BASE_DIR / "addresslist.txt"
LOG_DIR = Path("/app/logs")
LOG_FILE = LOG_DIR / f"recovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

LOG_DIR.mkdir(parents=True, exist_ok=True)

def log_msg(msg):
    """Print and log message"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {msg}"
    print(log_line)
    with open(LOG_FILE, "a") as f:
        f.write(log_line + "\n")

def verify_files():
    """Verify all required files exist"""
    log_msg("Verifying required files...")
    
    required_files = {
        WORDLIST: "Electrum wordlist",
        ADDRESSLIST: "Address list"
    }
    
    for file_path, description in required_files.items():
        if file_path.exists():
            size = file_path.stat().st_size
            log_msg(f"  ✓ {description}: {file_path} ({size} bytes)")
        else:
            log_msg(f"  ✗ ERROR: Missing {description}: {file_path}")
            return False
    
    return True

def count_words():
    """Count words in wordlist"""
    with open(WORDLIST, "r") as f:
        words = [w.strip() for w in f if w.strip()]
    return len(words)

def run_recovery():
    """Run the actual recovery"""
    log_msg("")
    log_msg("="*60)
    log_msg("Starting Electrum 2 Seed Recovery")
    log_msg("="*60)
    log_msg(f"Wallet Address: {WALLET_ADDRESS}")
    log_msg(f"Seed Length: {SEED_LENGTH} words")
    log_msg(f"Wallet Type: {WALLET_TYPE}")
    log_msg(f"Language: {LANGUAGE}")
    log_msg(f"Wordlist: {count_words()} words")
    log_msg(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_msg("="*60)
    log_msg("")
    
    # Build command
    cmd = [
        "python3",
        "/opt/btcrecover/seedrecover.py",
        "--wallet-type", WALLET_TYPE,
        "--seed-language", LANGUAGE,
        "--address", WALLET_ADDRESS,
        "--addresslist", str(ADDRESSLIST),
        "--passwordlist", str(WORDLIST),
    ]
    
    log_msg(f"Running: {' '.join(cmd)}")
    log_msg("")
    log_msg("Recovery in progress... (this may take several hours)")
    log_msg("")
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        for line in process.stdout:
            line = line.rstrip()
            print(line)
            
            with open(LOG_FILE, "a") as f:
                f.write(line + "\n")
            
            if "Seed found" in line or "seed found" in line.lower():
                log_msg("")
                log_msg("🎉 SEED FOUND! 🎉")
                log_msg("")
        
        process.wait()
        
        log_msg("")
        log_msg("="*60)
        log_msg(f"Recovery completed (exit code: {process.returncode})")
        log_msg(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log_msg("="*60)
        log_msg("")
        
        return process.returncode == 0
    
    except Exception as e:
        log_msg(f"❌ ERROR: {e}")
        return False

def main():
    """Main entry point"""
    try:
        log_msg("Seed Recovery System Starting...")
        log_msg(f"Log file: {LOG_FILE}")
        log_msg("")
        
        if not verify_files():
            log_msg("❌ File verification failed")
            sys.exit(1)
        
        success = run_recovery()
        sys.exit(0 if success else 1)
    
    except Exception as e:
        log_msg(f"❌ FATAL ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()