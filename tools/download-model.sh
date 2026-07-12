#!/usr/bin/env bash
# 下载本地向量模型 BAAI/bge-small-zh-v1.5（fastembed ONNX 版，约 90MB 压缩包）。
# 模型不入 git 仓库（见 .gitignore），克隆后跑一次本脚本即可。
# 来源：qdrant-fastembed 官方 GCS 镜像（与 fastembed 库自动下载的同源，国内可直连）。
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)/data/models"
TARBALL="fast-bge-small-zh-v1.5.tar.gz"
URL="https://storage.googleapis.com/qdrant-fastembed/${TARBALL}"

if [ -f "$DIR/fast-bge-small-zh-v1.5/model_optimized.onnx" ]; then
    echo "✓ 模型已存在：$DIR/fast-bge-small-zh-v1.5/"
    exit 0
fi

mkdir -p "$DIR"
echo "→ 下载 $URL"
curl -L --progress-bar -o "$DIR/$TARBALL" "$URL"
tar -xzf "$DIR/$TARBALL" -C "$DIR"
echo "✓ 模型就绪：$DIR/fast-bge-small-zh-v1.5/（512维中文语义向量，全程离线推理）"
