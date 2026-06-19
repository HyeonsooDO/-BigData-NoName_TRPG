from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from tkinter import font as tkfont

from generate_image import IllustrationGenerator

from story_logic import (
    DEFAULT_HOST,
    DEFAULT_MODEL_NAME,
    DEFAULT_OLLAMA_URL,
    DEFAULT_PORT,
    DEFAULT_SECRET_TOKEN,
    StoryEngine,
    ThreadedServer,
)


class ImageRequestHandler(BaseHTTPRequestHandler):
    generator: IllustrationGenerator
    secret_token: str
    log: callable

    def do_POST(self):
        if self.path != "/generate-image":
            self.send_error(404)
            return

        auth = self.headers.get("Authorization", "")
        token = self.headers.get("X-Secret-Token", "")
        if self.secret_token and auth != f"Bearer {self.secret_token}" and token != self.secret_token:
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 1024 * 1024:
                raise ValueError("요청 본문 크기가 올바르지 않습니다.")

            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt:
                raise ValueError("prompt가 필요합니다.")

            image_bytes = self.generator.generate(
                prompt=prompt,
                negative_prompt=str(payload.get("negative_prompt", "")) or None,
                width=int(payload.get("width", 768)),
                height=int(payload.get("height", 768)),
                steps=int(payload.get("steps", 25)),
                guidance_scale=float(payload.get("guidance_scale", 7.0)),
                seed=payload.get("seed"),
                remove_bg=bool(payload.get("remove_background", True)),
            )

            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(image_bytes)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(image_bytes)
            self.log(f"[image] generated: {len(image_bytes)} bytes")
        except Exception as exc:
            self.log(f"[image] error: {exc}")
            self._send_json(500, {"ok": False, "error": str(exc)})

    def _send_json(self, status: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        return


class ImageAPIServer:
    def __init__(self, generator: IllustrationGenerator, log):
        self.generator = generator
        self.log = log
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self, host: str, port: int, secret_token: str):
        if self.httpd is not None:
            return

        handler = type(
            "ConfiguredImageRequestHandler",
            (ImageRequestHandler,),
            {
                "generator": self.generator,
                "secret_token": secret_token,
                "log": staticmethod(self.log),
            },
        )

        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.log(f"[image] server started: http://{host}:{port}/generate-image")

    def stop(self):
        if self.httpd is None:
            return
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd = None
        self.thread = None
        self.log("[image] server stopped")


def get_preferred_korean_font(size=10):
    root = tk._default_root
    families = set(tkfont.families(root)) if root else set()
    candidates = [
        "Malgun Gothic",
        "맑은 고딕",
        "Noto Sans CJK KR",
        "Noto Sans KR",
        "NanumGothic",
        "나눔고딕",
        "Segoe UI",
        "TkDefaultFont",
    ]
    family = next((f for f in candidates if f in families), "TkDefaultFont")
    return (family, size)


class ServerGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("스토리 서버")
        self.root.geometry("1180x820")
        self.root.minsize(980, 680)

        self.ui_font = get_preferred_korean_font(10)
        self.text_font = get_preferred_korean_font(10)

        self.queue: queue.Queue = queue.Queue()
        self.engine = StoryEngine(log=self._enqueue_log)
        self.server = ThreadedServer(self.engine, log=self._enqueue_log)
        self.image_generator = IllustrationGenerator()
        self.image_server = ImageAPIServer(self.image_generator, self._enqueue_log)

        self.host_var = tk.StringVar(value=DEFAULT_HOST)
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.image_port_var = tk.StringVar(value=str(DEFAULT_PORT + 1))
        self.token_var = tk.StringVar(value=DEFAULT_SECRET_TOKEN)
        self.ollama_var = tk.StringVar(value=DEFAULT_OLLAMA_URL)
        self.model_var = tk.StringVar(value=DEFAULT_MODEL_NAME)
        self.status_var = tk.StringVar(value="중지됨")

        self._build_ui()
        self._poll_queue()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except Exception:
            pass
        for name in ["TLabel", "TButton", "TEntry", "TLabelframe.Label", "TCombobox"]:
            style.configure(name, font=self.ui_font)

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.LabelFrame(self.root, text="서버 설정", padding=10)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        for i in range(6):
            top.columnconfigure(i, weight=1)

        self._entry(top, "호스트", self.host_var, 0, 0)
        self._entry(top, "포트", self.port_var, 0, 1)
        self._entry(top, "이미지 포트", self.image_port_var, 0, 2)
        self._entry(top, "토큰", self.token_var, 0, 3, show="*")
        self._entry(top, "Ollama URL", self.ollama_var, 0, 4)
        self._entry(top, "모델명", self.model_var, 0, 5)

        actions = ttk.Frame(top)
        actions.grid(row=2, column=0, columnspan=6, sticky="e", pady=(8, 0))
        self.start_btn = ttk.Button(actions, text="서버 시작", command=self.start_server)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(actions, text="서버 중지", command=self.stop_server, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))

        body = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        log_frame = ttk.LabelFrame(body, text="로그", padding=8)
        log_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = ScrolledText(log_frame, wrap="word", font=self.text_font, state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")

        right = ttk.LabelFrame(body, text="세션", padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(3, weight=2)

        toolbar = ttk.Frame(right)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(toolbar, text="새로고침", command=self.refresh_sessions).pack(side="left")
        ttk.Button(toolbar, text="선택 세션 삭제", command=self.delete_session).pack(side="left", padx=(6, 0))

        self.session_list = tk.Listbox(right, font=self.text_font, exportselection=False)
        self.session_list.grid(row=1, column=0, sticky="nsew")
        self.session_list.bind("<<ListboxSelect>>", self.show_selected_session)

        ttk.Label(right, text="세션 미리보기").grid(row=2, column=0, sticky="w", pady=(8, 4))
        self.preview_text = ScrolledText(right, wrap="word", font=self.text_font, state="disabled")
        self.preview_text.grid(row=3, column=0, sticky="nsew")

        status = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

    def _entry(self, parent, label, var, row, column, show=None):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w")
        ttk.Entry(parent, textvariable=var, show=show, font=self.ui_font).grid(
            row=row + 1, column=column, sticky="ew", padx=(0, 8)
        )

    def _enqueue_log(self, message: str):
        self.queue.put(("log", message))

    def _append_log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_preview(self, text: str):
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", text)
        self.preview_text.configure(state="disabled")

    def start_server(self):
        try:
            host = self.host_var.get().strip() or DEFAULT_HOST
            port = int(self.port_var.get().strip())
            image_port = int(self.image_port_var.get().strip())
        except ValueError:
            messagebox.showwarning("입력 오류", "포트는 숫자여야 합니다.")
            return

        self.engine.set_model_config(
            ollama_url=self.ollama_var.get().strip() or DEFAULT_OLLAMA_URL,
            model_name=self.model_var.get().strip() or DEFAULT_MODEL_NAME,
        )
        try:
            token = self.token_var.get().strip() or DEFAULT_SECRET_TOKEN
            self.server.start(host, port, token)
            self.image_server.start(host, image_port, token)
        except Exception as exc:
            messagebox.showerror("시작 실패", str(exc))
            return

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set(f"실행 중 - 스토리 {host}:{port} / 이미지 {host}:{image_port}")
        self.refresh_sessions()

    def stop_server(self):
        self.server.stop()
        self.image_server.stop()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_var.set("중지됨")

    def refresh_sessions(self):
        self.session_list.delete(0, "end")
        with self.engine.sessions_lock:
            keys = list(self.engine.sessions.keys())
        for key in keys:
            self.session_list.insert("end", key)

    def show_selected_session(self, _event=None):
        sel = self.session_list.curselection()
        if not sel:
            self._set_preview("")
            return
        session_id = self.session_list.get(sel[0])
        with self.engine.sessions_lock:
            state = self.engine.sessions.get(session_id)
        if not state:
            self._set_preview("")
            return
        text = (
            f"세션 ID: {state.session_id}\n"
            f"플레이어: {state.player_name} ({state.player_gender})\n"
            f"장르: {state.genre}\n"
            f"씬: {state.scene_no}\n"
            f"턴: {state.turn_count}/{state.turn_limit}\n\n"
            f"현재 장면:\n{state.scene_text}\n\n"
            f"최근 대화:\n"
        )
        for item in state.history[-10:]:
            text += f"- {item.get('speaker', '')}: {item.get('text', '')}\n"
        self._set_preview(text)

    def delete_session(self):
        sel = self.session_list.curselection()
        if not sel:
            return
        session_id = self.session_list.get(sel[0])
        self.engine.delete_session(session_id)
        self.refresh_sessions()
        self._set_preview("")
        self._append_log(f"[session] deleted: {session_id}")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                    self.refresh_sessions()
                    self.show_selected_session()
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)

    def on_close(self):
        try:
            self.server.stop()
            self.image_server.stop()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    ServerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
