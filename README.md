# AstrBot Hermes Ecosystem Plugin

把 **Hermes Agent** 接入 **AstrBot** 的发布版插件。

这不是一个普通的“问答命令插件”，而是把 Hermes Agent 暴露出来的 **OpenAI-compatible API** 注册成 AstrBot 的模型提供商。配置完成后，AstrBot 可以像调用普通大模型一样调用 Hermes；Hermes 再负责模型路由、工具调用、skills、多 Agent、文件/终端/网页能力等。

## 适合谁用

- 你已经有 AstrBot，希望 QQ / 群聊 / WebChat 的回复由 Hermes Agent 驱动。
- 你想让 AstrBot 不只是聊天，而是可以借助 Hermes 的工具、skills、记忆、定时任务、子代理等能力。
- 你没有玩过 Agent，也可以按本文档一步一步部署。

## 整体架构

```text
QQ / 群聊 / WebChat
        ↓
AstrBot：消息接入、权限、插件生态、群聊事件
        ↓
本插件注册的 hermes_chat_completion provider
        ↓ HTTP OpenAI-compatible API
Hermes Gateway api_server：/health、/v1/models、/v1/chat/completions
        ↓
Hermes Agent：模型路由、tools、skills、subagent、cron、文件/终端/网页能力
        ↓
AstrBot 回复 QQ / WebChat
```

一句话理解：

> AstrBot 负责接 QQ 消息；Hermes 负责像 Agent 一样思考和执行；本插件负责把两边接起来。

## 插件功能

- 注册 AstrBot 模型提供商类型：`hermes_chat_completion`
- 所有需要用户填写的内容都放在 AstrBot 插件配置页：
  - `provider_id`
  - `enable_provider`
  - `api_base`
  - `api_key`
  - `model`
  - `timeout`
  - `streaming_response`
  - `temperature`
  - `max_tokens`
  - `custom_headers_json`
  - `extra_body_json`
  - `auto_sync_provider_on_startup`
- 提供命令把插件配置同步到 AstrBot 的 `provider_sources`
- 提供 Hermes API 健康检查命令
- 发布版源码不内置任何真实 URL、Key、Token、密码

## 目录结构

把插件目录放到 AstrBot 插件目录：

```text
AstrBot/data/plugins/astrbot_plugin_hermes_ecosystem
```

目录结构：

```text
astrbot_plugin_hermes_ecosystem/
├── main.py
├── metadata.yaml
├── _conf_schema.json
└── README.md
```

放好后，重启 AstrBot 或在 AstrBot WebUI 重载插件。

---

# 新手部署总流程

如果你从没用过 Agent，可以按这个顺序做：

1. 安装并配置 Hermes Agent。
2. 选择 Hermes 背后的大模型，例如 OpenRouter、OpenAI、DeepSeek、Gemini 等。
3. 启动 Hermes Gateway 的 `api_server`，让它提供 OpenAI-compatible API。
4. 用 curl 测试 Hermes API 是否正常。
5. 安装本 AstrBot 插件。
6. 在插件配置页填写 Hermes API 地址、key、模型名。
7. 在 QQ / WebChat 里执行 `/hermes健康`。
8. 执行 `/hermes安装提供商`。
9. 重启 AstrBot。
10. 在 AstrBot 模型提供商里选择 Hermes provider。

下面详细展开。

---

# 第 1 步：安装 Hermes Agent

Hermes Agent 官方文档：

```text
https://hermes-agent.nousresearch.com/docs
```

Linux / macOS / WSL 常见安装方式：

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

安装后检查：

```bash
hermes --version
hermes doctor
```

如果你在中国大陆服务器上，直接访问 GitHub 可能很慢或失败，可以换镜像、手动下载，或参考 Hermes 官方安装文档。

## 配置 Hermes 使用哪个大模型

运行交互式设置：

```bash
hermes setup
```

或者只配置模型：

```bash
hermes model
```

你需要准备一个可用的大模型 provider，例如：

- OpenRouter
- OpenAI
- Anthropic
- DeepSeek
- Google Gemini
- 本地 / 自定义 OpenAI-compatible 模型

配置完成后先在终端测试 Hermes 本身能不能聊天：

```bash
hermes chat -q "只回复两个字：正常"
```

如果这里都不能正常回复，先不要配置 AstrBot，先把 Hermes 自己修好。

---

# 第 2 步：开启 Hermes API Server

本插件连接的不是 Hermes CLI 窗口，而是 Hermes Gateway 的 `api_server` 平台。

它会提供这些 HTTP 接口：

```text
GET  /health
GET  /v1/models
POST /v1/chat/completions
```

这些接口长得像 OpenAI API，所以 AstrBot 可以把它当模型提供商调用。

## 推荐配置：AstrBot 和 Hermes 在同一台机器

编辑 Hermes 配置：

```bash
hermes config edit
```

在 `~/.hermes/config.yaml` 里确认或添加：

```yaml
platforms:
  api_server:
    enabled: true
    extra:
      host: 127.0.0.1
      port: 8642
    key: ""
    cors_origins: "*"
```

含义：

| 项目 | 说明 |
| --- | --- |
| `enabled: true` | 开启 API Server |
| `host: 127.0.0.1` | 只允许本机访问，最安全 |
| `port: 8642` | API 端口，可以改，但插件配置要同步改 |
| `key: ""` | 不设置 API key，仅适合本机访问 |
| `cors_origins: "*"` | 允许跨域，一般保持默认即可 |

启动或重启 Hermes Gateway：

```bash
hermes gateway restart
```

如果之前没有安装 gateway 服务，可以先运行：

```bash
hermes gateway setup
hermes gateway install
hermes gateway start
```

查看状态：

```bash
hermes gateway status
hermes status --all
```

## 测试 API 是否正常

在运行 Hermes 的机器上执行：

```bash
curl -sS http://127.0.0.1:8642/health
```

正常类似：

```json
{"status":"ok","platform":"hermes-agent"}
```

测试模型列表：

```bash
curl -sS http://127.0.0.1:8642/v1/models
```

正常应该能看到包含 `hermes-agent` 的模型列表。

测试聊天：

```bash
curl -sS http://127.0.0.1:8642/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"hermes-agent","messages":[{"role":"user","content":"只回复两个字：正常"}],"stream":false}'
```

如果这里能返回正常内容，再去配置 AstrBot。

---

# 第 3 步：端口和网络怎么填

很多新手最容易卡在 `127.0.0.1`、`0.0.0.0`、端口放行这里。

## 情况 A：AstrBot 和 Hermes 在同一台服务器

这是最推荐、最安全的方式。

Hermes 配置：

```yaml
host: 127.0.0.1
port: 8642
```

插件配置里的 `api_base` 填：

```text
http://127.0.0.1:8642/v1
```

不需要开放防火墙端口，因为只有本机访问。

## 情况 B：AstrBot 和 Hermes 在同一局域网，但不在同一台机器

假设 Hermes 机器局域网 IP 是：

```text
192.168.1.20
```

Hermes 配置要改成：

```yaml
host: 0.0.0.0
port: 8642
key: "请换成一个很长的随机key"
```

插件配置里的 `api_base` 填：

```text
http://192.168.1.20:8642/v1
```

插件配置里的 `api_key` 填 Hermes 配置里的 key。

还要确认 Hermes 机器防火墙允许 AstrBot 机器访问 8642 端口。

## 情况 C：Hermes 要给公网服务器上的 AstrBot 调用

不建议裸露 HTTP 端口到公网。如果必须这样做：

1. Hermes `host` 改成 `0.0.0.0`。
2. 设置强 `key`。
3. 云服务器安全组只允许 AstrBot 服务器 IP 访问 8642。
4. 更推荐加 Nginx / Caddy 反向代理和 HTTPS。
5. 插件配置 `api_base` 填公网域名或 IP：

```text
https://your-domain.example/v1
```

或：

```text
http://服务器公网IP:8642/v1
```

强烈不要使用空 key 暴露到公网。

## `api_base` 一定要带 `/v1` 吗？

推荐带：

```text
http://127.0.0.1:8642/v1
```

如果你误填成：

```text
http://127.0.0.1:8642
```

插件会自动补成 `/v1`，但文档和排查时都建议直接写完整地址。

---

# 第 4 步：安装本插件

把插件目录放到：

```text
AstrBot/data/plugins/astrbot_plugin_hermes_ecosystem
```

然后重启 AstrBot 或在 WebUI 重载插件。

启动日志里应该能看到类似：

```text
Loading plugin astrbot_plugin_hermes_ecosystem
Model provider registered: hermes_chat_completion
```

如果没有，说明插件没有被正确加载。

---

# 第 5 步：填写插件配置

进入 AstrBot WebUI：

```text
插件管理 → Hermes 生态接入 → 配置
```

填写这些项。

| 配置项 | 推荐值 | 说明 |
| --- | --- | --- |
| `provider_id` | `hermes_agent` | 写入 AstrBot 模型提供商列表时使用的唯一 ID。多个 Hermes 实例可改成 `hermes_agent_2` |
| `enable_provider` | `true` | 想让 AstrBot 使用 Hermes 时改成 true；发布默认 false 是为了安全 |
| `api_base` | `http://127.0.0.1:8642/v1` | Hermes API Server 地址。AstrBot 和 Hermes 不同机器时，把 IP 换成 Hermes 机器地址 |
| `api_key` | 空 / `$HERMES_API_KEY` / 真实 key | Hermes 配置了 key 就填；没设置 key 可留空 |
| `model` | `hermes-agent` | Hermes API 暴露给客户端的模型名 |
| `timeout` | `300` 或 `600` | Agent 可能会调用工具，建议比普通模型长 |
| `streaming_response` | `true` | Hermes 支持 SSE 时建议开启；如果兼容性不好可关掉 |
| `temperature` | `0.7` | 传给 Hermes API 的 temperature |
| `max_tokens` | `4096` | 单次回复最大 token |
| `custom_headers_json` | `{}` | 高级项，自定义请求头；必须是 JSON 对象 |
| `extra_body_json` | `{}` | 高级项，额外请求体；必须是 JSON 对象 |
| `auto_sync_provider_on_startup` | `false` | 建议先手动 `/hermes安装提供商`，确认没问题后再考虑开启 |

## 关于 api_key

有三种常见方式：

### 方式 1：Hermes API Server 没设置 key

Hermes 配置：

```yaml
key: ""
```

插件配置：

```text
api_key 留空
```

只建议 `host: 127.0.0.1` 本机访问时这样做。

### 方式 2：直接在插件配置里填 key

Hermes 配置：

```yaml
key: "换成你自己的随机长key"
```

插件配置：

```text
api_key = 换成你自己的随机长key
```

### 方式 3：用环境变量

插件配置：

```text
api_key = $HERMES_API_KEY
```

然后在 AstrBot 运行环境中设置：

```bash
export HERMES_API_KEY='换成你自己的随机长key'
```

如果 AstrBot 是 systemd 服务，需要写到 systemd service 的 `Environment=` 或环境文件里，而不是只在当前 SSH 窗口 export。

---

# 第 6 步：在 AstrBot 里执行命令

本插件提供这些命令。

## `/hermes生态`

显示插件用途和架构说明。

## `/hermes配置`

显示当前插件配置会生成的 AstrBot provider JSON。

它会隐藏真实 key。你可以用它检查：

- `api_base` 有没有填错
- `model` 是不是 `hermes-agent`
- `enable` 是不是你想要的状态
- JSON 高级配置有没有写错

## `/hermes健康`

检查当前配置的 Hermes API：

- `GET /health`
- `GET /v1/models`

推荐先执行这个。成功后再安装 provider。

## `/hermes安装提供商`

把当前插件配置写入 AstrBot `cmd_config.json` 的 `provider_sources`。

执行成功后会提示类似：

```text
Hermes Provider 配置已写入。
added provider 'hermes_agent' in .../cmd_config.json
请在 AstrBot WebUI 重启/重载，或重启 AstrBot 服务后，在模型提供商里选择这个 provider。
```

然后重启 AstrBot。

---

# 第 7 步：选择 Hermes 模型提供商

重启 AstrBot 后，在 AstrBot WebUI 的模型提供商 / 模型配置页面里找到：

```text
type: hermes_chat_completion
id: hermes_agent
```

把它设置为当前使用的模型提供商，或在对应人格 / 会话配置里选择它。

之后 QQ / WebChat 消息就会经过：

```text
AstrBot → hermes_chat_completion → Hermes API Server → Hermes Agent
```

---

# 手动 Provider 配置示例

如果不使用 `/hermes安装提供商`，也可以手动在 AstrBot provider 配置里添加：

```json
{
  "id": "hermes_agent",
  "type": "hermes_chat_completion",
  "provider_type": "chat_completion",
  "provider": "hermes",
  "enable": true,
  "key": ["$HERMES_API_KEY"],
  "api_base": "http://127.0.0.1:8642/v1",
  "model": "hermes-agent",
  "timeout": 300,
  "streaming_response": true,
  "temperature": 0.7,
  "max_tokens": 4096,
  "custom_headers": {},
  "extra_body": {}
}
```

一般不建议新手手动改，优先用 `/hermes安装提供商`。

---

# 常见问题排查

## 1. 插件装了，但模型列表里没有 Hermes

检查插件是否加载成功：

```text
Loading plugin astrbot_plugin_hermes_ecosystem
Model provider registered: hermes_chat_completion
```

然后执行：

```text
/hermes安装提供商
```

最后重启 AstrBot。

## 2. `/hermes健康` 连接失败

按顺序检查：

1. Hermes Gateway 是否启动。
2. Hermes `api_server.enabled` 是否为 `true`。
3. `api_base` 是否填对，推荐 `http://127.0.0.1:8642/v1`。
4. 端口是否一致：Hermes 配 `8642`，插件也要写 `8642`。
5. AstrBot 和 Hermes 是否在同一台机器。
6. 如果不在同一台机器，Hermes 是否绑定 `0.0.0.0`。
7. 防火墙 / 云安全组是否放行端口。
8. 如果 Hermes 设置了 key，插件的 `api_key` 是否一致。

## 3. `Connection refused`

通常表示端口没有服务在监听。

在 Hermes 机器上检查：

```bash
curl http://127.0.0.1:8642/health
```

如果失败，说明 Hermes API Server 没启动或端口不是 8642。

## 4. `401 Unauthorized` 或 `403 Forbidden`

通常是 key 不对。

检查 Hermes 配置里的：

```yaml
key: "..."
```

和插件配置里的：

```text
api_key
```

是否一致。

## 5. `404 Not Found`

常见原因是 `api_base` 没写 `/v1`，或者反向代理路径写错。

推荐：

```text
http://127.0.0.1:8642/v1
```

本插件会自动补 `/v1`，但如果你用了 Nginx / Caddy 反代，仍然要确认 `/v1/chat/completions` 被正确转发。

## 6. 调用很慢或超时

Hermes 是 Agent，不只是普通聊天补全。它可能会调用工具、读文件、联网、执行命令、生成计划。

建议：

```text
timeout = 300 或 600
```

如果你的 AstrBot 平台本身也有超时限制，也需要相应调大。

## 7. QQ 里没有反应，但 `/hermes健康` 正常

这说明 Hermes API 可能没问题，问题可能在 AstrBot 的模型选择或 QQ 平台侧。

检查：

1. AstrBot 是否已经重启。
2. 是否真的选择了 `hermes_agent` 这个 provider。
3. `enable_provider` 是否为 true，并且 `/hermes安装提供商` 后已经重启。
4. AstrBot 当前人格 / 会话是否使用该模型。
5. QQ 平台适配器是否收到消息。

## 8. 可以公开到公网吗？

可以，但不建议裸奔。若 `api_server` 绑定 `0.0.0.0`：

- 必须设置强 key。
- 云安全组只允许可信 IP 访问。
- 最好套 HTTPS 反向代理。
- 不要把 key 写进公开仓库、截图、README 示例。

---

# 发布前安全检查

发布前建议检查源码中是否误写入敏感信息：

```bash
grep -RInE 'sk-[A-Za-z0-9_-]{16,}|Bearer [A-Za-z0-9_~.-]{16,}|password[=:]' astrbot_plugin_hermes_ecosystem || true
```

正常情况下不应该出现真实密钥。

不要提交：

- 真实 API key
- NapCat token
- AstrBot WebSocket token
- 服务器密码
- 私有 IP + 密码组合
- 个人 QQ 号等隐私信息

---

# 推荐默认值

新手本机部署时，推荐：

```text
provider_id = hermes_agent
enable_provider = true
api_base = http://127.0.0.1:8642/v1
api_key = 留空，或 $HERMES_API_KEY
model = hermes-agent
timeout = 300
streaming_response = true
temperature = 0.7
max_tokens = 4096
custom_headers_json = {}
extra_body_json = {}
auto_sync_provider_on_startup = false
```

配置后执行：

```text
/hermes健康
/hermes安装提供商
```

然后重启 AstrBot。