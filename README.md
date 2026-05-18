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
  - `install_model_entry`
  - `set_as_default_provider`
  - `disable_other_chat_models`
  - `model_modalities_json`
  - `max_context_tokens`
  - `auto_sync_provider_on_startup`
- 提供命令把插件配置同步到 AstrBot 的 `provider_sources` 和模型条目 `provider`
- 可以从插件命令里直接把 AstrBot 默认聊天模型切换成 Hermes，不需要新手去 WebUI 下拉框里找
- 提供 Hermes API 健康检查和当前默认模型状态检查命令
- 发布版源码不内置任何真实 URL、Key、Token、密码
- 不使用已废弃的 `@register` 插件装饰器，依赖 `metadata.yaml` 和 `Star` 子类自动发现，减少新版 AstrBot 兼容性问题

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
├── requirements.txt
├── LICENSE
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
8. 执行 `/hermes安装提供商`，让 Hermes 出现在 AstrBot 模型列表里。
9. 如果想直接让机器人主聊天走 Hermes，执行 `/hermes切换默认`。
10. 重启 AstrBot。
11. 用 `/hermes状态` 确认默认模型是否已经是 Hermes。

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
| `extra_body_json` | `{}` | 高级项，额外请求体；必须是 JSON 对象。可以用来传 Hermes API 额外参数，例如 profile |
| `install_model_entry` | `true` | 同时创建 AstrBot 模型条目 `hermes_agent/hermes-agent`。如果不开，可能只注册了 provider 类型，但 WebUI 模型列表看不到可选模型 |
| `set_as_default_provider` | `false` | 开启后 `/hermes安装提供商` 会直接把 AstrBot 默认聊天模型改成 Hermes。保守做法是先关着，健康检查通过后执行 `/hermes切换默认` |
| `disable_other_chat_models` | `false` | 切换默认时是否禁用其它聊天模型。一般不建议开；只有你想强制所有聊天都走 Hermes 时再开 |
| `model_modalities_json` | `{"items":["text","tool_use"]}` | 写入 AstrBot 模型条目的能力列表。底层 Hermes 模型支持图片时可加入 `image` |
| `max_context_tokens` | `0` | 写入 AstrBot 模型条目的上下文长度。0 表示不限制；知道底层模型上下文时可填 128000 等 |
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

把当前插件配置写入 AstrBot `cmd_config.json`：

- `provider_sources`：写入 Hermes provider source，例如 `id=hermes_agent`、`type=hermes_chat_completion`、`api_base=http://127.0.0.1:8642/v1`。
- `provider`：写入真正能在 AstrBot 模型列表里看到的模型条目，例如 `hermes_agent/hermes-agent`。

执行成功后会提示类似：

```text
Hermes Provider 配置已写入。
added provider source 'hermes_agent', added chat model 'hermes_agent/hermes-agent', default unchanged ...
```

如果你只执行这个命令，Hermes 会出现在 AstrBot 模型列表里，但不一定立刻成为默认聊天模型。

## `/hermes切换默认`

把 AstrBot 默认聊天模型直接改成当前插件配置对应的 Hermes 模型：

```text
provider_source_id: hermes_agent
model: hermes-agent
default_provider_id: hermes_agent/hermes-agent
```

执行后重启 AstrBot。启动日志应该能看到：

```text
Loading model hermes_chat_completion(hermes_agent/hermes-agent) ...
Selected hermes_chat_completion(hermes_agent/hermes-agent) as default chat model provider
```

这才表示普通 @ 对话真的走 Hermes，而不是其它 Gemini/OpenAI provider。

## `/hermes状态`

检查当前 AstrBot 配置里：

- Hermes provider source 是否已写入
- Hermes 模型条目是否已写入
- 当前默认聊天模型是不是 Hermes
- 当前插件连接的 `api_base` 是什么

## 第 7 步：确认 Hermes 已经成为默认模型

执行 `/hermes状态`，如果看到：

```text
是否正在默认使用 Hermes: 是
```

再重启 AstrBot 后测试普通 @ 对话。之后 QQ / WebChat 消息就会经过：

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
  "extra_body": {},
  "models": ["hermes-agent"]
}
```

还需要在 `provider` 列表里有模型条目：

```json
{
  "id": "hermes_agent/hermes-agent",
  "enable": true,
  "provider_source_id": "hermes_agent",
  "model": "hermes-agent",
  "modalities": ["text", "tool_use"],
  "custom_extra_body": {},
  "max_context_tokens": 0
}
```

并且要把默认聊天模型设成：

```json
"provider_settings": {
  "default_provider_id": "hermes_agent/hermes-agent"
}
```

一般不建议新手手动改，优先用 `/hermes安装提供商` + `/hermes切换默认`。

---

# 自定义 URL、Key 和 Hermes 底层模型怎么切

这里要分清两层：

## A. AstrBot → Hermes API 的连接

这是本插件配置的：

```text
api_base = http://127.0.0.1:8642/v1
api_key = Hermes api_server 的 key
model = hermes-agent
```

如果 Hermes 和 AstrBot 在同一台机器，推荐 `127.0.0.1`。如果不在同一台机器，改成 Hermes 服务器 IP，并确保 Hermes 绑定 `0.0.0.0` 且端口放行。

## B. Hermes → 底层大模型 provider

这不是在 AstrBot 插件里直接填 OpenAI/Gemini/DeepSeek key，而是在 Hermes 自己里面切：

```bash
hermes model
# 或
hermes setup model
# 或编辑
hermes config edit
```

切完后重启 Hermes Gateway：

```bash
hermes gateway restart
```

然后 AstrBot 仍然只连：

```text
http://127.0.0.1:8642/v1
model: hermes-agent
```

好处是：AstrBot 不需要知道底层到底是 Gemini、DeepSeek、OpenRouter 还是本地模型，全部由 Hermes 管。

---

# 常见问题排查

## 1. 插件装了，但模型列表里没有 Hermes

注意：只看到日志 `Model provider registered: hermes_chat_completion` 只代表“provider 类型注册成功”，不代表 AstrBot 模型列表里已经有可选模型。

请在插件配置里保持：

```text
install_model_entry = true
```

然后执行：

```text
/hermes安装提供商
```

再重启 AstrBot。

检查插件是否加载成功：

```text
Loading plugin astrbot_plugin_hermes_ecosystem
Model provider registered: hermes_chat_completion
```

如果还是看不到，执行 `/hermes状态` 看“模型条目”是否为“已写入”。

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

---

# AstrBot 插件市场/发布注意事项

本插件按 AstrBot 新版插件结构发布：

- 插件类继承 `Star`，不依赖已废弃的 `@register` 插件装饰器。
- 插件元数据以 `metadata.yaml` 为准。
- `metadata.yaml` 中的 `version` 使用普通版本号，例如 `0.2.4`，Release tag 可以使用 `v0.2.4`。
- `repo` 指向 GitHub 仓库，方便 AstrBot WebUI/插件市场识别更新来源。
- `requirements.txt` 只声明第三方依赖，目前为 `httpx`。
- 打包发布时不要包含 `__pycache__`、`.pyc`、`.bak`、本地配置文件、真实 key 或生成的 zip。


## 热重载说明

AstrBot 热重载插件时，Provider 适配器可能已经存在。插件会自动替换同名的旧 `hermes_chat_completion` 适配器，避免重复注册报错或继续使用旧代码。


## v0.2.6 重要变化：尽量只在插件里完成切换

新版默认把 `enable_provider` 和 `set_as_default_provider` 打开。普通用户只需要：

1. 在插件配置页确认 `api_base = http://127.0.0.1:8642/v1`。
2. 如果 Hermes API Server 没设置 key，`api_key` 留空；如果设置了 key，就填 API key。
3. 模型名保持 `hermes-agent`。
4. 在聊天里执行 `/hermes安装提供商`。
5. 重启 AstrBot。
6. 执行 `/hermes状态`，看到“是否正在默认使用 Hermes: 是”。

新版默认 `use_builtin_openai_adapter = true`，也就是用 AstrBot 内置 `openai_chat_completion` 适配 Hermes 的 OpenAI-compatible API。这样更稳，不需要用户去 AstrBot 其它地方手动添加 provider，也避免自定义适配器在某些 AstrBot 版本里遇到 `TextPart is not JSON serializable`。如果你确实要测试插件内置的 `hermes_chat_completion` 适配器，可以把这个选项关掉。


## v0.2.7 修复：本机 Hermes 无 key 也能用

AstrBot 内置 OpenAI 适配器要求 `api_key` 非空，但本机 Hermes API Server 通常不校验 key。新版默认填入占位值 `sk-hermes-local`，这样用户不需要去系统环境变量或 AstrBot 其它地方额外配置。若你的 Hermes API Server 设置了真实 API key，把插件配置里的 `api_key` 改成真实 key 即可。
