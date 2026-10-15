#!/usr/bin/env bash
# 下载排版用的三种开源字体（SIL OFL）到 fonts/。字体不进仓库；第一次用之前跑一次。
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p fonts
get() {  # get <文件名> <地址>
  if [ -s "fonts/$1" ] && [ "$(stat -c %s "fonts/$1" 2>/dev/null || stat -f %z "fonts/$1")" -gt 1000000 ]; then
    echo "已有 fonts/$1"; return
  fi
  echo "下载 $1 …"
  curl -fL --retry 3 -o "fonts/$1.part" "$2" && mv "fonts/$1.part" "fonts/$1"
}
get 'NotoSerifSC[wght].ttf' 'https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifsc/NotoSerifSC%5Bwght%5D.ttf'
get 'NotoSansSC[wght].ttf'  'https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf'
get 'LXGWWenKai-Regular.ttf' 'https://github.com/lxgw/LxgwWenKai/releases/latest/download/LXGWWenKai-Regular.ttf'
ls -la fonts/
