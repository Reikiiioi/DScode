import base64
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime
import requests
from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live


try:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

DEFAULT_TOKEN = "TOKEN"
TOKEN = os.environ.get("DEEPSEEK_TOKEN", DEFAULT_TOKEN).strip()
BASE_URL = "https://chat.deepseek.com"
WASM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sha3_wasm_bg.wasm")
WASM_URL = "https://fe-static.deepseek.com/chat/static/sha3_wasm_bg.7b9ca65ddd.wasm"

MAIN = "\033[38;2;77;107;254m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

SYSTEM_PROMPT = ""

_SESSION = requests.Session()
_SOLVER = None
console = Console(file=sys.stdout, force_terminal=True, legacy_windows=False)

def preprocess_markdown(text: str) -> str:
    if not text:
        return ""
    lines = text.split("\n")
    new_lines = []
    in_math = False
    for line in lines:
        stripped = line.strip()
        if stripped == "$$":
            if not in_math:
                in_math = True
                new_lines.append("```latex")
            else:
                in_math = False
                new_lines.append("```")
        elif stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 2:
            content = stripped[2:-2].strip()
            new_lines.append("```latex")
            new_lines.append(content)
            new_lines.append("```")
        else:
            new_lines.append(line)
    text = "\n".join(new_lines)

    text = re.sub(r"^(\s*[-*+]\s+)\[ \]", r"\1☐", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*[-*+]\s+)\[[xX]\]", r"\1☑", text, flags=re.MULTILINE)

    alerts = {
        "NOTE": "ℹ️ **Note**:",
        "TIP": "💡 **Tip**:",
        "IMPORTANT": "❗ **Important**:",
        "WARNING": "⚠️ **Warning**:",
        "CAUTION": "🛑 **Caution**:",
    }
    for tag, replacement in alerts.items():
        text = re.sub(rf"^>\s*\[!{tag}\]\s*", f"> {replacement} ", text, flags=re.MULTILINE | re.IGNORECASE)

    return text


def ensure_wasm():
    if os.path.isfile(WASM_PATH) and os.path.getsize(WASM_PATH) > 1000:
        return WASM_PATH
    r = _SESSION.get(WASM_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    with open(WASM_PATH, "wb") as f:
        f.write(r.content)
    return WASM_PATH

class PowSolver:
    def __init__(self, wasm_path):
        try:
            from wasmtime import Engine, Instance, Module, Store
            self.engine = Engine()
            self.store = Store(self.engine)
            module = Module.from_file(self.engine, wasm_path)
            inst = Instance(self.store, module, [])
            exp = inst.exports(self.store)
            self.memory = exp["memory"]
            self.wasm_solve = exp["wasm_solve"]
            self.add_stack = exp["__wbindgen_add_to_stack_pointer"]
            self.malloc = exp["__wbindgen_export_0"]
            self.mode = "wasmtime"
        except Exception:
            self.mode = "node"

    def write_wasm(self, s):
        data = s.encode("utf-8")
        ptr = int(self.malloc(self.store, len(data), 1)) & 0xFFFFFFFF
        base = self.memory.data_ptr(self.store)
        for i, b in enumerate(data):
            base[ptr + i] = b
        return ptr, len(data)

    def solve(self, challenge):
        if self.mode == "wasmtime":
            prefix = f"{challenge['salt']}_{challenge['expire_at']}_"
            retptr = int(self.add_stack(self.store, -16)) & 0xFFFFFFFF
            c_ptr, c_len = self.write_wasm(challenge["challenge"])
            p_ptr, p_len = self.write_wasm(prefix)
            self.wasm_solve(self.store, retptr, c_ptr, c_len, p_ptr, p_len, float(challenge["difficulty"]))
            base = self.memory.data_ptr(self.store)
            status = int.from_bytes(bytes([base[retptr + i] for i in range(4)]), "little", signed=True)
            answer = struct.unpack_from("<d", bytes([base[retptr + 8 + i] for i in range(8)]))[0]
            self.add_stack(self.store, 16)
            if status != 1:
                raise RuntimeError(f"PoW status={status}")
            return int(answer)
        else:
            js_code = f"""
            const fs = require('fs');
            const mod = new WebAssembly.Module(fs.readFileSync({json.dumps(WASM_PATH)}));
            const inst = new WebAssembly.Instance(mod, {{}});
            const exp = inst.exports;
            function writeStr(s) {{
              const enc = new TextEncoder().encode(s);
              const ptr = exp.__wbindgen_export_0(enc.length, 1) >>> 0;
              new Uint8Array(exp.memory.buffer).set(enc, ptr);
              return [ptr, enc.length];
            }}
            const prefix = {json.dumps(challenge['salt'] + '_' + str(challenge['expire_at']) + '_')};
            const retptr = exp.__wbindgen_add_to_stack_pointer(-16) >>> 0;
            const [c_ptr, c_len] = writeStr({json.dumps(challenge['challenge'])});
            const [p_ptr, p_len] = writeStr(prefix);
            exp.wasm_solve(retptr, c_ptr, c_len, p_ptr, p_len, {challenge['difficulty']});
            const dv = new DataView(exp.memory.buffer);
            const ans = dv.getFloat64(retptr + 8, true);
            console.log(Math.round(ans));
            """
            out = subprocess.check_output(["node", "-e", js_code], text=True).strip()
            return int(out)

def get_solver():
    global _SOLVER
    if _SOLVER is None:
        _SOLVER = PowSolver(ensure_wasm())
    return _SOLVER

def make_pow_header(token, target_path="/api/v0/chat/completion"):
    r = _SESSION.post(
        f"{BASE_URL}/api/v0/chat/create_pow_challenge",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        },
        json={"target_path": target_path},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    ch = data["data"]["biz_data"]["challenge"]
    answer = get_solver().solve(ch)
    payload = {
        "algorithm": ch["algorithm"],
        "challenge": ch["challenge"],
        "salt": ch["salt"],
        "answer": answer,
        "signature": ch["signature"],
        "target_path": ch.get("target_path", target_path),
    }
    return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()

def make_headers(token, session_id=None, extra=None):
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/a/chat/s/{session_id}" if session_id else f"{BASE_URL}/",
        "Authorization": f"Bearer {token}",
        "x-client-platform": "web",
        "x-client-version": "1.8.0",
        "x-app-version": "20241129.1",
    }
    if extra:
        h.update(extra)
    return h

def create_chat_session(token):
    r = _SESSION.post(
        f"{BASE_URL}/api/v0/chat_session/create",
        headers=make_headers(token, None, {"Content-Type": "application/json"}),
        json={"character_id": None},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    biz = (data.get("data") or {}).get("biz_data") or {}
    session_id = (biz.get("chat_session") or {}).get("id") or biz.get("id")
    if not session_id:
        raise RuntimeError(f"Session error: {data}")
    return str(session_id)

def delete_chat_session(token, session_id):
    try:
        _SESSION.post(
            f"{BASE_URL}/api/v0/chat_session/delete",
            headers=make_headers(token, session_id, {"Content-Type": "application/json"}),
            json={"chat_session_id": session_id},
            timeout=15,
        )
    except Exception:
        pass

def stream_chat_completion(prompt, token=TOKEN, on_delta=None, search_enabled=False, on_search=None, sources_out=None):
    prompt = str(prompt).encode("utf-8", errors="replace").decode("utf-8")
    session_id = create_chat_session(token)

    def cleanup():
        threading.Thread(target=delete_chat_session, args=(token, session_id), daemon=True).start()

    try:
        pow_hdr = make_pow_header(token, "/api/v0/chat/completion")
        payload = {
            "chat_session_id": session_id,
            "parent_message_id": None,
            "model_type": "deepseek_chat",
            "prompt": prompt,
            "ref_file_ids": [],
            "thinking_enabled": False,
            "search_enabled": search_enabled,
            "source": None,
            "action": None,
            "preempt": False,
        }

        try:
            resp = _SESSION.post(
                f"{BASE_URL}/api/v0/chat/completion",
                headers=make_headers(token, session_id, {
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "x-ds-pow-response": pow_hdr,
                }),
                json=payload,
                timeout=120,
                stream=True,
            )
            resp.raise_for_status()
        except requests.HTTPError as e:
            body = e.response.text if e.response is not None else ""
            code = e.response.status_code if e.response is not None else "?"
            raise RuntimeError(f"HTTP {code}: {body[:400]}") from e

        full_text = []
        sources = []
        buf = b""
        search_shown = False

        def handle_frag(frag):
            nonlocal search_shown
            if not isinstance(frag, dict):
                return ""
            ftyp = frag.get("type")
            fcontent = frag.get("content") or ""
            if ftyp in ("SEARCH", "TOOL_SEARCH", "WEB_SEARCH") or (ftyp and "SEARCH" in str(ftyp)):
                if fcontent and on_search and not search_shown:
                    on_search(fcontent)
                    search_shown = True
                return ""
            elif ftyp == "RESPONSE" and fcontent:
                return fcontent
            return ""

        for chunk in resp.iter_content(chunk_size=128):
            if not chunk:
                continue
            buf += chunk
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                line = buf[:nl].decode("utf-8", "replace").rstrip("\r")
                buf = buf[nl + 1:]

                if not line.startswith("data: "):
                    continue
                raw_data = line[6:].strip()
                if not raw_data or raw_data == "[DONE]":
                    continue

                try:
                    obj = json.loads(raw_data)
                except Exception:
                    continue

                v = obj.get("v")
                p = obj.get("p")
                o = obj.get("o")
                delta = ""

                if isinstance(v, dict) and "response" in v:
                    for frag in (v["response"].get("fragments") or []):
                        delta += handle_frag(frag)
                elif o == "BATCH" and isinstance(v, list):
                    for item in v:
                        if not isinstance(item, dict):
                            continue
                        ip = item.get("p")
                        iv = item.get("v")
                        io = item.get("o")
                        if ip == "fragments" and io == "APPEND" and isinstance(iv, list):
                            for frag in iv:
                                delta += handle_frag(frag)
                        elif ip == "content" and isinstance(iv, str):
                            if on_search and not search_shown and ("Found" in iv or "found" in iv.lower() or "web pages" in iv.lower()):
                                on_search(iv)
                                search_shown = True
                elif p and isinstance(p, str) and p.endswith("/results") and isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            sources.append(item)
                elif p == "response/fragments" and isinstance(v, list):
                    for frag in v:
                        delta += handle_frag(frag)
                elif isinstance(p, str) and p.endswith("/content") and isinstance(v, str):
                    delta += v
                elif p is None and isinstance(v, str):
                    delta += v

                if delta:
                    full_text.append(delta)
                    if on_delta:
                        on_delta(delta)

        if sources_out is not None:
            sources_out.extend(sources)

        return "".join(full_text).strip()
    finally:
        cleanup()

def get_width():
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except Exception:
        return 80

def print_banner():
    cwd = os.getcwd()
    logo = [
        f"{MAIN}█████████{RESET}",
        f"{MAIN}██     ██{RESET}",
        f"{MAIN}██     ██{RESET}",
        f"{MAIN}█████████{RESET}",
    ]
    
    text_lines = [
        f"{BOLD}DeepSeek Code{RESET} {DIM}v1.0.3{RESET}",
        f"{DIM}DeepSeek-V4.1-Flash{RESET}",
        f"{DIM}{cwd}{RESET}",
        f"{DIM}Created by Reikiiioi (tg: @sypren){RESET}"
    ]
    print()
    for l, t in zip(logo, text_lines):
        print(f"  {l}   {t}")
    print()

def build_prompt(history):
    lines = [SYSTEM_PROMPT]
    recent = history[-10:] if len(history) > 10 else history
    for m in recent:
        role = m["role"]
        content = m["content"]
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
    lines.append("Assistant:")
    return "\n\n".join(lines)

def main():
    history = []
    print_banner()

    while True:
        size = shutil.get_terminal_size()
        w = size.columns
        line = "─" * w
        print(f"{DIM}{line}{RESET}")
        try:
            user_input = input(f"{BOLD}> {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{DIM}Exiting DeepSeek...{RESET}")
            break

        print(f"{DIM}{line}{RESET}")
        left = "? for shortcuts"
        right = "Thinking off (tab to toggle)"
        sp = " " * max(1, w - len(left) - len(right))
        print(f"{DIM}{left}{sp}{right}{RESET}\n")

        if not user_input:
            continue

        if user_input in ("?", "/?", "/help"):
            print(f"{MAIN}●{RESET} Shortcuts & Commands:")
            print(f"  {BOLD}?{RESET}               Show shortcuts")
            print(f"  {BOLD}/search <query>{RESET}  Search the web and ask DeepSeek")
            print(f"  {BOLD}/clear{RESET}          Clear screen and reprint banner")
            print(f"  {BOLD}/reset{RESET}          Clear conversation context")
            print(f"  {BOLD}/exit{RESET}           Exit DeepSeek\n")
            continue

        if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
            print(f"{DIM}Goodbye!{RESET}")
            break

        if user_input.lower() == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
            print_banner()
            continue

        if user_input.lower() == "/reset":
            history.clear()
            os.system("cls" if os.name == "nt" else "clear")
            print_banner()
            print(f"{MAIN}●{RESET} Conversation context cleared.\n")
            continue

        is_search = False
        query = user_input
        if user_input.startswith("/search") or user_input.startswith("/s ") or user_input == "/s":
            parts = user_input.split(maxsplit=1)
            if len(parts) == 1 or not parts[1].strip():
                print(f"{MAIN}●{RESET} {DIM}Usage: /search <query>{RESET}\n")
                continue
            is_search = True
            query = parts[1].strip()

        history.append({"role": "user", "content": query})
        prompt_str = build_prompt(history)

        search_shown = False

        def on_search(status_text):
            nonlocal search_shown
            m = re.search(r"(\d+)", status_text)
            if m:
                line = f"Found {m.group(1)} web pages"
            else:
                line = status_text
            if sys.stdout.isatty():
                sys.stdout.write(f"\r\033[K  {DIM}{line}{RESET}\n")
            else:
                sys.stdout.write(f"  {DIM}{line}{RESET}\n")
            sys.stdout.flush()
            search_shown = True

        time_sent = datetime.now()
        start_perf = time.perf_counter()

        if is_search:
            if sys.stdout.isatty():
                sys.stdout.write(f"{MAIN}—{RESET} {DIM}Searching the web...{RESET}")
                sys.stdout.flush()

        accumulated = []
        try:
            if sys.stdout.isatty():
                with Live(console=console, refresh_per_second=10, vertical_overflow="visible") as live:
                    def on_delta(chunk):
                        accumulated.append(chunk)
                        current_text = "".join(accumulated)
                        live.update(Markdown(preprocess_markdown(current_text), code_theme="monokai", hyperlinks=True))

                    full_response = stream_chat_completion(
                        prompt=prompt_str,
                        token=TOKEN,
                        on_delta=on_delta,
                        search_enabled=is_search,
                        on_search=on_search if is_search else None,
                    )
            else:
                def on_delta(chunk):
                    accumulated.append(chunk)

                full_response = stream_chat_completion(
                    prompt=prompt_str,
                    token=TOKEN,
                    on_delta=on_delta,
                    search_enabled=is_search,
                    on_search=on_search if is_search else None,
                )
                console.print(Markdown(preprocess_markdown(full_response), code_theme="monokai", hyperlinks=True))

            end_perf = time.perf_counter()
            time_received = datetime.now()
            duration_sec = end_perf - start_perf

            sent_str = time_sent.strftime("%H:%M:%S")
            recv_str = time_received.strftime("%H:%M:%S")
            dur_str = f"{duration_sec:.2f}s"

            console.print()
            console.print(
                f"[dim]⏱  Sent: [bold #4d6bfe]{sent_str}[/bold #4d6bfe]  │  "
                f"Received: [bold #4d6bfe]{recv_str}[/bold #4d6bfe]  │  "
                f"Duration: [bold green]{dur_str}[/bold green][/dim]"
            )
            console.print()
            history.append({"role": "assistant", "content": full_response})
        except Exception as e:
            print(f"\n{DIM}Error: {e}{RESET}\n")

if __name__ == "__main__":
    os.system("cls" if os.name == "nt" else "clear")
    main()
