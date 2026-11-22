#!/bin/sh
# Deterministic package sets only. No user supplied package names are accepted.
set -eu
maizo_select_packages() {
 maizo_selected=''
 for maizo_candidate in $maizo_packages; do
  case "$maizo_candidate" in samba|smbclient|samba-client) if [ "${MAIZONAS_ISOLATED:-0}" = 1 ]; then continue;fi;; esac
  maizo_selected="$maizo_selected $maizo_candidate"
 done
 maizo_packages=$maizo_selected
}
maizo_role=${1:---runtime}
case "$maizo_role" in --runtime|--build|--host|--repair) ;; *) echo 'Papel de instalação inválido'; exit 2;; esac
if [ "$maizo_role" = --repair ] && [ -f /etc/maizonas/install.env ]; then
 . /etc/maizonas/install.env
 if [ -n "${MAIZONAS_RUNTIME:-}" ]; then
  chroot "$MAIZONAS_RUNTIME" /usr/bin/env MAIZONAS_ISOLATED=1 /opt/maizonas/scripts/dependencies.sh --runtime
  /opt/maizonas/scripts/dependencies.sh --host
 else /opt/maizonas/scripts/dependencies.sh --runtime; fi
 exit 0
fi
if command -v apt-get >/dev/null; then
 export DEBIAN_FRONTEND=noninteractive
 apt-get update
 case "$maizo_role" in
 --build) maizo_packages='build-essential pkg-config nasm libdvdnav-dev libdvdread-dev libx264-dev libmp3lame-dev libxvidcore-dev';;
 --host) maizo_packages='samba smbclient iproute2 wpasupplicant';;
 *) maizo_packages='python3 python3-pil aria2 p7zip-full ffmpeg lsdvd samba smbclient iproute2 curl ca-certificates';;
 esac
 maizo_select_packages
 apt-get install -y --no-install-recommends $maizo_packages
elif command -v dnf >/dev/null; then
 case "$maizo_role" in
 --build) maizo_packages='gcc make pkgconf-pkg-config nasm libdvdnav-devel libdvdread-devel x264-devel lame-devel xvidcore-devel';;
 --host) maizo_packages='samba samba-client iproute wpa_supplicant';;
 *) maizo_packages='python3 python3-pillow aria2 7zip ffmpeg-free lsdvd samba samba-client iproute curl ca-certificates';;
 esac
 maizo_select_packages
 dnf install -y $maizo_packages
elif command -v pacman >/dev/null; then
 case "$maizo_role" in
 --build) maizo_packages='base-devel pkgconf nasm libdvdnav libdvdread x264 lame xvidcore';;
 --host) maizo_packages='samba iproute2 wpa_supplicant';;
 *) maizo_packages='python python-pillow aria2 7zip ffmpeg lsdvd samba iproute2 curl ca-certificates';;
 esac
 maizo_select_packages
 pacman -Sy --needed --noconfirm $maizo_packages
elif command -v zypper >/dev/null; then
 case "$maizo_role" in
 --build) maizo_packages='gcc make pkgconf-pkg-config nasm libdvdnav-devel libdvdread-devel libx264-devel libmp3lame-devel libxvidcore-devel';;
 --host) maizo_packages='samba samba-client iproute2 wpa_supplicant';;
 *) maizo_packages='python3 python3-Pillow aria2 7zip ffmpeg lsdvd samba samba-client iproute2 curl ca-certificates';;
 esac
 maizo_select_packages
 zypper --non-interactive install $maizo_packages
elif command -v apk >/dev/null; then
 case "$maizo_role" in
 --build) maizo_packages='build-base pkgconf nasm libdvdnav-dev libdvdread-dev x264-dev lame-dev xvidcore-dev';;
 --host) maizo_packages='samba samba-client iproute2 wpa_supplicant';;
 *) maizo_packages='python3 py3-pillow aria2 7zip ffmpeg lsdvd samba samba-client iproute2 curl ca-certificates';;
 esac
 maizo_select_packages
 apk add --no-cache $maizo_packages
elif command -v tazpkg >/dev/null; then
 # Python/media tools use the isolated runtime on SliTaz. Never replace libc.
 for maizo_package in samba smbclient wpa_supplicant; do
  case "$maizo_package" in samba) command -v smbd >/dev/null && continue;; smbclient) command -v smbclient >/dev/null && continue;; wpa_supplicant) command -v wpa_supplicant >/dev/null && continue;; esac
  tazpkg get-install "$maizo_package" --forced
 done
else
 echo 'Gerenciador não reconhecido. Suportados: apt-get, dnf, pacman, zypper, apk e tazpkg.' >&2
 exit 1
fi
# Distributions have alternative 7-Zip executable names.
if ! command -v 7z >/dev/null && command -v 7zz >/dev/null; then
 mkdir -p /usr/local/bin
 ln -s "$(command -v 7zz)" /usr/local/bin/7z
fi
