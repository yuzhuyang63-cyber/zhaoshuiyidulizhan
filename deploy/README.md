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
Each successful submission also refreshes the long-term Excel statistics report:

- `/opt/zhaoshuiyidulizhan/data/inquiries/reports/inquiry-statistics.xlsx`

The long-term report is generated from all saved inquiry records and includes
raw inquiries plus daily, weekly, monthly, quarterly, yearly, and product
interest summaries. Monthly report files are still generated as
`inquiry-report-YYYY-MM.xlsx` when needed.

When SMTP is configured, inquiry notification emails and the daily scheduled
report email use the existing `INQUIRY_TO` destination mailbox list. The daily
statistics email is sent by the backend at 21:00 China time by default.

Optional inquiry settings in `.env`:

```bash
INQUIRY_RETENTION_DAYS=0
INQUIRY_DAILY_REPORT_HOUR=21
INQUIRY_DAILY_REPORT_MINUTE=0
INQUIRY_ALLOWED_ORIGINS=https://cyqwater.com,https://www.cyqwater.com
```

`INQUIRY_RETENTION_DAYS=0` means keep historical inquiry data indefinitely, which
preserves yearly, quarterly, monthly, and weekly statistics continuity.
`INQUIRY_ALLOWED_ORIGINS` limits cross-origin browser calls to the inquiry API;
same-origin website submissions continue to work without adding the domain here.

## Feishu customer tracking

The backend can append every new inquiry to one Feishu Bitable customer tracking
table. It only creates a new record; it does not overwrite existing rows edited
by sales.

Create these fields in the Feishu customer table:

```text
询盘编号
提交时间
客户名单
地区名称
客户场景
沟通进程
客户要求
是否需要跟进
已购买
购买金额
成本
利润
发货形式
发货状态
售后跟踪
跟进备注
下次跟进时间
最后更新时间
公司名称
邮箱
WhatsApp
意向产品
访客IP
```

Recommended first-pass field types: text for most fields, single-select for
status fields such as `沟通进程`, `是否需要跟进`, `已购买`, `发货形式`, `发货状态`,
and `售后跟踪`. The backend sends default values such as `新询盘`, `是`, `否`,
`未确定`, `未发货`, and `未开始`.

`地区名称` is filled automatically from server-side country headers such as
`CF-IPCountry`, `CloudFront-Viewer-Country`, or `X-Vercel-IP-Country` when your
CDN/reverse proxy provides them. If no country header is available, the field is
looked up through the optional GeoIP API below; if both methods fail, the field
is left empty.

Optional GeoIP API settings:

```bash
GEOIP_ENABLED=1
GEOIP_API_URL_TEMPLATE=https://ipwho.is/{ip}?lang=zh-CN
GEOIP_TIMEOUT_SECONDS=3
```

`GEOIP_API_URL_TEMPLATE` must contain `{ip}`. Free IP lookup APIs are usually
enough for low inquiry volume, but they may have rate limits, availability
limits, or commercial-use restrictions. For stable production use, replace the
URL with a paid API or a local IP database provider.

Add these settings to `.env` after creating a Feishu self-built app and granting
it Bitable permissions:

```bash
FEISHU_ENABLED=1
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_BITABLE_APP_TOKEN=
FEISHU_CUSTOMER_TABLE_ID=
```

If Feishu sync fails, the inquiry is still saved locally and email reporting
continues; the failure is written to the backend log.
