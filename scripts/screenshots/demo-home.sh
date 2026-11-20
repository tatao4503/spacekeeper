#!/bin/bash
# README 스크린샷용 가짜 홈(/Users/Shared/demo). 실제 사용자 경로가 찍히지 않게 한다.
# 큰 파일은 APFS 클론(cp -c)이라 화면에는 각자 크기로 잡히지만 실제로는 ~2GB만 쓴다.
# 다 찍은 뒤: rm -rf /Users/Shared/demo
set -euo pipefail
H=/Users/Shared/demo
rm -rf "$H"; mkdir -p "$H/.base"; cd "$H/.base"
for spec in a:900 b:600 c:300 d:120 e:40; do
  dd if=/dev/urandom of="${spec%%:*}" bs=1m count="${spec##*:}" status=none
done
cl() { mkdir -p "$(dirname "$2")"; cp -c "$H/.base/$1" "$2"; }
cl a "$H/Downloads/Lecture-recording-2025-03.mov"
cl b "$H/Downloads/Photos-backup-2024.zip"
cl c "$H/Downloads/Figma-125.4.dmg"
cl d "$H/Downloads/Zoom-installer.pkg"
cl e "$H/Downloads/fonts-pack.zip"
touch -t 202503100900 "$H"/Downloads/*
mkdir -p "$H/Developer/web-app" "$H/Developer/blog"
echo '{"name":"web-app"}' > "$H/Developer/web-app/package.json"
echo '{"name":"blog"}' > "$H/Developer/blog/package.json"
cl b "$H/Developer/web-app/node_modules/@next/swc-darwin-arm64/next-swc.node"
cl d "$H/Developer/web-app/node_modules/typescript/lib/typescript.js"
cl c "$H/Developer/web-app/.next/cache/webpack/client-production/0.pack"
cl d "$H/Developer/blog/node_modules/esbuild/bin/esbuild"
cl a "$H/Library/Developer/Xcode/DerivedData/Notes-abcdefg/Build/Intermediates.noindex/x.o"
cl c "$H/Library/Caches/Homebrew/downloads/llvm--21.1.8.bottle.tar.gz"
cl d "$H/Library/Caches/pip/http/x.whl"
cl c "$H/.gradle/caches/modules-2/files-2.1/x.jar"
cl e "$H/Documents/Thesis-final.pdf"
cl e "$H/Documents/Thesis-final copy.pdf"
cl e "$H/Desktop/Thesis-final.pdf"
mkdir -p "$H/Pictures" "$H/Music"
cl a "$H/Movies/Trip-4K.mov"
rm -rf "$H/.base"
echo "가짜 홈 준비: $H"
