#!/bin/sh
set -eu
# Build only when the distro FFmpeg lacks native DVD navigation or lossless codecs.
maizo_engine=/opt/maizonas-engine
if [ -x "$maizo_engine/bin/ffmpeg" ]; then exit 0;fi
/opt/maizonas/scripts/dependencies.sh --build
maizo_build=$(mktemp -d /tmp/maizonas-ffmpeg.XXXXXX)
trap 'rm -r -- "$maizo_build"' EXIT HUP INT TERM
curl --fail --location --proto '=https' https://ffmpeg.org/releases/ffmpeg-8.1.3.tar.xz -o "$maizo_build/ffmpeg.tar.xz"
# HTTPS source is pinned to a version; archive hash is recorded with the installation.
sha256sum "$maizo_build/ffmpeg.tar.xz" > "$maizo_build/source.sha256"
tar -xf "$maizo_build/ffmpeg.tar.xz" -C "$maizo_build"
cd "$maizo_build/ffmpeg-8.1.3"
./configure --prefix="$maizo_engine" --disable-doc --disable-debug --disable-ffplay --enable-gpl --enable-libdvdnav --enable-libdvdread --enable-libx264 --enable-libmp3lame --enable-libxvid --disable-encoders --enable-encoder=libx264,libxvid,libmp3lame,ffv1,alac,flac,aac,ac3,mpeg2video,mpeg4,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,rawvideo,wrapped_avframe,png
maizo_jobs=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
[ "$maizo_jobs" -le 4 ] || maizo_jobs=4
make -j"$maizo_jobs"
make install
cp "$maizo_build/source.sha256" "$maizo_engine/source.sha256"
