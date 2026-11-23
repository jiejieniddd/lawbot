# CareerBot 首字延迟优化与本地验证

本次只修改本地代码，没有连接 `/opt/CareerBot` 或访问线上模型。没有改动向量生成、知识库、前端或检索排序。服务器的 40 秒延迟尚不能从本地模拟推断具体来源，上线后须用阶段日志定位。

## 请求到首字的实际链路

1. `RequestIdMiddleware` 记录请求到达时间和请求 ID；FastAPI 进行鉴权、参数校验、取得数据库 session。
2. `routers/v1/chat.py:chat` 校验会话归属、加载最近 6 条历史、保存用户消息、读取/更新偏好、解密当前供应商凭据。随后 `get_retriever` 读取嵌入配置，首次调用会加载索引，后续复用缓存。再加载简历、JD 和跨会话记忆。这些串行工作都在返回 StreamingResponse 前完成，计入 `request_setup` 和 HTTP 首字时间。
3. 同步 SSE 生成器通过 Starlette 的线程池执行；`run_agent_stream` 做输入安全检查、取得 checkpointer、编译图。图的阶段顺序为意图 → 分类 → 事实判断 → 改写 → 检索 → 准备回答。闲聊、模糊问题、越界、事实不足会走相应短路；固定追问直接输出。
4. 意图规则无法判断才请求模型。分类独占方向规则优先；现在无方向信号但已明确属于 CareerBot 的问题采用 general，多个方向冲突等不确定情形仍可请求模型。事实基线足够则跳过模型；短输入缺少方向/技术栈时直接保留追问，不再让模型尝试推翻该保护。长问题只在规则无法识别意图且启发式改写未命中时请求改写模型。
5. 检索阶段按需串行执行简历分析、技能差距、岗位匹配、面试追问和 search_kb；这些工具可能各自检索。它们不额外发聊天模型请求。实际 HybridRetriever 是 BM25 优先、无结果才做查询嵌入和向量检索。云端查询 embedding 仍可能发生；本次未更改 embedding 方式、超时或回退。
6. 有凭据时 prepare_answer 只组装提示词，随后调用 `complete_text_stream`。`_model_report_args` 是遗留辅助函数，当前主图没有调用它。收到首个非空文本后产出 token → `_sse` → StreamingResponse → Nginx → 浏览器 reader/onEvent。status 事件不是回答首字。
7. 生成后仍执行原有规则自检、引用处理和 guardrail，保存回答并输出 done；未通过删减安全检查来提速。现有“流后自检”不等于对已发到浏览器的内容进行撤回，本次没有改变这个边界。

## 串行请求、超时与失败行为

- 旧版首字前最多存在 4 次辅助请求（意图、分类、事实、改写），每次默认使用 `LLM_TIMEOUT_SECONDS=60`。并非每个问题都调用 4 次；很多规则本来就能短路。
- 新版辅助请求使用 `min(LLM_TIMEOUT_SECONDS, LLM_AUX_TIMEOUT_SECONDS)`，后者默认 8 秒，输出上限 256 tokens。失败、空 JSON 或无法解析时保留规则回退。明确传递 `num_retries=0`；之前代码未显式控制 SDK 重试。
- 回答默认请求超时仍为 60 秒，流闲置阈值 120 秒，总时长阈值 480 秒。闲置/总时长是在读取到 chunk 时检查的，并非可独立打断阻塞读取的硬定时器；阻塞期间依赖 SDK 的网络超时。因此不能承诺请求严格在这些秒数内结束。
- 旧版流式失败/空响应后再发一次完整的非流式请求，可能再次等待 60 秒。新版删除这次调用；首字前失败直接输出明确失败提示，清空失败回答的引用。部分文本已经发出时只追加一次中断提示，不重新发答案、不清空已经累计的文本。客户端把流中途异常转换为明确的截断异常，并关闭流资源。
- 兼容用的 `make_answer` 也删除非流式重试；主 `/chat` 使用的是 `_stream_answer_tokens`。
- 现有查询嵌入调用未显式传递超时，仍依赖嵌入 SDK；没有为提速改用假向量。纯检索 0.01–0.42 秒不能等同于包含首次索引加载和所有工具调用的端到端检索时间。
- 前端只对鉴权 401 刷新 token 后重发，不会自动重发已经部分生成的答案。前端 SSE 空闲看门狗为 180 秒。仓库 Nginx 已关闭代理缓冲，读取超时 3600 秒；API 保留 `X-Accel-Buffering: no`。

## 日志与长度档位

API 导入时配置独立 `lawbot.timing` INFO logger 和标准错误输出 handler，避免依赖 Uvicorn 是否配置应用 INFO logger。初始化幂等、不传播到 root，避免重复输出或打开 SDK 调试日志。

格式：`agent_timing request_id=... stage=... elapsed_ms=...`。阶段包括 request_setup、intent、classification、facts、rewrite、retrieval、prepare_answer、generation、first_token、response_generation。未执行的阶段不产生日志。

- first_token：从 HTTP middleware 收到请求到输出第一个非空 token，包括鉴权、数据库准备和索引初始化；不是浏览器实际绘制时间。失败提示也属于 token，应结合回答/错误情况分析。
- generation：从发起回答流到流结束，包括等待上游首字。
- response_generation：从请求到图生成结束，包括流后处理；不含随后保存消息的数据库提交和 done。
- 阶段日志只输出 ID、固定阶段名、耗时及布尔值，不输出密码、密钥、提示词和用户问题。供应商异常日志只记录异常类型，避免 SDK 异常体泄露请求。这里的日志规范针对新增耗时日志；原有独立 agent trace 文件机制未被重写。

生产 `.env` 可设置：

```dotenv
LLM_ANSWER_PROFILE=compact
LLM_AUX_TIMEOUT_SECONDS=8
```

默认 normal 保持 1600 tokens 和原提示词。compact 为 800 tokens，并请求简洁、完整的回答（尽量 300 字内，保留必要引用与安全提示）。显式 `LLM_ANSWER_MAX_TOKENS` 优先级更高；要使用档位的上限应移除该覆盖值。compact 主要减少生成总时长，不保证上游首字更快。达到输出上限仍显示“篇幅受限”提示。

## 可复现本地结果

基线 commit：`79200be8200244dc898a624c76adb8c1d1f28bf7`。原始汇总和既有失败用例名保存于 `eval/latency_results.json`。

`eval/latency_probe.py` 替换模型为每次固定等待 50ms 的本地模拟，使用 FakeRetriever，不连接网络，不读取线上凭据。每个场景先预热一次，再运行 5 次取首字中位数。测的是 agent 首字/失败反馈时间，不包含 HTTP、真实模型、真实检索和浏览器网络。

- 普通 Python 面试：模型请求 2 → 1（辅助分类 1 → 0）；首字 123.46 → 73.74ms。
- 明确后端面试：模型请求 1 → 1；首字 72.25 → 73.61ms，属于本地波动，没有声称提速。
- 简短“后端”输入：模型请求 1 → 1；首字 72.07 → 72.24ms。该现有规则路径会回答，并非所有短输入都会触发追问。
- 回答流失败：模型请求 2 → 1；首次失败反馈 122.82 → 72.35ms；删除了非流式重试。

在仓库根目录 PowerShell 中复现：

```powershell
New-Item -ItemType Directory -Force tmp | Out-Null
git show 79200be8200244dc898a624c76adb8c1d1f28bf7:packages/lawbot/lawbot/agent/graph.py | Out-File tmp/latency_graph_before.py -Encoding utf8
.venv/Scripts/python.exe eval/latency_probe.py --graph-file tmp/latency_graph_before.py
.venv/Scripts/python.exe eval/latency_probe.py
.venv/Scripts/python.exe -m pytest apps/api/tests/test_chat_latency.py apps/api/tests/test_llm_timeout.py apps/api/tests/test_chat_sse.py apps/api/tests/test_guardrail.py apps/api/tests/test_answer_prompts.py apps/api/tests/test_agent_tools.py -q -p no:cacheprovider
```

该定向测试组 52 passed，含 18 个新增回归用例。再加入 test_agent_stream.py、test_agent_memory.py 后，修改前为 42 passed / 39 failed；修改后为 60 passed / 39 failed，失败用例集合相同。旧测试包含大量法律领域断言，以及旧的非流式回退预期，不能据此宣称全套通过；本次没有删除或跳过这些测试。

## `/opt/CareerBot` 部署（尚未执行）

运行所需更新文件：

- `packages/lawbot/lawbot/agent/graph.py`
- `packages/lawbot/lawbot/llm/client.py`
- `apps/api/app/logging_config.py`（新增）
- `apps/api/app/main.py`
- `apps/api/app/middleware.py`
- `apps/api/app/routers/v1/chat.py`

同时保留 `.env.example`、`apps/api/tests/test_chat_latency.py`、`eval/latency_probe.py`、`eval/latency_results.json` 和本文以便复现。不要用 `.env.example` 覆盖生产 `.env`。无依赖、数据库 schema 或前端变更。

仓库 Dockerfile 把 Python 源码 COPY 进镜像，单纯 `docker compose restart api` 不会更新镜像里的代码。上传上述文件并按需编辑生产 `.env` 后：

```sh
cd /opt/CareerBot
docker compose build api
docker compose up -d --no-deps --force-recreate api
docker compose logs --since=5m api
```

这只构建/重建 API；不要执行全服务 `docker compose up --build`，不要在服务器运行前端 npm build。本次前端无改动，无需重新打包。若连 API 也在本机打包镜像，则传输并 `docker load` 对应 API 镜像后使用 `docker compose up -d --no-deps --no-build --force-recreate api`，确保镜像 tag 与服务器 compose 对应。

部署后发送一条普通面试题，通过响应头 X-Request-Id 关联日志，检查 first_token 和各阶段耗时。只有这些真实请求日志才能证明线上首字改善；本地模拟没有证明原来的 40 秒会降到某个数值。
