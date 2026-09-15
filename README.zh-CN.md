# editPDFbyAI

[English](README.md) | **简体中文** | [日本語](README.ja.md)

用自然语言编辑 PDF。描述修改要求，查看真实 PDF 预览，确认后应用并导出。AI 使用你自己的 DeepSeek API Key。

PDF 在你的电脑上处理，操作界面在浏览器中打开，无需云端 PDF 服务。应用界面为英文，修改要求可以使用中文、英文或日文；具体理解效果取决于模型。

## 下载与启动

从 [Releases](https://github.com/smartgalilei/editPDFbyAI/releases) 下载对应版本：

| 系统 | 下载包 |
| --- | --- |
| Apple Silicon Mac（M 系列芯片） | macOS-arm64 |
| Intel Mac | macOS-x64 |
| Windows x64 | Windows-x64 |

**完整解压下载包**，Mac 启动 `editPDFbyAI`，Windows 启动 `editPDFbyAI.exe`。程序包含 Python 和 PDF 引擎，无需另行安装。启动后自动打开浏览器；使用期间请保留终端窗口。关闭窗口或按 Ctrl+C 停止服务，停止前请先导出修改。

初版 Mac 包面向 macOS 15 或更新版本；Windows 包面向 Windows 10/11 x64，暂不提供 Windows ARM 原生版。初版尚无代码签名或 Apple 公证，系统可能提示开发者未验证。也可以按下方说明从源码运行；请勿为安装而关闭系统安全防护。

## 使用步骤

1. 点击 **Open PDF** 打开文件，或用 **Try a sample document** 试用虚构示例。
2. 打开 **API settings**，输入自己的 DeepSeek API Key 并选择模型。
3. 在 **Scope** 选择当前页、全部页或指定页码。
4. 用自然语言描述修改，点击 **Preview changes**。
5. 比较修改前后，点击 **Apply changes** 应用，再用 **Export PDF** 导出。

提示词示例：

- “把交付日期改为 2026 年 11 月 1 日，其他内容保持不变。”
- “把第 1 页标题在页面中水平居中。”
- “把标题文字改成深蓝色，标题所在的矩形背景改成浅黄色。”
- “将第 2 页顺时针旋转 90 度。”

支持撤销、重做最近十次已应用修改。原文件不会被覆盖。界面只提供 AI 编辑，不提供手动编辑面板。

## 编辑效果与限制

文字替换复用 PDF 原有字体资源和绘制状态。可要求左、中、右、上、垂直居中、下对齐，参照原文字区域、整页或指定矩形区域；支持文字和纯色矩形背景改色。

**缺失数字默认自动近似补齐**：需要兼容的内嵌 Bold 字体和同族 Regular 完整数字作为参考。生成字形是近似结果，并不等于原字体设计；已有字形保持。预览和文档提示会注明近似字形。缺少参考或字体不支持时，仍会拒绝修改。

这是固定版式编辑器，不是任意 PDF 的无条件编辑工具。复杂编码、重叠对象、跨样式替换、空间不足或目标外发生意外视觉变化时，会拒绝方案。暂不支持 OCR 修改扫描件文字，也不支持图片、渐变或复杂透明背景改色。编辑可能使数字签名失效。删除文字并不等于完整清除文档隐藏数据。

限制：40 MB、300 页、每方案最多 60 项操作，单次 AI 分析约 100,000 字符。文档和历史仅保存在服务内存中，退出后丢失。多个标签页共享一个本机会话。

## 隐私与 API 费用

PDF 导入、渲染、编辑和导出都在本机完成。发送 AI 请求时，会将**所选页的全部提取文字**、坐标和修改要求发送到 `https://api.deepseek.com/chat/completions`，不发送 PDF 二进制文件或页面图片。DeepSeek 按你的账户条款处理和计费。

密钥只保存在本机服务内存，不写入配置文件或浏览器存储；也可通过 `DEEPSEEK_API_KEY` 环境变量提供。应用无遥测。服务仅监听 `127.0.0.1`，使用随机会话令牌并检查 Host 和 Origin。请勿将服务暴露至局域网或公网，也不要分享本机会话网址。

## 从源码运行

安装 Python 3.11，下载源码，然后双击 `start-macos.command` 或 `start-windows.bat`。首次启动需要网络安装依赖。

Mac 终端：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe server.py
```

## 开发与测试

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -q
python -m pip install pyinstaller==6.22.3
python scripts/build_desktop.py
python scripts/smoke_desktop.py
```

需要在各目标系统分别构建，PyInstaller 不能跨系统直接打包。GitHub Actions 构建三种下载包，检查打包后的程序启动、静态资源、PDF 渲染和导出。测试使用虚构文档和模拟 AI 返回，不代表已验证真实 DeepSeek 调用；真实调用需要有效密钥和余额。

## 开源许可证

Copyright (c) 2026 editPDFbyAI contributors。项目采用 **GNU AGPL 第 3 版**，见 [LICENSE](LICENSE)。对应源码可在本仓库及各 Release 的源码包中获取。第三方依赖保留各自许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和下载包内的许可证文件。

PyMuPDF/MuPDF 采用 AGPL 或单独商业授权；本项目使用 AGPL 发行版。不附带商业字体或真实用户 PDF。

交互方向参考 [EDITOR_KIM](https://github.com/kindsusu/EDITOR_KIM)，未复制其源码。
