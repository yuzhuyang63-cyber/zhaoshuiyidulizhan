# 找水仪独立站

这是一个用于地下水勘探设备展示和询盘的外贸官网项目，包含：

- 静态官网前端：`HTML + CSS + JavaScript`
- 右侧悬浮智能客服
- 基于产品手册的本地 `RAG` 知识库检索
- Python 聊天后端：`sever_main.py`

当前知识库已接入两份产品手册：

- `ADMT安卓屏系列产品操作手册（中英文版）`
- `找水金箍棒操作手册中英文版`

客服支持中英文识别，并尽量按用户输入语言回复。

## 功能概览

- 多页面官网：首页、产品、解决方案、视频、联系我们
- 右下角智能客服悬浮窗
- 按产品手册做知识库检索，降低大模型幻觉
- 中文/英文问答
- 知识库无答案时安全降级，不乱编价格、库存、交期等信息
- 支持公网部署，前端与 `/api/chat` 同域调用

## 项目结构

```text
.
├─ index.html
├─ about.html
├─ products.html
├─ solutions.html
├─ videos.html
├─ contact.html
├─ styles.css
├─ script.js
├─ sever_main.py
├─ requirements.txt
├─ .env.example
├─ kb/
│  ├─ build_product_kb.py
│  ├─ sources.json
│  ├─ README.md
│  └─ generated/
│     ├─ manual_chunks.jsonl
│     ├─ faq_seed.jsonl
│     ├─ product_catalog.json
│     └─ extraction_report.json
└─ deploy/
   ├─ README.md
   ├─ nginx.site.conf
   └─ zhaoshuiyidulizhan.service
```

## 环境要求

- Python 3.10+
- 一个可用的 DeepSeek API Key

安装依赖：

```powershell
pip install -r requirements.txt
```

## 本地启动

### 1. 配置环境变量

先复制模板：

```powershell
Copy-Item .env.example .env
```

然后编辑 `.env`，至少填写：

```env
DEEPSEEK_API_KEY=你的真实apikey
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
CHAT_SERVER_HOST=127.0.0.1
CHAT_SERVER_PORT=8000
```

说明：

- 后端会自动读取项目根目录 `.env`
- 兼容 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`API_KEY`
- `.env` 已被 `.gitignore` 忽略，不应提交到仓库

### 2. 构建知识库

如果你更新了产品手册，重新生成知识库：

```powershell
python kb/build_product_kb.py
```

生成结果位于：

- `kb/generated/manual_chunks.jsonl`
- `kb/generated/faq_seed.jsonl`
- `kb/generated/product_catalog.json`
- `kb/generated/extraction_report.json`

更多说明见：[kb/README.md](./kb/README.md)

### 3. 启动聊天后端

```powershell
python sever_main.py
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

正常情况下应看到：

- `rag_ready: true`
- `api_configured: true`

### 4. 预览前端

你可以直接打开 `index.html`，也可以起一个静态服务：

```powershell
python -m http.server 5500
```

然后访问：

```text
http://127.0.0.1:5500
```

本地开发时，前端会自动尝试：

- `http://127.0.0.1:8000/api/chat`
- `http://localhost:8000/api/chat`
- 当前站点同域 `/api/chat`

## RAG 工作方式

客服不是直接把问题丢给大模型，而是先做检索：

1. 用户提问
2. 从本地知识库中检索最相关的手册片段
3. 将片段作为上下文发送给模型
4. 模型只根据这些片段整理回答
5. 如果知识库没有明确答案，返回安全兜底回复

当前知识库以产品操作手册为主，适合回答：

- 产品概述
- 操作步骤
- WiFi/连接方式
- 在线测量/离线测量
- 数据处理
- 绘图分析
- 野外布线
- 使用注意事项

不适合直接回答：

- 价格
- 交期
- 库存
- 保修政策
- 售后条款

这些内容需要你单独补充业务数据。

## 智能客服说明

- 历史消息当前保存在 `sessionStorage`
- 同一个标签页刷新时会保留
- 关闭页面重新打开后，不再继承旧会话
- 本地调试时，如果后端报错，前端会显示更具体的错误原因
- 如果模型服务临时失败，后端会降级返回知识库原文片段，而不是直接报废

## 常见问题

### 1. 智能客服显示“暂时不可用”

优先检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

重点看：

- `rag_ready` 是否为 `true`
- `api_configured` 是否为 `true`

如果 `api_configured` 为 `false`，通常是 `.env` 没配置好，或后端没有重启。

### 2. 为什么问候语能回复，但专业问题报错？

因为问候语可能不需要调用模型；而专业问题需要走知识库检索和模型生成。如果 API Key 没读到，通常会在这一阶段失败。

### 3. 为什么有些技术参数回答不完整？

部分参数在原始手册中是图片、截图或表格，不是纯文本。生成脚本无法完整抽取时，会记录到：

- `kb/generated/extraction_report.json`

这类内容需要人工补录。

### 4. 为什么客服会保留刷新前的消息？

这是当前设计行为：为了避免刷新页面丢失当前会话。

如果你不希望刷新后保留，也可以把前端改成纯内存会话。

## 公网部署

推荐方案：

- 一台 Linux VPS
- `nginx` 提供静态站点
- `nginx` 将 `/api/*` 反向代理到 `sever_main.py`
- `systemd` 守护后端服务
- `certbot` 配置 HTTPS

部署说明见：[deploy/README.md](./deploy/README.md)

## 安全说明

- 不要把真实 API Key 写进前端代码
- 不要提交 `.env`
- 如果 Key 曾经泄露，建议去服务商后台立即轮换
- 知识库源文件和内部业务数据不要直接暴露在静态网站目录

## 后续建议

如果你继续扩展这个项目，建议下一步做这几件事：

- 补充业务 FAQ：价格、交期、保修、售后
- 将引用来源显示到前端聊天窗口
- 增加联系人收集和询盘转发
- 为英文知识库补充更规范的业务文案
- 接入日志和访问监控

