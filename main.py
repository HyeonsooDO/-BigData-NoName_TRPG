import copy
import json
import queue
import socket
import struct
import threading
import uuid
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from tkinter import font as tkfont

#서버 IP
SERVER_HOST = ""
SERVER_PORT = 5767
SECRET_TOKEN = "change_this_to_a_long_random_string"


class NetworkError(Exception):
    pass


def recvall(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def send_json(sock, obj):
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    header = struct.pack("!I", len(payload))
    sock.sendall(header + payload)


def recv_json(sock):
    header = recvall(sock, 4)
    if header is None:
        return None
    length = struct.unpack("!I", header)[0]
    payload = recvall(sock, length)
    if payload is None:
        return None
    return json.loads(payload.decode("utf-8"))


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
        "Apple SD Gothic Neo",
        "Segoe UI",
        "TkDefaultFont",
    ]
    family = next((f for f in candidates if f in families), "TkDefaultFont")
    return (family, size)


class SetupDialog(tk.Toplevel):
    CHARACTER_FIELDS = [
        ("name", "이름"),
        ("role", "역할"),
        ("personality", "성격"),
        ("relationship", "플레이어와의 관계"),
        ("goal", "목표"),
        ("secret", "비밀/숨김 정보"),
        ("tone", "말투"),
    ]

    def __init__(self, master, initial_data=None):
        super().__init__(master)
        self.title("스토리 세팅")
        self.geometry("1040x760")
        self.minsize(900, 680)
        self.transient(master)
        self.grab_set()

        self.ui_font = get_preferred_korean_font(10)
        self.text_font = get_preferred_korean_font(10)

        data = initial_data or {}
        self.result = None
        self.characters = copy.deepcopy(data.get("characters") or [])
        self.current_index = None

        self.session_var = tk.StringVar(value=data.get("session_id") or f"story_{uuid.uuid4().hex[:6]}")
        self.player_var = tk.StringVar(value=data.get("player_name") or "주인공")
        self.player_gender_var = tk.StringVar(value=data.get("player_gender") or "남")
        self.genre_var = tk.StringVar(value=data.get("genre") or "학원 청춘물")
        self.turn_limit_var = tk.IntVar(value=int(data.get("turn_limit") or 6))
        self.field_vars = {key: tk.StringVar(value="") for key, _ in self.CHARACTER_FIELDS}
        self.char_gender_var = tk.StringVar(value="여")

        self._build_ui(data.get("world") or "")
        self._refresh_listbox()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.wait_visibility()
        self.focus_set()

    def _build_ui(self, world_text):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except Exception:
            pass
        for name in ["TLabel", "TButton", "TEntry", "TLabelframe.Label", "TRadiobutton"]:
            style.configure(name, font=self.ui_font)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.LabelFrame(self, text="기본 설정", padding=10)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        for i in range(5):
            top.columnconfigure(i, weight=1)
        self._entry(top, "세션 ID", self.session_var, 0, 0)
        self._entry(top, "플레이어 이름", self.player_var, 0, 1)
        self._entry(top, "장르", self.genre_var, 0, 2)
        ttk.Label(top, text="플레이어 성별").grid(row=0, column=3, sticky="w")
        g1 = ttk.Frame(top)
        g1.grid(row=1, column=3, sticky="w")
        ttk.Radiobutton(g1, text="남", value="남", variable=self.player_gender_var).pack(side="left")
        ttk.Radiobutton(g1, text="여", value="여", variable=self.player_gender_var).pack(side="left", padx=(8, 0))
        ttk.Label(top, text="씬 전환 턴 수").grid(row=0, column=4, sticky="w")
        tk.Spinbox(top, from_=3, to=20, textvariable=self.turn_limit_var, font=self.ui_font, width=8).grid(row=1, column=4, sticky="w")

        world_box = ttk.LabelFrame(self, text="세계관 설정", padding=10)
        world_box.grid(row=1, column=0, sticky="ew", padx=10)
        world_box.columnconfigure(0, weight=1)
        self.world_text = tk.Text(world_box, height=7, wrap="word", font=self.text_font, undo=True)
        self.world_text.grid(row=0, column=0, sticky="ew")
        self.world_text.insert("1.0", world_text)

        body = ttk.Frame(self, padding=(10, 10, 10, 10))
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text="등장인물 목록", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.char_listbox = tk.Listbox(left, font=self.text_font, exportselection=False)
        self.char_listbox.grid(row=0, column=0, sticky="nsew")
        self.char_listbox.bind("<<ListboxSelect>>", self._on_select_character)
        left_btns = ttk.Frame(left)
        left_btns.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(left_btns, text="추가", command=self.add_character).pack(side="left")
        ttk.Button(left_btns, text="삭제", command=self.remove_character).pack(side="left", padx=(6, 0))

        right = ttk.LabelFrame(body, text="등장인물 설정", padding=10)
        right.grid(row=0, column=1, sticky="nsew")
        for i in range(2):
            right.columnconfigure(i, weight=1)

        row = 0
        ttk.Label(right, text="성별").grid(row=row, column=0, columnspan=2, sticky="w")
        gender_frame = ttk.Frame(right)
        gender_frame.grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Radiobutton(gender_frame, text="남", value="남", variable=self.char_gender_var).pack(side="left")
        ttk.Radiobutton(gender_frame, text="여", value="여", variable=self.char_gender_var).pack(side="left", padx=(8, 0))
        row += 2

        for key, label in self.CHARACTER_FIELDS:
            ttk.Label(right, text=label).grid(row=row, column=0, columnspan=2, sticky="w")
            ttk.Entry(right, textvariable=self.field_vars[key], font=self.ui_font).grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
            row += 2

        ttk.Button(right, text="등장인물 설정 저장", command=self.save_current_character).grid(row=row, column=1, sticky="e", pady=(8, 0))

        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.grid(row=3, column=0, sticky="ew")
        ttk.Button(bottom, text="취소", command=self.cancel).pack(side="right")
        ttk.Button(bottom, text="시작", command=self.confirm).pack(side="right", padx=(0, 6))

    def _entry(self, parent, label, var, row, col):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w")
        ttk.Entry(parent, textvariable=var, font=self.ui_font).grid(row=row + 1, column=col, sticky="ew", padx=(0, 8))

    def _refresh_listbox(self):
        self.char_listbox.delete(0, "end")
        for idx, char in enumerate(self.characters, start=1):
            self.char_listbox.insert("end", f"{idx}. {char.get('name', '이름 없음')}")

    def _clear_form(self):
        self.current_index = None
        self.char_gender_var.set("여")
        for key in self.field_vars:
            self.field_vars[key].set("")

    def _on_select_character(self, _event):
        sel = self.char_listbox.curselection()
        if not sel:
            self._clear_form()
            return
        self.current_index = sel[0]
        char = self.characters[self.current_index]
        self.char_gender_var.set(char.get("gender") or "여")
        for key, _ in self.CHARACTER_FIELDS:
            self.field_vars[key].set(char.get(key, ""))

    def add_character(self):
        self.characters.append({
            "name": "",
            "gender": "여",
            "role": "",
            "personality": "",
            "relationship": "",
            "goal": "",
            "secret": "",
            "tone": "",
        })
        self._refresh_listbox()
        idx = len(self.characters) - 1
        self.char_listbox.selection_clear(0, "end")
        self.char_listbox.selection_set(idx)
        self._on_select_character(None)

    def remove_character(self):
        sel = self.char_listbox.curselection()
        if not sel:
            return
        del self.characters[sel[0]]
        self._refresh_listbox()
        if self.characters:
            next_idx = min(sel[0], len(self.characters) - 1)
            self.char_listbox.selection_set(next_idx)
            self._on_select_character(None)
        else:
            self._clear_form()

    def save_current_character(self):
        if self.current_index is None:
            messagebox.showwarning("안내", "먼저 등장인물을 선택하거나 추가해 주세요.", parent=self)
            return
        char = {key: self.field_vars[key].get().strip() for key, _ in self.CHARACTER_FIELDS}
        char["gender"] = self.char_gender_var.get().strip() or "여"
        if not char["name"]:
            messagebox.showwarning("안내", "등장인물 이름은 비워둘 수 없습니다.", parent=self)
            return
        self.characters[self.current_index] = char
        self._refresh_listbox()
        self.char_listbox.selection_clear(0, "end")
        self.char_listbox.selection_set(self.current_index)

    def confirm(self):
        if self.current_index is not None:
            self.save_current_character()
        valid_characters = []
        for item in self.characters:
            if item.get("name", "").strip():
                valid_characters.append(copy.deepcopy(item))
        if not valid_characters:
            messagebox.showwarning("안내", "등장인물을 최소 1명 이상 추가해 주세요.", parent=self)
            return
        self.result = {
            "session_id": self.session_var.get().strip() or f"story_{uuid.uuid4().hex[:6]}",
            "player_name": self.player_var.get().strip() or "주인공",
            "player_gender": self.player_gender_var.get().strip() or "남",
            "genre": self.genre_var.get().strip() or "학원 청춘물",
            "world": self.world_text.get("1.0", "end").strip(),
            "turn_limit": int(self.turn_limit_var.get()),
            "characters": valid_characters,
        }
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()


class StoryClientGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("스토리 클라이언트")
        self.root.geometry("1280x860")
        self.root.minsize(980, 700)

        self.ui_font = get_preferred_korean_font(10)
        self.text_font = get_preferred_korean_font(10)
        self.input_font = get_preferred_korean_font(10)

        self.sock = None
        self.connected = False
        self.awaiting_response = False
        self.queue = queue.Queue()
        self.current_setup = {
            "session_id": f"story_{uuid.uuid4().hex[:6]}",
            "player_name": "주인공",
            "player_gender": "남",
            "genre": "학원 청춘물",
            "world": "",
            "turn_limit": 6,
            "characters": [],
        }
        self.current_scene_no = 0

        self.host_var = tk.StringVar(value=SERVER_HOST)
        self.port_var = tk.StringVar(value=str(SERVER_PORT))
        self.token_var = tk.StringVar(value=SECRET_TOKEN)
        self.status_var = tk.StringVar(value="연결 안 됨")
        self.session_var = tk.StringVar(value=self.current_setup["session_id"])
        self.player_var = tk.StringVar(value=self.current_setup["player_name"])
        self.scene_var = tk.StringVar(value="스토리를 아직 시작하지 않았습니다.")
        self.selected_character_var = tk.StringVar(value="")

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

        top = ttk.Frame(self.root, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        for i in range(6):
            top.columnconfigure(i, weight=1)
        self._add_labeled_entry(top, "서버", self.host_var, 0, 0)
        self._add_labeled_entry(top, "포트", self.port_var, 0, 1)
        self._add_labeled_entry(top, "토큰", self.token_var, 0, 2, show="*")
        self._add_labeled_entry(top, "세션 ID", self.session_var, 0, 3)
        self._add_labeled_entry(top, "플레이어 이름", self.player_var, 0, 4)
        btns = ttk.Frame(top)
        btns.grid(row=1, column=5, sticky="e")
        self.connect_btn = ttk.Button(btns, text="연결", command=self.connect_to_server)
        self.connect_btn.pack(side="left", padx=(0, 6))
        self.disconnect_btn = ttk.Button(btns, text="연결 해제", command=self.disconnect_from_server, state="disabled")
        self.disconnect_btn.pack(side="left")

        center = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        center.grid(row=1, column=0, sticky="nsew")
        center.columnconfigure(0, weight=2)
        center.columnconfigure(1, weight=1)
        center.rowconfigure(0, weight=1)

        left = ttk.Frame(center)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        left.rowconfigure(2, weight=1)

        story_actions = ttk.Frame(left)
        story_actions.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.setup_btn = ttk.Button(story_actions, text="스토리 생성", command=self.open_setup_dialog)
        self.setup_btn.pack(side="left")
        self.refresh_btn = ttk.Button(story_actions, text="상태 새로고침", command=self.refresh_state)
        self.refresh_btn.pack(side="left", padx=(6, 0))

        scene_frame = ttk.LabelFrame(left, text="현재 씬", padding=8)
        scene_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        scene_frame.columnconfigure(0, weight=1)
        scene_frame.rowconfigure(1, weight=1)
        ttk.Label(scene_frame, textvariable=self.scene_var).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.scene_text = ScrolledText(scene_frame, wrap="word", font=self.text_font, state="disabled")
        self.scene_text.grid(row=1, column=0, sticky="nsew")

        chat_frame = ttk.LabelFrame(left, text="대화 로그", padding=8)
        chat_frame.grid(row=2, column=0, sticky="nsew")
        chat_frame.columnconfigure(0, weight=1)
        chat_frame.rowconfigure(0, weight=1)
        self.chat_log = ScrolledText(chat_frame, wrap="word", font=self.text_font, state="disabled")
        self.chat_log.grid(row=0, column=0, sticky="nsew")
        self.chat_log.tag_configure("system", foreground="#2c3e50")
        self.chat_log.tag_configure("scene", foreground="#6a1b9a")
        self.chat_log.tag_configure("user", foreground="#0d47a1")
        self.chat_log.tag_configure("npc", foreground="#1b5e20")
        self.chat_log.tag_configure("error", foreground="#b71c1c")

        right = ttk.Frame(center)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        npc_frame = ttk.LabelFrame(right, text="대화 설정", padding=8)
        npc_frame.grid(row=0, column=0, sticky="ew")
        npc_frame.columnconfigure(0, weight=1)
        ttk.Label(npc_frame, text="대화할 등장인물").grid(row=0, column=0, sticky="w")
        self.character_combo = ttk.Combobox(npc_frame, textvariable=self.selected_character_var, state="readonly", font=self.ui_font)
        self.character_combo.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        input_frame = ttk.LabelFrame(right, text="입력", padding=8)
        input_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(0, weight=1)
        self.input_box = tk.Text(input_frame, height=10, wrap="word", font=self.input_font, undo=True)
        self.input_box.grid(row=0, column=0, sticky="nsew")
        self.input_box.bind("<Return>", self._on_enter_key)
        btn_row = ttk.Frame(input_frame)
        btn_row.grid(row=1, column=0, sticky="e", pady=(8, 0))
        self.send_btn = ttk.Button(btn_row, text="보내기", command=self.send_message)
        self.send_btn.pack(side="right")

        status = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

        self._append_log("[시스템] '스토리 생성' 버튼을 눌러 설정을 만든 뒤 시작해 주세요.\n\n", "system")

    def _add_labeled_entry(self, parent, label, variable, row, column, show=None):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w")
        entry = ttk.Entry(parent, textvariable=variable, show=show, font=self.ui_font)
        entry.grid(row=row + 1, column=column, sticky="ew", padx=(0, 8))
        return entry

    def _append_log(self, text, tag=None):
        self.chat_log.configure(state="normal")
        self.chat_log.insert("end", text, tag)
        self.chat_log.see("end")
        self.chat_log.configure(state="disabled")

    def _set_scene_text(self, text):
        self.scene_text.configure(state="normal")
        self.scene_text.delete("1.0", "end")
        self.scene_text.insert("1.0", text)
        self.scene_text.configure(state="disabled")

    def _set_waiting(self, value):
        self.awaiting_response = value
        state = "disabled" if value else "normal"
        self.send_btn.configure(state=state)
        self.setup_btn.configure(state=state if self.connected else "disabled")
        if value:
            self.input_box.configure(state="disabled")
        else:
            self.input_box.configure(state="normal")

    def _set_connected_ui(self, connected):
        self.connected = connected
        self.connect_btn.configure(state="disabled" if connected else "normal")
        self.disconnect_btn.configure(state="normal" if connected else "disabled")
        self.setup_btn.configure(state="normal" if connected and not self.awaiting_response else "disabled")
        self.send_btn.configure(state="normal" if connected and not self.awaiting_response else "disabled")

    def _on_enter_key(self, event):
        if event.state & 0x0001:
            return None
        self.send_message()
        return "break"

    def clear_input(self):
        self.input_box.delete("1.0", "end")

    def connect_to_server(self):
        if self.connected:
            return
        try:
            host = self.host_var.get().strip()
            port = int(self.port_var.get().strip())
            token = self.token_var.get().strip()
        except ValueError:
            messagebox.showwarning("입력 오류", "포트는 숫자여야 합니다.")
            return
        self.status_var.set("연결 중...")
        threading.Thread(target=self._connect_worker, args=(host, port, token), daemon=True).start()

    def _connect_worker(self, host, port, token):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((host, port))
            send_json(sock, {"type": "ping", "token": token})
            resp = recv_json(sock)
            if not resp or resp.get("type") != "pong":
                raise NetworkError("서버 응답이 올바르지 않습니다.")
            sock.settimeout(None)
            self.queue.put(("connected", sock))
        except Exception as e:
            self.queue.put(("connect_error", str(e)))

    def disconnect_from_server(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        self._set_waiting(False)
        self._set_connected_ui(False)
        self.status_var.set("연결 안 됨")
        self._append_log("[시스템] 서버 연결이 해제되었습니다.\n\n", "system")

    def _request_worker(self, payload, purpose):
        try:
            send_json(self.sock, payload)
            resp = recv_json(self.sock)
            if resp is None:
                raise NetworkError("서버 연결이 끊어졌습니다.")
            self.queue.put((purpose, resp))
        except Exception as e:
            self.queue.put(("request_error", str(e)))

    def open_setup_dialog(self):
        if not self.connected:
            messagebox.showwarning("연결 필요", "먼저 서버에 연결해 주세요.")
            return
        dialog = SetupDialog(self.root, self.current_setup)
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        self.current_setup = dialog.result
        self.session_var.set(dialog.result["session_id"])
        self.player_var.set(dialog.result["player_name"])
        self._set_waiting(True)
        self.status_var.set("스토리 생성 중...")
        payload = {
            "type": "start_story",
            "token": self.token_var.get().strip(),
            **dialog.result,
        }
        threading.Thread(target=self._request_worker, args=(payload, "start_story"), daemon=True).start()

    def send_message(self):
        if not self.connected or not self.sock:
            messagebox.showwarning("연결 필요", "먼저 서버에 연결해 주세요.")
            return
        if self.awaiting_response:
            return
        prompt = self.input_box.get("1.0", "end").strip()
        if not prompt:
            return
        session_id = self.session_var.get().strip()
        character_name = self.selected_character_var.get().strip()
        player_name = self.player_var.get().strip() or "주인공"
        if not session_id:
            messagebox.showwarning("안내", "먼저 스토리를 시작해 주세요.")
            return
        if not character_name:
            messagebox.showwarning("안내", "대화할 등장인물을 선택해 주세요.")
            return
        self._append_log(f"{player_name}: {prompt}\n", "user")
        self.clear_input()
        self._set_waiting(True)
        self.status_var.set("응답 생성 중...")
        payload = {
            "type": "talk",
            "token": self.token_var.get().strip(),
            "session_id": session_id,
            "character_name": character_name,
            "user_input": prompt,
        }
        threading.Thread(target=self._request_worker, args=(payload, "talk"), daemon=True).start()

    def refresh_state(self):
        if not self.connected or not self.session_var.get().strip():
            return
        payload = {
            "type": "get_state",
            "token": self.token_var.get().strip(),
            "session_id": self.session_var.get().strip(),
        }
        threading.Thread(target=self._request_worker, args=(payload, "get_state"), daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "connected":
                    self.sock = item[1]
                    self._set_connected_ui(True)
                    self.status_var.set("연결됨")
                    self._append_log("[시스템] 서버에 연결되었습니다.\n\n", "system")
                elif kind == "connect_error":
                    self.status_var.set("연결 실패")
                    messagebox.showerror("연결 실패", item[1])
                elif kind == "start_story":
                    self._handle_start_story(item[1])
                elif kind == "talk":
                    self._handle_talk(item[1])
                elif kind == "get_state":
                    self._handle_state(item[1])
                elif kind == "request_error":
                    self._set_waiting(False)
                    self._append_log(f"[오류] {item[1]}\n\n", "error")
                    self.status_var.set("오류 발생")
                    self.disconnect_from_server()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _handle_start_story(self, resp):
        self._set_waiting(False)
        if resp.get("type") != "story_started":
            self._append_log(f"[오류] {resp.get('message', '스토리 시작 실패')}\n\n", "error")
            self.status_var.set("스토리 시작 실패")
            return
        self.current_scene_no = int(resp.get("scene_no") or 1)
        self.scene_var.set(f"씬 {self.current_scene_no}")
        scene_text = resp.get("scene_text", "")
        self._set_scene_text(scene_text)
        self._append_log("[시스템] 스토리가 시작되었습니다.\n", "system")
        self._append_log(f"[씬 {self.current_scene_no}]\n{scene_text}\n\n", "scene")
        names = resp.get("characters") or []
        self.character_combo["values"] = names
        if names:
            self.selected_character_var.set(names[0])
        self.status_var.set("스토리 시작 완료")

    def _handle_talk(self, resp):
        self._set_waiting(False)
        if resp.get("type") != "reply":
            self._append_log(f"[오류] {resp.get('message', '응답 실패')}\n\n", "error")
            self.status_var.set("오류 발생")
            return
        char_name = self.selected_character_var.get().strip() or "등장인물"
        self._append_log(f"{char_name}: {resp.get('text', '')}\n\n", "npc")
        if resp.get("scene_advanced"):
            self.current_scene_no = int(resp.get("scene_no") or (self.current_scene_no + 1))
            self.scene_var.set(f"씬 {self.current_scene_no}")
            scene_text = resp.get("scene_text") or ""
            self._set_scene_text(scene_text)
            self._append_log(f"[시스템] 이야기가 다음 장면으로 진행되었습니다.\n", "system")
            self._append_log(f"[씬 {self.current_scene_no}]\n{scene_text}\n\n", "scene")
        self.status_var.set("응답 완료")

    def _handle_state(self, resp):
        if resp.get("type") != "state":
            return
        state = resp.get("state", {})
        self.current_scene_no = int(state.get("scene_no") or 0)
        self.scene_var.set(f"씬 {self.current_scene_no}" if self.current_scene_no else "스토리를 아직 시작하지 않았습니다.")
        self._set_scene_text(state.get("scene_text", ""))
        names = [c.get("name", "") for c in state.get("characters", []) if c.get("name")]
        self.character_combo["values"] = names
        if names and self.selected_character_var.get().strip() not in names:
            self.selected_character_var.set(names[0])

    def on_close(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = StoryClientGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
