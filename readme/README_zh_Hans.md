# Suno by Ace Data Cloud：CrewAI 原生音乐工具

本集成由 **Ace Data Cloud** 提供，不是 Suno 或 CrewAI 官方产品。独立 Suno 品牌包，不是 17 服务合集。[English](../README.md)

## 安装入口

已有 [GitHub 预览 wheel 与源码包](https://github.com/AceDataCloud/SunoCrewAI/releases/tag/v0.1.0-preview.1)，源码仍在审阅，**尚未 PyPI 发布或 CrewAI 官方目录收录**。先审阅[本仓库 PR](https://github.com/AceDataCloud/SunoCrewAI/pulls)，固定下列源码，或使用带 SHA256 校验的 wheel；不要仅按 tag 名称安装附件：

```bash
uv add 'crewai-suno @ git+https://github.com/AceDataCloud/SunoCrewAI.git@e5eeb04661ed7b9a86e1f2f970a9e7943b027ca2'
```

```bash
uv add 'crewai-suno @ https://github.com/AceDataCloud/SunoCrewAI/releases/download/v0.1.0-preview.1/crewai_suno-0.1.0-py3-none-any.whl#sha256=d31998ca7f33f54c9603a0acb0d906f25933e858be6c83babc5a6d0e5a478e51'
```

wheel 来自同一固定源码 SHA，URL 强制校验 SHA256；若附件替换，摘要不符必须失败。release 页面仅提供信息，不作为信任锚。

发布后目标命令为 `uv add crewai-suno`，尚未发布前不要把它当现成安装入口。CrewAI 要求 Python 3.10–3.13；Intel macOS 可能缺 lancedb wheel，正式使用请选择支持的 Linux 环境，不跳过依赖冒充完整安装。

## 获取自己的 API Token

1. 打开 [Ace Applications](https://platform.acedata.cloud/console/applications?utm_source=github&utm_medium=referral&utm_campaign=evergreen&utm_content=sunocrewai_readme_zh_api_key)，注册并登录。必要时选择 **Initialize General Application**。
2. 打开 **General application**，确认 Suno 权限、当前余额和[价格](https://platform.acedata.cloud/models?utm_source=github&utm_medium=referral&utm_campaign=evergreen&utm_content=sunocrewai_readme_zh_pricing)。服务专属应用只支持授权的服务。
3. 点击下图 **1** 复制已有 Key，或 **2 Manage Keys → Create** 创建独立 Key。

![复制 API Key 或进入 Manage Keys，凭据均已遮挡](../assets/tutorial/get-api-key-en.png)

4. 将新 Key 命名为 `CrewAI Suno`，按需配置过期、额度和权限。若启用 **Allowed APIs**，同时允许 `/suno/audios` 与 `/suno/tasks`。

![创建专用 Key 的历史真实截图](../assets/tutorial/create-api-key-en.png)

图片于 2026-10-18 从 SunoDify 固定版本原样复用，来源见 [source.json](../assets/tutorial/source.json)。第二图历史名称是 `Dify tutorial`，这里只是示例，请填写 `CrewAI Suno`。没有可见真实凭据。

用安全输入或密钥管理器设置环境变量 `ACEDATACLOUD_API_KEY`。只放 Token 原文，不加 `Bearer`、引号或空格；不要用 platform 管理 Token，也不要把 Key 放进 prompt 或提交到 `.env`。工具可从安全凭据存储接收 `api_key=...`，序列化不包含它。

## 在 CrewAI 中添加 Suno 工具

```python
from crewai import Agent
from suno_crewai import SunoGenerateMusicTool, SunoRetrieveTaskTool

agent = Agent(
    role="音乐制作人",
    goal="按用户已批准预算生成音乐，并查询同一任务结果",
    backstory="使用 Ace Data Cloud 的 Suno 服务",
    llm=your_configured_llm,
    tools=[SunoGenerateMusicTool(), SunoRetrieveTaskTool()],
    allow_delegation=False,
    max_retry_limit=0,
)
```

工具名称为 **Suno by Ace Data Cloud - Generate Music** 和 **Suno by Ace Data Cloud - Retrieve Task**，有原生输入 schema，无需配置 MCP。只是添加工具不会调用接口；调用者负责批准付费行为。生成工具每个实例默认只允许一次调用，防止重复提交，但这不是额度上限或权限系统。

## 首用与同 ID 查询

先查当前模型目录，选择公开 Suno model ID；`chirp-v6` 是当前 API 合同示例，不是永久默认。生成请求收费，须先确定模型与额度：

```python
import json
from suno_crewai import SunoGenerateMusicTool, SunoRetrieveTaskTool

# 实际执行会收费；本教程没有运行该调用。
submitted = json.loads(SunoGenerateMusicTool().run(
    prompt="A gentle instrumental piano melody for a sunrise, no vocals.",
    model="chirp-v6", instrumental=True,
))
result = SunoRetrieveTaskTool().run(task_id=submitted["task_id"], wait_seconds=240)
print(result)
```

accepted / pending 不等于成功；保存原 `task_id`，未完成、超时或提交结果不明时，不要重跑生成。继续查询同一 ID。成功返回 `status=succeeded`、`success=true`、`media_urls` 及接口返回的原 `cost`（Credits，不是 USD）。媒体链接存在不代表已验证可播放。

对用户自己的旧任务，可直接免费只读查询：

```bash
uv run python examples/query_existing.py YOUR_EXISTING_TASK_ID
```

实际接口是 `/suno/audios` + `async=true`，以及 `/suno/tasks` + `action=retrieve,id=...`。只做初始文字生成，不猜测 duration 或高级动作，不加模型 fallback，不自动重试收费 HTTP 提交；有界等待只查询同一个任务。

## 在真实 CrewAI 界面查看执行

![CrewAI 官方历史执行详情，仅作交互参考，非 Ace 跑通](../assets/tutorial/official-crewai-tracing.png)

图为 CrewAI 官方历史原图，2026-10-18 下载，原图日期标记 `10/1/2025`、版本未注明；左侧是执行步骤，右侧展开 Response，输入未展开。**不是本 Suno 包运行截图，不证明 Ace 上线，也不承诺新增 GUI**。你的实际执行应检查具名 Suno 工具事件和 task 状态；可选 tracing 的账号/认证见[官方文档](https://docs.crewai.com/en/observability/tracing)，本包不自动开启追踪。

## 常见问题

| 情况 | 处理 |
|---|---|
| 401 / 403 | 检查完整消费者 Token、过期、Suno 权限、Allowed APIs 和余额；403 不一概等于内容审核。 |
| 400 | 对照当前模型及输入 schema；本工具不隐式支持所有高级动作。 |
| pending / 无结果 | 只查同一任务 ID，不重新生成。 |
| 429 | 降低并发并等待；工具只发一次 HTTP，LLM / agent 自身可能另有重试。 |
| 超时 / 5xx | 提交可能已到服务端，先看请求历史再决定是否重新生成。 |
| ToolFailure | 已明确失败；结构化错误默认不可重试。保留 task/trace ID 联系支持，不提供 Key。 |
| 音频无法打开 | 确认终态成功，再检查返回 HTTPS URL 的网络访问。 |

代码免费，生成和你配置的 LLM 按当前价格计费；查询中的 cost 是原任务费用，不是新增营收或新扣款证据。工具把用户 prompt 与 Token 发往 `api.acedata.cloud`，仅向 agent 返回过滤后的结果，不返回原始请求和身份字段。测试均 Mock 收费 HTTP，不把安装、测试次数当用户或收入。

[源码](https://github.com/AceDataCloud/SunoCrewAI) · [反馈](https://github.com/AceDataCloud/SunoCrewAI/issues) · dev@acedata.cloud
