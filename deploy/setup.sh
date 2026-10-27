#!/usr/bin/env bash
# 在云服务器（Ubuntu）上安装/更新抽佣驾驶舱机器人：python 虚拟环境 + systemd 服务（开机自启、崩溃自动重启）
# 用法：代码已传到 /opt/cockpit 后，以 root 运行 bash /opt/cockpit/deploy/setup.sh
set -euo pipefail
APP=/opt/cockpit

if ! id cockpit >/dev/null 2>&1; then
  useradd --system --home "$APP" --shell /usr/sbin/nologin cockpit
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip >/dev/null

python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"

chown -R cockpit:cockpit "$APP"
chmod 600 "$APP/config.env"

cp "$APP/deploy/cockpit.service" /etc/systemd/system/cockpit.service
systemctl daemon-reload
systemctl enable cockpit >/dev/null
systemctl restart cockpit
sleep 3
systemctl --no-pager --lines=5 status cockpit || true
