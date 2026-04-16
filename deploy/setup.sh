#!/bin/bash
# CryptoMaster Hetzner Setup Script
# Run once on a fresh Ubuntu 24.04 server as root
# Usage: REPO_URL=https://github.com/YOUR/REPO.git bash setup.sh

set -e

APP_USER="cryptomaster"
APP_DIR="/opt/cryptomaster"

if [ -z "$REPO_URL" ]; then
    echo "ERROR: set REPO_URL before running this script"
    echo "  REPO_URL=https://github.com/YOUR/REPO.git bash setup.sh"
    exit 1
fi

echo "=== [1/8] System update ==="
apt-get update -qq && apt-get upgrade -y -qq

echo "=== [2/8] Install Python, Redis, Git ==="
apt-get install -y -qq python3 python3-pip python3-venv redis-server git

echo "=== [3/8] Enable and start Redis ==="
systemctl enable redis-server
systemctl start redis-server

echo "=== [4/8] Create app user ==="
id -u $APP_USER &>/dev/null || useradd -r -s /bin/bash -m -d /home/$APP_USER $APP_USER

echo "=== [5/8] Clone repository ==="
if [ -d "$APP_DIR/.git" ]; then
    echo "Repo already cloned, pulling latest..."
    sudo -u $APP_USER git -C $APP_DIR pull origin main
else
    sudo -u $APP_USER git clone "$REPO_URL" $APP_DIR
fi
chown -R $APP_USER:$APP_USER $APP_DIR

echo "=== [6/8] Set up Python venv ==="
sudo -u $APP_USER python3 -m venv $APP_DIR/venv
sudo -u $APP_USER $APP_DIR/venv/bin/pip install --upgrade pip -q
sudo -u $APP_USER $APP_DIR/venv/bin/pip install -r $APP_DIR/requirements.txt -q

echo "=== [7/8] Allow cryptomaster to restart its own service ==="
cat > /etc/sudoers.d/cryptomaster << 'EOF'
cryptomaster ALL=(ALL) NOPASSWD: /bin/systemctl restart cryptomaster, /bin/systemctl is-active cryptomaster
EOF
chmod 440 /etc/sudoers.d/cryptomaster

echo "=== [8/8] Install and enable systemd service ==="
cp $APP_DIR/deploy/cryptomaster.service /etc/systemd/system/cryptomaster.service
systemctl daemon-reload
systemctl enable cryptomaster

echo ""
echo "=== SETUP COMPLETE ==="
echo ""
echo "Next: create the .env file with your secrets:"
echo "  cp $APP_DIR/deploy/.env.example $APP_DIR/.env"
echo "  nano $APP_DIR/.env"
echo ""
echo "Encode Firebase key:  base64 -w 0 firebase_key.json"
echo ""
echo "Then start the bot:"
echo "  systemctl start cryptomaster"
echo "  journalctl -fu cryptomaster"
