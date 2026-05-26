#!/bin/bash

# SEED-RECOVERY vastai.ai GPU Deployment Launcher
# For: 16RGFo6hjq9ym6Pj7N5H7L1NR1rVPJyw2v (Electrum 2, 12-word)
# Auto-launches recovery on vast.ai GPU

set -e

echo "========================================"
echo "SEED-RECOVERY vastai.ai Launcher"
echo "========================================"
echo ""
echo "Wallet: 16RGFo6hjq9ym6Pj7N5H7L1NR1rVPJyw2v"
echo "Seed Type: Electrum 2, 12-word English"
echo "Recovery Method: MPK-based validation"
echo ""

# Step 1: Check vast CLI installed
echo "[1/6] Checking vast.ai CLI..."
if ! command -v vast &> /dev/null; then
    echo "vast.ai CLI not found. Installing..."
    pip install vast-ai
fi

# Step 2: Authenticate
echo "[2/6] Authenticating with vast.ai..."
read -p "Enter your vast.ai API Key: " API_KEY
vast set apikey "$API_KEY"
vast show user || { echo "Authentication failed!"; exit 1; }

# Step 3: Check Docker
echo "[3/6] Checking Docker..."
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker not installed. Please install Docker first."
    exit 1
fi

# Step 4: Build Docker image
echo "[4/6] Building Docker image (this may take 2-3 minutes)..."
docker build -t seed-recovery-electrum2:latest . \
  -f Dockerfile.vastai \
  --build-arg WALLET_ADDRESS="16RGFo6hjq9ym6Pj7N5H7L1NR1rVPJyw2v" \
  --build-arg PUBLIC_KEY="02145d2611c823a396ef6712ce0f712f09b9b4f3135e3e0aa3230fb9b6d08d1e16"

# Step 5: Search for GPU
echo "[5/6] Searching for available GPUs on vast.ai..."
echo "Looking for RTX 3090, A100, or A6000..."

# Search for RTX 3090 (best value)
GPU_OFFER=$(vast search offers 'gpu_name in [RTX_3090] and cuda_vers >= 11.8 and reliability >= 0.95' --raw | head -1 | jq -r '.id')

if [ -z "$GPU_OFFER" ] || [ "$GPU_OFFER" == "null" ]; then
    echo "RTX 3090 not available, trying A100..."
    GPU_OFFER=$(vast search offers 'gpu_name in [A100] and cuda_vers >= 11.8 and reliability >= 0.95' --raw | head -1 | jq -r '.id')
fi

if [ -z "$GPU_OFFER" ] || [ "$GPU_OFFER" == "null" ]; then
    echo "ERROR: No suitable GPU found. Please check vast.ai availability and account balance."
    exit 1
fi

echo "Found GPU offer ID: $GPU_OFFER"

# Step 6: Launch instance
echo "[6/6] Launching recovery instance..."
echo ""
echo "⏳ Starting GPU instance (this takes 1-2 minutes)..."

INSTANCE=$(vast create instance "$GPU_OFFER" \
  --image seed-recovery-electrum2:latest \
  --disk 50 \
  --label "seed-recovery-electrum2" \
  --on-demand \
  2>&1 | grep -oP 'new instance id: \K[0-9]+')

if [ -z "$INSTANCE" ]; then
    echo "ERROR: Failed to create instance"
    exit 1
fi

echo "✅ Instance created: $INSTANCE"
echo ""
echo "========================================"
echo "🚀 RECOVERY STARTED!"
echo "========================================"
echo ""
echo "Instance ID: $INSTANCE"
echo "Status: Starting (takes 1-2 minutes to boot)"
echo ""
echo "Monitor recovery progress:"
echo "  vast show instance $INSTANCE"
echo ""
echo "Get instance logs:"
echo "  vast logs $INSTANCE"
echo ""
echo "SSH into instance (once running):"
echo "  vast ssh $INSTANCE"
echo ""
echo "Expected recovery time: 12-48 hours"
echo "Cost: ~€0.40/hour (RTX 3090)"
echo ""
echo "IMPORTANT: Once seed is found, check logs immediately!"
echo "The seed will appear in the recovery logs."
echo "========================================"
echo ""