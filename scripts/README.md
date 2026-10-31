# 开发与维护命令

以下命令在仓库根目录执行，先安装 `requirements-dev.txt`。

| 命令 | 作用 |
| --- | --- |
| `python scripts/validate.py` | 完整依赖、素材、Ruff、测试、覆盖率和固定评测门槛 |
| `powershell -File scripts/test.ps1` | 独立测试临时目录，成功后清理 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/clean_workspace.ps1` | 预览缓存清理；`-Apply` 执行，`-BuildCache` 包含打包中间文件 |
| `python scripts/build_desktop.py` | 构建 Windows 便携目录与公开 ZIP |
| `python scripts/build_portable.py --output artifacts/local/source-snapshot.zip` | 创建可审核源码快照；不等同包含运行环境的客户端 |
| `python scripts/healthcheck.py` | 依赖和应用入口检查 |
| `python scripts/lock_runtime.py --common` | 核对依赖约束 |
| `python scripts/build_knowledge.py --help` | 知识构建、审核与校验参数 |
| `python scripts/audit_demo_sources.py` | 演示素材来源与完整性审核 |
| `python scripts/check_docs.py` | 检查公开 Markdown 本地文件链接，不访问外部网站 |
| `python scripts/discover_cc_wardrobe.py --help` | 演示素材发现参数 |
| `python scripts/download_cc_wardrobe.py --help` | 素材下载参数 |

素材发现和下载需要网络；默认验证使用固定本地资料。配置与数据库保护规则见[目录维护说明](../docs/development/REPOSITORY.md)。
