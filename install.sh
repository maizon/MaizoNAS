#!/bin/sh
# Linux installer, including old-libc SliTaz hosts. No global libc replacement.
set -eu
maizo_source=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
maizo_user=${SUDO_USER:-${USER:-}}
maizo_runtime=''
maizo_skip=0
maizo_start=1
maizo_dvd=1
while [ "$#" -gt 0 ]; do
 case "$1" in
 --user) maizo_user=$2;shift 2;;
 --runtime) maizo_runtime=$2;shift 2;;
 --skip-packages) maizo_skip=1;shift;;
 --no-start) maizo_start=0;shift;;
 --no-dvd-build) maizo_dvd=0;shift;;
 --help) echo 'sudo sh install.sh --user SEU_USUARIO [--runtime /caminho] [--skip-packages] [--no-start] [--no-dvd-build]';exit 0;;
 *) echo "Opção desconhecida: $1";exit 2;;
 esac
done
[ "$(id -u)" = 0 ] || { echo 'Execute com sudo (ou como root).';exit 1; }
case "$maizo_user" in ''|root) echo 'Informe --user com um usuário comum que será dono da coleção.';exit 1;; *[!a-zA-Z0-9_-]*) echo 'Nome de usuário inválido.';exit 1;; esac
id "$maizo_user" >/dev/null
if [ -z "$maizo_runtime" ] && [ -f /etc/slitaz-release ]; then
 if [ -x /opt/opl-runtime/usr/bin/python3 ] && chroot /opt/opl-runtime python3 -c 'import sys;assert sys.version_info >= (3,9)' 2>/dev/null; then
  maizo_runtime=/opt/opl-runtime
 else
  maizo_runtime=/opt/maizonas-runtime
  maizo_arch=$(uname -m)
  case "$maizo_arch" in x86_64|aarch64|armv7) ;; i?86) maizo_arch=x86;; *) echo 'Arquitetura sem runtime automático. Informe --runtime.';exit 1;; esac
  maizo_stage=$(mktemp -d /tmp/maizonas-bootstrap.XXXXXX)
  trap 'rm -r -- "$maizo_stage"' EXIT HUP INT TERM
  maizo_base=https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/$maizo_arch
  if command -v curl >/dev/null; then maizo_fetch=curl; else maizo_fetch=wget; fi
  maizo_download() {
   if [ "$maizo_fetch" = curl ]; then curl --fail --location --proto '=https' "$1" -o "$2";else wget -O "$2" "$1";fi
  }
  maizo_download "$maizo_base/latest-releases.yaml" "$maizo_stage/releases.yaml"
  # The official manifest uses one '-' record separator and simple scalar keys.
  maizo_file=$(awk '/^[ ]*file: alpine-minirootfs-/ {print $2;exit}' "$maizo_stage/releases.yaml")
  maizo_sha=$(awk '/^[ ]*file: alpine-minirootfs-/ {found=1} found && /^[ ]*sha256:/ {print $2;exit}' "$maizo_stage/releases.yaml")
  case "$maizo_file" in alpine-minirootfs-*.tar.gz) ;; *) echo 'Manifesto Alpine inválido.';exit 1;; esac
  case "$maizo_sha" in *[!a-fA-F0-9]*|'') echo 'SHA-256 inválido.';exit 1;; esac
  [ "${#maizo_sha}" = 64 ] || exit 1
  maizo_download "$maizo_base/$maizo_file" "$maizo_stage/root.tar.gz"
  echo "$maizo_sha  $maizo_stage/root.tar.gz" | sha256sum -c -
  mkdir -p "$maizo_runtime"
  tar -xzf "$maizo_stage/root.tar.gz" -C "$maizo_runtime"
  cp /etc/resolv.conf "$maizo_runtime/etc/resolv.conf"
  chroot "$maizo_runtime" /sbin/apk add --no-cache python3 py3-pillow aria2 7zip ffmpeg lsdvd iproute2 curl ca-certificates
  rm -r -- "$maizo_stage"
  trap - EXIT HUP INT TERM
 fi
fi
if [ -n "$maizo_runtime" ]; then
 case "$maizo_runtime" in /*) ;; *) echo 'O runtime deve ser um caminho absoluto.';exit 1;; esac
 for maizo_path in /home /srv /tmp /dev /proc /sys /run; do
  mkdir -p "$maizo_path" "$maizo_runtime$maizo_path"
  mountpoint -q "$maizo_runtime$maizo_path" || mount --rbind "$maizo_path" "$maizo_runtime$maizo_path"
 done
 mkdir -p "$maizo_runtime/host"
 mountpoint -q "$maizo_runtime/host" || mount --bind / "$maizo_runtime/host"
 for maizo_host_path in /usr /var /dev /proc /sys /run /var/run /var/lock /tmp; do
  mkdir -p "$maizo_runtime/host$maizo_host_path"
  mountpoint -q "$maizo_runtime/host$maizo_host_path" || mount --bind "$maizo_host_path" "$maizo_runtime/host$maizo_host_path"
 done
 mkdir -p "$maizo_runtime/opt/maizonas-source"
 mountpoint -q "$maizo_runtime/opt/maizonas-source" || mount --bind "$maizo_source" "$maizo_runtime/opt/maizonas-source"
 cp /etc/resolv.conf "$maizo_runtime/etc/resolv.conf"
 if [ "$maizo_skip" = 0 ]; then
  chroot "$maizo_runtime" /usr/bin/env MAIZONAS_ISOLATED=1 /bin/sh -s -- --runtime < "$maizo_source/scripts/dependencies.sh"
  sh "$maizo_source/scripts/dependencies.sh" --host
 fi
 mkdir -p "$maizo_runtime/opt/maizonas-installer"
 # Installer sources are temporary. Runtime binaries remain independently installed.
 cp -R "$maizo_source/maizonas" "$maizo_runtime/opt/maizonas-installer/"
 chroot "$maizo_runtime" python3 /opt/maizonas-installer/maizonas/install.py --source /opt/maizonas-source --user "$maizo_user" --runtime "$maizo_runtime" --start "$maizo_start" --dvd "$maizo_dvd" --host-root /proc/1/root
else
 if [ "$maizo_skip" = 0 ]; then sh "$maizo_source/scripts/dependencies.sh" --runtime;fi
 command -v python3 >/dev/null
 python3 "$maizo_source/maizonas/install.py" --source "$maizo_source" --user "$maizo_user" --start "$maizo_start" --dvd "$maizo_dvd"
fi
