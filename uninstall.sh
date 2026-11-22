#!/bin/sh
# Remove the application/startup only. Never remove media, state or system packages.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Execute com sudo.';exit 1; }
maizo_runtime=''
[ ! -f /etc/maizonas/install.env ] || . /etc/maizonas/install.env
maizo_runtime=${MAIZONAS_RUNTIME:-}
if [ -x /usr/local/sbin/maizonasctl ];then /usr/local/sbin/maizonasctl stop;fi
if [ -f /etc/systemd/system/maizonas.service ];then
 systemctl disable maizonas || true
 rm /etc/systemd/system/maizonas.service
 systemctl daemon-reload
fi
if command -v rc-update >/dev/null;then rc-update del maizonas default 2>/dev/null || true;fi
if command -v update-rc.d >/dev/null;then update-rc.d -f maizonas remove 2>/dev/null || true;fi
if [ -f /etc/init.d/local.sh ];then sed -i '/^\/etc\/init.d\/maizonas start$/d' /etc/init.d/local.sh;fi
[ ! -f /etc/init.d/maizonas ] || rm /etc/init.d/maizonas
if [ -n "$maizo_runtime" ];then
 for maizo_path in /opt/maizonas /etc/maizonas;do
  if mountpoint -q "$maizo_runtime$maizo_path";then umount "$maizo_runtime$maizo_path";fi
 done
fi
[ ! -d /opt/maizonas ] || rm -r /opt/maizonas
[ ! -f /usr/local/sbin/maizonasctl ] || rm /usr/local/sbin/maizonasctl
echo 'Aplicação removida. Jogos, filmes, downloads, configuração, backups, Samba e pacotes foram preservados.'
