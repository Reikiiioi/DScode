<div align="center">

# ⚡ DeepSeek Code

**A sleek, high-performance terminal CLI client for DeepSeek.**

Live streaming • Markdown & LaTeX rendering • Real-time Web Search • Native PoW solver

[🇬🇧 English](README.md) • [🇷🇺 Русский](github/README.md)

</div>

---

## 📖 Overview

**DeepSeek Code** is a lightweight, terminal-based AI assistant powered by DeepSeek (`chat.deepseek.com`). Built for developers who live in the command line, it brings a modern terminal user interface (TUI) with real-time token streaming, rich syntax-highlighted markdown, live web search, and automated Proof-of-Work (PoW) verification.

No paid API keys, external proxy services, or local server setups (`no localhost`) are required.

```
  █████████   DeepSeek Code v1.0.3
  ██     ██   DeepSeek-V4.1-Flash
  ██     ██   /path/to/project
  █████████   Created by Reikiiioi (tg: @sypren)
```

---

## ✨ Features

- ⚡ **Real-Time Streaming**: Instant token streaming rendered at 10 FPS with zero lag.
- 🎨 **Rich Terminal Markdown**:
  - Syntax-highlighted code blocks powered by the `monokai` theme.
  - Interactive checklists (`- [ ]` $\rightarrow$ `☐`, `- [x]` $\rightarrow$ `☑`).
  - LaTeX math expressions (`$$...$$`) converted into clean, readable code blocks.
  - GitHub-style callouts (`[!NOTE]`, `[!TIP]`, `[!IMPORTANT]`, `[!WARNING]`, `[!CAUTION]`) styled with contextual icons.
- 🌐 **Deep Web Search**: Use `/search <query>` to enable DeepSeek's real-time web search engine with live status updates (`Found N web pages`).
- 🛡️ **Automated Proof-of-Work (PoW) Solver**:
  - Automatically fetches `sha3_wasm_bg.wasm` from DeepSeek CDN on first run.
  - Solves cryptographic challenges in-process via `wasmtime` for maximum speed.
  - Graceful zero-configuration fallback to `Node.js` if `wasmtime` is unavailable.
- 🧹 **Zero Cloud Clutter**: Temporary chat sessions are generated on the fly and automatically purged in the background, keeping your web UI conversation history completely clean.
- ⏱️ **Latency & Telemetry**: Displays exact dispatch time, completion time, and request duration (`⏱ Sent: 21:04:12 │ Received: 21:04:15 │ Duration: 2.84s`).
- 🖥️ **Full Cross-Platform Support**: Seamless ANSI color and UTF-8 handling on Windows (VT mode), macOS, and Linux.

---

## 🚀 Getting Started

### 1. Prerequisites

- **Python 3.8+**
- **WebAssembly Engine** (choose either):
  - `wasmtime` (recommended, installs via pip)
  - OR **Node.js** installed on your system (fallback)

### 2. Installation

Clone or copy the files into your working directory and install the required Python packages:

```bash
pip install requests rich wasmtime
```

*(If you don't install `wasmtime`, ensure `node` is accessible in your system `PATH`.)*

### 3. Authentication

DeepSeek Code uses your personal user token from `chat.deepseek.com`.

#### How to get your token:
1. Open [chat.deepseek.com](https://chat.deepseek.com) in your browser and log in.
2. Press `F12` (or right-click $\rightarrow$ **Inspect**) to open Developer Tools.
3. Go to **Application** (or **Storage**) $\rightarrow$ **Local Storage** $\rightarrow$ `https://chat.deepseek.com`.
4. Find the key named `userToken` (or inspect network requests in the **Network** tab and copy the `Authorization: Bearer <token>` value).
5. Copy the token string.

#### Setting the token:

You can supply your token via an environment variable or directly in the code:

**Option A: Environment Variable (Recommended)**

- **Linux / macOS:**
  ```bash
  export DEEPSEEK_TOKEN="your_token_here"
  ```
- **Windows (PowerShell):**
  ```powershell
  $env:DEEPSEEK_TOKEN="your_token_here"
  ```
- **Windows (Command Prompt):**
  ```cmd
  set DEEPSEEK_TOKEN=your_token_here
  ```

**Option B: In-Code Configuration**

Edit `DeepSeekCode.py` and replace the placeholder:
```python
DEFAULT_TOKEN = "your_token_here"
```

---

## 💻 Usage

Run the script from your terminal:

```bash
python DeepSeekCode.py
```

### Interactive Commands

| Command | Shortcut | Description |
| :--- | :--- | :--- |
| `?` / `/?` / `/help` | `?` | Displays shortcut and command reference. |
| `/search <query>` | `/s <query>` | Queries DeepSeek with real-time web search enabled. |
| `/clear` | — | Clears the terminal screen and reprints the banner. |
| `/reset` | — | Clears conversation context history and resets screen. |
| `/exit` / `/quit` | `exit` / `quit` | Exits the CLI application. |

---

## 🛠️ Architecture & How It Works

```
┌───────────────────────┐
│     User Terminal     │
│   (Prompt / Commands) │
└───────────┬───────────┘
            │
            ▼
┌────────────────────────────────────────────────────────┐
│                   DeepSeekCode.py                      │
│                                                        │
│  1. Request PoW Challenge ──► /api/v0/chat/create_pow  │
│  2. Compute Solution      ──► wasmtime / node (WASM)   │
│  3. Create Session        ──► /api/v0/chat_session/create│
│  4. Stream Completion     ──► /api/v0/chat/completion  │
│  5. Background Cleanup    ──► /api/v0/chat_session/delete
└───────────┬────────────────────────────────────────────┘
            │
            ▼
┌───────────────────────┐
│  Rich Markdown Stream │
│  (10 FPS Live Render) │
└───────────────────────┘
```

1. **PoW Resolution**: When initiating a request, DeepSeek requires solving a cryptographic challenge. The script downloads `sha3_wasm_bg.wasm` and computes the target hash answer using `wasmtime` (or Node.js) and sends the signature in the `x-ds-pow-response` header.
2. **Conversation Context**: The CLI retains the last 10 messages within the active session for multi-turn dialogue.
3. **Session Purging**: To prevent thousands of ephemeral requests from polluting your web interface at `chat.deepseek.com`, sessions are automatically and asynchronously deleted after completion.

---

## ⚙️ Configuration & Customization

You can adjust internal parameters in `DeepSeekCode.py`:

- **System Prompt**: Modify `SYSTEM_PROMPT` to tailor the assistant's persona or default instructions.
- **Context Depth**: Default history length is set to the last 10 turns (`history[-10:]`).
- **Code Highlighting Theme**: Default is `monokai`, customizable via `Markdown(..., code_theme="...")`.

---

## ❓ Troubleshooting

- **`RuntimeError: PoW status=...`**: Ensure `wasmtime` is installed or Node.js is present on your system path.
- **`HTTP 401: Unauthorized`**: Your `DEEPSEEK_TOKEN` has expired or is invalid. Refresh your token from browser cookies / local storage.
- **Characters or formatting look broken on Windows**: DeepSeek Code automatically activates Virtual Terminal Mode on Windows. If using standard CMD, ensure your font supports Unicode (e.g. Consolas, Cascadia Code, or Windows Terminal).

---

## 👤 Author

- **Author**: Reikiiioi
- **Telegram**: [@sypren](https://t.me/sypren)

---

## 📄 License

This project is licensed under the MIT License — see the LICENSE file for details.
