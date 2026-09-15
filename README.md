# editPDFbyAI

**English** | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

Edit PDFs with natural language. Describe a change, inspect a real PDF preview, then apply and export. Powered by your own DeepSeek API key.

PDF processing runs on your computer. The interface opens in your browser; no cloud PDF server or subscription is required.

## Download and run

Download the archive for your system from [Releases](https://github.com/smartgalilei/editPDFbyAI/releases):

| Platform | Package |
| --- | --- |
| Mac with Apple Silicon | macOS-arm64 |
| Mac with Intel processor | macOS-x64 |
| Windows x64 | Windows-x64 |

Extract the **entire archive**, then launch `editPDFbyAI` on Mac or `editPDFbyAI.exe` on Windows. Python and the PDF libraries are included. Keep the terminal window open while editing; close it or press Ctrl+C to quit. Export changes before quitting.

The initial macOS builds target macOS 15 or later; Windows builds target Windows 10/11 x64. Windows ARM is not a native build target. Initial binaries are unsigned and not Apple-notarized, so operating systems may show developer verification warnings. Source installation is available below; do not disable system security protections.

## Use

1. Open a PDF or try the fictional sample document.
2. Open **API settings**, enter your own DeepSeek API key, and choose a model.
3. Select the current page, all pages, or a page range.
4. Describe your change and click **Preview changes**.
5. Compare before and after, apply the result, then **Export PDF**.

Examples:

- “Change the delivery date to November 1, 2026. Keep everything else unchanged.”
- “Center the title horizontally on page 1.”
- “Change the title color to dark blue and its rectangular background to pale yellow.”
- “Rotate page 2 clockwise by 90 degrees.”

Undo and redo keep up to ten applied versions. Your original file is never overwritten. The interface is AI-only; there is no manual editing panel.

## Editing behavior and limits

Text replacement reuses the PDF's existing font resources and drawing state. Alignment supports left, center, right, top, middle and bottom relative to the original text area, page or a specified rectangle. Text and solid rectangular backgrounds can be recolored.

Missing **digits** are approximated automatically when a compatible embedded Bold font and a matching Regular digit set are available. Generated glyphs are approximations, not the original font design. Existing glyphs are retained. The preview and document notice identify approximated glyphs; unsupported fonts or insufficient references still cause the edit to be rejected.

This is a fixed-layout editor, not an unrestricted word processor. Unsupported encodings, overlapping objects, mixed-style replacements, insufficient space and unexpected visual changes are rejected. It does not provide OCR for scanned text. Images, gradients and complex transparent backgrounds cannot be recolored. Editing may invalidate digital signatures. Text deletion is not comprehensive sanitization of hidden data.

Limit: 40 MB, 300 pages, 60 operations per plan. Pages sent for AI analysis are limited to roughly 100,000 characters. All document state lives in service memory and is lost when the process exits. Multiple tabs share one session.

## Privacy and API costs

PDF import, rendering, editing and export run locally. AI requests send **all extracted text from the selected pages**, coordinates and your instructions to `https://api.deepseek.com/chat/completions`. The PDF binary and page images are not sent. DeepSeek processes the request under your account terms and bills your account.

The key is kept only in local service memory, never written to configuration files or browser storage. You can also supply `DEEPSEEK_API_KEY` as an environment variable. There is no telemetry. The service binds only to `127.0.0.1`, uses a random session token, and checks Host and Origin. Do not expose it to a LAN or the internet or share its session URL.

## Run from source

Install Python 3.11, download the source, then double-click `start-macos.command` or `start-windows.bat`. The first run requires internet access to install dependencies.

Mac terminal:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe server.py
```

## Development

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -q
python -m pip install pyinstaller==6.22.3
python scripts/build_desktop.py
python scripts/smoke_desktop.py
```

Build on each target OS; PyInstaller is not a cross-compiler. GitHub Actions builds the three packages and checks startup, static assets, PDF rendering and export from the packaged executable. Tests use generated fictional documents and mocked AI responses. These checks do not establish live DeepSeek availability; live calls require a valid key and balance.

## License

Copyright (c) 2026 smartgalilei. Licensed under **GNU AGPL version 3**, see [LICENSE](LICENSE). Corresponding source is available in this repository and in each release source archive. Dependencies retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the license files included with each package.

PyMuPDF/MuPDF uses AGPL or a separate commercial license. This project uses the AGPL distribution. No commercial font files or real user PDFs are bundled.

Interaction inspiration: [EDITOR_KIM](https://github.com/kindsusu/EDITOR_KIM). This implementation does not copy its source code.
