# 仓库目录与清理规则

| 目录/文件 | 职责 |
| --- | --- |
| `desktop.py`、`Start.cmd`、`Start.vbs` | Windows 客户端启动入口 |
| `stylemate/` | 应用代码，按桌面、服务、Agent、Skill、RAG、存储划分 |
| `evaluation/` | 可重放评测程序与版本化题集，见[说明](../../evaluation/README.md) |
| `tests/` | 当前功能与故障边界的回归测试 |
| `scripts/` | 验证、打包、知识构建与缓存清理，见[说明](../../scripts/README.md) |
| `data/knowledge/` | 可公开的内置知识与来源；其余 `data/` 为本机状态 |
| `assets/demo/`、`licenses/` | 演示素材及第三方许可 |
| `docs/` | [分类文档与导航](../README.md) |
| `artifacts/` | [基线、分类报告与本地验证输出](../../artifacts/README.md) |
| `dist/native/` | 当前公开 Windows 目录包 |
| `dist/personal/` | 本机自用客户端及私有数据，禁止提交 |
| `dist/TravelWardrobeAssistant-Windows-Portable.zip` | 当前公开便携 ZIP，不提交到源码仓库 |
| `.venv/`、`.env`、`.vscode/` | 本机依赖、服务密钥与编辑器配置，Git 忽略 |

## 日常清理

```powershell
# 先预览，只列出可重建缓存。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/clean_workspace.ps1
# 清理测试临时目录、pytest/Ruff/覆盖率缓存和源码字节码。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/clean_workspace.ps1 -Apply
# 额外清理 PyInstaller 中间文件；保留公开包和个人客户端。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/clean_workspace.ps1 -Apply -BuildCache
```

脚本限制目标在本仓库，拒绝链接/联接目录及受 Git 跟踪的内容。先停止正在执行的测试和构建再清理。脚本不处理 `.venv`、私有配置、衣柜数据库、照片、个人客户端或历史评测报告。

本次整理将本地旧诊断日志归档到 `artifacts/local/history-20261031.zip`，清除其中可重建的程序解压副本；公开历史证据保留在 `artifacts/reports/`。测试文件只有在对应功能确已移除且核对引用后才删除，不能为清爽或提高通过率删掉有效回归。

新增文档放入对应分类并更新导航；更新路径时检查 Markdown 链接、构建脚本和评测 manifest。正式发布通过 GitHub Actions/Releases 分发 Windows ZIP，源码仓库不堆积构建目录。
