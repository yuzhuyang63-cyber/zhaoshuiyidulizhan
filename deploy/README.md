# Deployment

## Recommended topology

- One Linux VPS
- `nginx` serves the static site
- `nginx` proxies `/api/*` to the Python backend package
- `systemd` keeps the Python backend running
- `certbot` adds HTTPS

This matches the current project structure best because the site is static HTML/CSS/JS and the chatbot is a Python API.

## Server directories

- Project code: `/opt/zhaoshuiyidulizhan`
- Static files: `/var/www/zhaoshuiyidulizhan`

## Basic commands

```bash
sudo apt update
sudo apt install -y python3 python3-venv nginx snapd
sudo snap install core
sudo snap refresh core
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot
```

```bash
cd /opt
sudo mkdir -p /opt/zhaoshuiyidulizhan
sudo chown -R $USER:$USER /opt/zhaoshuiyidulizhan
```

Copy the project into `/opt/zhaoshuiyidulizhan`, then:

```bash
cd /opt/zhaoshuiyidulizhan
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python kb/build_product_kb.py
```

Edit `.env` and set the real `DEEPSEEK_API_KEY`.

Optional logging settings:

```bash
CHAT_LOG_PATH=logs/chat-backend.log
CHAT_LOG_MAX_BYTES=5242880
CHAT_LOG_BACKUP_COUNT=5
```

When the log file reaches `CHAT_LOG_MAX_BYTES`, it will rotate. Old rotated files beyond `CHAT_LOG_BACKUP_COUNT` are deleted automatically.

## Backend

Before enabling the service, either:

- keep `User=www-data` and run `sudo chown -R www-data:www-data /opt/zhaoshuiyidulizhan`, or
- edit `deploy/zhaoshuiyidulizhan.service` and replace `www-data` with your real deploy user.

Install the service file:

```bash
sudo cp deploy/zhaoshuiyidulizhan.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zhaoshuiyidulizhan
sudo systemctl status zhaoshuiyidulizhan
```

## Maintenance script

The repo includes `deploy/manage.sh` for common maintenance:

```bash
chmod +x deploy/manage.sh
bash deploy/manage.sh status
bash deploy/manage.sh restart
bash deploy/manage.sh health
bash deploy/manage.sh logs
bash deploy/manage.sh transcript-logs
bash deploy/manage.sh deploy-backend
bash deploy/manage.sh deploy-all
```

The script assumes:

- project directory: `/opt/zhaoshuiyidulizhan`
- backend service: `zhaoshuiyidulizhan`
- static directory: `/var/www/zhaoshuiyidulizhan`

You can override them with environment variables if needed.

## Static files

```bash
sudo mkdir -p /var/www/zhaoshuiyidulizhan
sudo cp *.html *.css *.js robots.txt sitemap.xml /var/www/zhaoshuiyidulizhan/
sudo cp -r assets media /var/www/zhaoshuiyidulizhan/
```

Before going live, replace `https://example.com` in `sitemap.xml` with your real public domain.

## Nginx

Edit `deploy/nginx.site.conf` and replace `example.com` with the real domain.

```bash
sudo cp deploy/nginx.site.conf /etc/nginx/sites-available/zhaoshuiyidulizhan
sudo ln -s /etc/nginx/sites-available/zhaoshuiyidulizhan /etc/nginx/sites-enabled/zhaoshuiyidulizhan
sudo nginx -t
sudo systemctl reload nginx
```

## HTTPS

After the domain points to the server IP:

```bash
sudo certbot --nginx -d example.com -d www.example.com
```

## Validation

```bash
curl http://127.0.0.1:8000/api/health
curl https://example.com/api/health
curl -X POST https://example.com/api/inquiry \
  -H 'Content-Type: application/json' \
  -d '{"name":"Test User","email":"test@example.com","message":"Need a quotation for 300m drilling.","language":"en"}'
```

The public endpoint should report `rag_ready: true` and `api_configured: true`.

Inquiry submissions are stored on the server under `/opt/zhaoshuiyidulizhan/data/inquiries/`.
