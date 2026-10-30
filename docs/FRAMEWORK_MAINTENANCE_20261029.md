# Agent 框架、验证与维护改进

日期：2026-10-29。延续现有 LangGraph 单 Agent 与确定性业务服务，不引入新的多 Agent 执行链。

## 官方项目参考

以下为当天 GitHub 页面显示的近似星数，仅用于选择调研对象，不代表技术质量或适配程度。

| 项目 | 页面近似星数 | 官方机制参考 | 本次取舍 |
| --- | ---: | --- | --- |
| [LangGraph](https://github.com/langchain-ai/langgraph) | 44.1k | [持久化与执行状态](https://docs.langchain.com/oss/python/langgraph/persistence) | 保留现有会话与确认写入边界；先补齐工具执行容量，不增加不需要的重放系统 |
| [AutoGen](https://github.com/microsoft/autogen) | 61.6k | [运行时与工具级观测](https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/framework/telemetry.html) | 借鉴运行和工具分层观测，使用本地内容白名单日志，不引入遥测服务依赖 |
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) | 20.9k | [禁止测试意外调用真实模型](https://pydantic.dev/docs/ai/guides/testing/)、[代码化评测](https://pydantic.dev/docs/ai/evals/evals/) | 测试默认禁止网络；脚本模型验证工具路径；固定评测增加可失败的质量门槛 |

这些机制按本项目约束重新实现，未复制上游实现或切换框架。AutoGen 作为观测参考，不新增其依赖。

## 执行与诊断

此前每次工具调用都创建独立线程池；调用超时后，旧线程可能仍执行，后续请求继续创建新线程。本次改为进程共享执行器，最多 4 个在途调用，不无限排队。容量耗尽立即返回 `tool_capacity_exhausted`，不启动处理函数，也不重试。只有处理函数实际结束或未开始的任务取消，才释放容量。

请求 ContextVar 继续跨线程传播；等待超时仍不接受迟到结果。已结束的网络异常仍只按原工具规格最多重试一次。写准备、确认和取消走原来的独立通道。

每个有效聊天请求分配独立 `run_id`，同时保存到回复与运行摘要。摘要包含耗时、逻辑工具调用数、实际工具尝试数、模型调用数、成功/失败/繁忙计数和结束状态。它不包含用户标识、会话标识、问题、回复、工具参数、工具返回或异常正文。日志位于 `data/desktop/agent-runs.log`，单文件 1 MiB、保留 3 个历史文件；只接入专用诊断 logger。自定义 observer 报错不会改变业务结果。

运行摘要是诊断信息，不是事务审计或持久执行检查点。`completed` 表示本次执行结束，`degraded` 表示存在降级或失败工具，并不代表回答事实正确。模型 SDK 调用、内部检索线程和其他进程不计入这 4 个只读工具名额。Python 仍不能强制终止正在运行的同步线程，进程退出可能等待它们结束。

## 统一验证

```powershell
python scripts/validate.py
```

同一命令用于本地、Linux CI、Windows CI 和 Windows 打包前置检查。依次执行已安装依赖一致性、声明约束校验、健康检查、素材审计、Ruff、编译、pytest、离线规则与 Agent/RAG 评测；每步最多 300 秒，失败即返回非零。Windows 临时目录置于项目根目录下的短路径，避免图片文件名与用户哈希叠加超过传统路径长度限制。

产物在 `artifacts/validation/`：各步日志、JUnit、Agent 覆盖率、最新评测报告、门槛结果和 `validation.json`。后者记录 Git revision、工作区是否有未提交修改，以及代码/测试/依赖/工作流指纹；验证结束会检查源码是否在运行期间变化。指纹覆盖 Python 与配置，不包含用户 `.env`。语料和题集指纹由评测报告单独记录。

测试夹具在 Python socket 的连接与解析入口阻断网络，且即使应用捕获异常进入降级，测试也会在结束时失败。它不会阻断子进程或 C 扩展自行发出的网络请求，不能称为操作系统网络隔离。正式在线评测仍使用显式 `--embedding-mode configured`，不混入离线 CI。

## 质量门槛与基线维护

`python -m evaluation.quality_gate` 重新执行现有 10 条规则用例、101 条 Agent/RAG/图用例，并读取已审核的 `artifacts/evaluation_manifest.json` 基线。

- 基线必须与当前语料、题集指纹一致；新报告必须保持相同的三个用例分母与 `offline_hash` 模式。
- 工具路由、图调用路径、图契约、确认保护、循环上限、记忆和安全固定用例必须全部通过。
- Recall@5、MRR@5、nDCG@5、困难负例排除率不得低于基线（仅允许 0.0001 的舍入差异）。
- 拒绝缺失值、布尔伪数值、NaN、改变分母或切换在线模型后进行直接比较。

低召回基线不是质量目标。当前 RAG Recall@5 约 0.2389，历史题集仍有范围冲突和证据覆盖不足；门槛只阻止已知固定用例退化，不宣称真实回答准确率提高。延迟和覆盖率作为诊断产物，不设置易受机器速度影响的固定耗时阈值。

语料或题集变更时：保留旧报告，在新文件名生成评测，人工检查完整分母、来源和范围冲突后更新 manifest，并解释基线变更。不要为了通过 CI 自动覆盖基线或删除失败题。

## 日常维护

GitHub Actions 上传验证产物，保留 14 天，同一分支只保留最新 CI。Windows 打包必须先通过完整验证。Dependabot 配置每周检查 Python 依赖、每月检查 Actions；Agent 栈和 Qt 栈分组，最多分别保留 3 和 2 个待处理 PR，不自动合并。依赖升级仍需检查 portable-lock 与两套安装入口的一致性。

客户端独立化后，默认 `requirements.txt` 包含业务依赖和 PySide6，desktop / portable 两个安装入口均引用它。继续使用已测试的 Pydantic 2.9.2、LangGraph 1.2.9 等版本；移除 Streamlit 依赖后，Windows / Python 3.12.4 的 `portable-lock.txt` 依赖闭包缩减为 70 个包，不混入开发测试和打包工具。这是特定平台快照，不当作跨平台锁文件。

运行 `python scripts/lock_runtime.py` 检查便携快照是否与安装环境一致。只有依赖更新完成并验证后，才使用 `--write` 显式重新生成；`--common` 验证共同依赖的声明约束，不改锁文件。

提交说明模板要求说明具体行为、验证证据、数据兼容性和真实服务联调范围。以上工作流与维护配置须推送至 GitHub 后才生效；本地检查不能替代 GitHub runner 的实际执行结果。

## 框架维护阶段验证结果（客户端独立化之前）

在本机 Windows / Python 3.12.4 运行 `python scripts/validate.py --output-dir artifacts/framework-validation`：全部步骤通过，385 项测试通过，Agent 模块语句覆盖率 92.04%。新增测试覆盖真实超时线程占用与恢复、容量耗尽拒绝、线程上下文隔离、异常释放、运行记录关联和隐私字段、日志去重与轮转配置、迟到计数、质量门槛的失效情况，以及离线网络阻断。

10 条规则用例和 101 条 Agent/RAG/图用例重新执行；固定安全与图契约通过率均为 1.0，RAG Recall@5 保持 0.2389，质量门槛通过，未调整题集分母或覆盖发布基线。完整验证记录、覆盖率和本轮评测位于 `artifacts/framework-validation/`，该目录为本地生成产物，不自动提交。

这是离线回归验证，没有替代真实模型、天气和在线 Embedding 的联调。原有 DashScope SDK 弃用提示仍存在，不影响本轮测试结果。
