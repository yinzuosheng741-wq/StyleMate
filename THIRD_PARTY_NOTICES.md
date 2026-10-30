# 第三方组件与素材

项目代码采用 MIT，见 [LICENSE](LICENSE)。第三方组件、知识和素材保留各自条款。

- **PySide6 / Qt 6.8.3 / Shiboken6**：动态库提供原生界面，未修改上游代码。PySide6 元数据列示 LGPL-3.0-only / GPL 许可选项；LGPL 及 GPL 文本见 `licenses/`。用户可以替换兼容的动态库并重新运行，不限制为调试此类修改进行的逆向工程。[Qt 许可说明](https://www.qt.io/development/open-source-lgpl-obligations)、[Qt 源代码](https://download.qt.io/archive/qt/6.8/6.8.3/single/)、[PySide6 源代码](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=6.8.3)。
- **Python**：PSF 许可，分发包附带构建环境提供的解释器许可文件。
- **其他依赖**：`licenses/runtime-dependencies.json` 记录实际构建环境的版本与许可字段，同时收集可获得的 LICENSE / COPYING / NOTICE。
- **演示图片**：Auckland Museum / Wikimedia Commons，CC BY 4.0。来源、作者和处理方式见 [素材说明](assets/demo/SOURCE.md) 与 manifest。
- **Open-Meteo / GeoNames**：天气和城市数据来源在设置和结果中标注，免费 API 限非商业使用，见[服务条款](https://open-meteo.com/en/pricing)。
- **知识摘要**：保留原站点权利、来源和适用范围，见 `data/knowledge/records.jsonl`。项目不提供原站点资料的整篇转载授权。

重新分发时保留第三方许可与素材来源；改动依赖或分发方式后重新检查上游条款。
