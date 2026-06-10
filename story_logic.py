
from __future__ import annotations

import json
import re
import socket
import struct
import threading
import traceback
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional

import requests

from story_prompts import (
    build_scene_prompt,
    build_summary_prompt,
    build_system_prompt,
    build_talk_prompt,
    build_talk_rewrite_prompt,
)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5767
DEFAULT_SECRET_TOKEN = "change_this_to_a_long_random_string"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL_NAME = "llama3"

DEFAULT_EMOTIONS = {
    "affection": 35,
    "trust": 45,
    "interest": 40,
    "tension": 15,
    "embarrassment": 5,
    "hurt": 0,
}

DISALLOWED_RE = re.compile(
    r"[\u3040-\u30ff\u31f0-\u31ff\u0400-\u04FF\U0001F300-\U0001FAFF]|[A-Za-z]{2,}"
)

SCENE_FALLBACK_TEMPLATE = """[씬 {scene_no}: {title}]
{body}

목표: {goal}
갈등: {conflict}
분위기: {mood}"""


class NetworkError(Exception):
    pass


@dataclass
class CharacterRuntimeState:
    emotions: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_EMOTIONS))
    memories: List[str] = field(default_factory=list)
    last_user_input: str = ""
    last_topic: str = ""


@dataclass
class SessionState:
    session_id: str
    player_name: str
    player_gender: str
    genre: str
    world: str
    turn_limit: int
    characters: List[Dict]
    scene_no: int = 1
    scene_text: str = ""
    turn_count: int = 0
    history: List[Dict] = field(default_factory=list)
    prior_summary: str = ""
    previous_reply_by_character: Dict[str, str] = field(default_factory=dict)
    runtime_by_character: Dict[str, CharacterRuntimeState] = field(default_factory=dict)


class StoryEngine:
    def __init__(self, log: Optional[Callable[[str], None]] = None):
        self.log = log or (lambda msg: None)
        self.ollama_url = DEFAULT_OLLAMA_URL
        self.model_name = DEFAULT_MODEL_NAME
        self.sessions: Dict[str, SessionState] = {}
        self.sessions_lock = threading.Lock()

    def set_model_config(self, *, ollama_url: str, model_name: str):
        self.ollama_url = ollama_url
        self.model_name = model_name

    @staticmethod
    def normalize_text(text: str) -> str:
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def clamp(value: int, low: int = 0, high: int = 100) -> int:
        return max(low, min(high, int(value)))

    @staticmethod
    def contains_disallowed(text: str) -> bool:
        return bool(DISALLOWED_RE.search(text or ""))

    @staticmethod
    def is_very_broken(text: str) -> bool:
        text = text or ""
        if not text.strip():
            return True
        if re.search(r"\(\:|\'\w|\.[ )]", text):
            return True
        if len(re.findall(r"[가-힣]", text)) < 4:
            return True
        return False

    @staticmethod
    def recvall(sock, size):
        data = b""
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                return None
            data += chunk
        return data

    @staticmethod
    def send_json(sock, obj):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        header = struct.pack("!I", len(payload))
        sock.sendall(header + payload)

    @staticmethod
    def recv_json(sock):
        header = StoryEngine.recvall(sock, 4)
        if header is None:
            return None
        length = struct.unpack("!I", header)[0]
        payload = StoryEngine.recvall(sock, length)
        if payload is None:
            return None
        return json.loads(payload.decode("utf-8"))

    def generate(self, prompt: str, *, temperature: float = 0.28, num_predict: int = 180) -> str:
        body = {
            "model": self.model_name,
            "system": build_system_prompt(),
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        response = requests.post(self.ollama_url, json=body, timeout=300)
        response.raise_for_status()
        data = response.json()
        return self.normalize_text(data.get("response", ""))

    def summarize_history(self, history: List[Dict], limit: int = 10) -> str:
        recent = history[-limit:]
        lines = []
        for item in recent:
            speaker = item.get("speaker", "")
            text = self.normalize_text(item.get("text", ""))
            if speaker and text:
                lines.append(f"- {speaker}: {text}")
        return "\n".join(lines) if lines else "- 아직 중요한 대화가 쌓이지 않았다."

    def make_scene_fallback(self, scene_no: int, player_name: str, characters: List[Dict], summary: str = "") -> str:
        char = characters[0] if characters else {"name": "상대", "relationship": "아는 사이", "personality": "차분함"}
        name = char.get("name") or "상대"
        relation = char.get("relationship") or "아는 사이"
        title = "아침 학교 앞" if scene_no == 1 else "조금 가까워진 분위기"
        body = (
            f"{player_name}은 {name}과 자연스럽게 마주쳤다. "
            f"두 사람은 {relation}답게 어색하지는 않지만, 오늘은 유난히 서로의 반응을 더 의식하게 되는 분위기다. "
            f"{name}은 겉으로는 차분해 보여도 대화를 피하지 않고 {player_name}의 말을 기다리고 있다."
        )
        goal = "상대와 자연스럽게 대화를 이어 간다."
        conflict = "서로의 속마음을 쉽게 드러내지 못한다."
        mood = "조용하지만 감정이 조금씩 움직이는 분위기."
        return SCENE_FALLBACK_TEMPLATE.format(scene_no=scene_no, title=title, body=body, goal=goal, conflict=conflict, mood=mood)

    def sanitize_scene(self, text: str, scene_no: int, player_name: str, characters: List[Dict]) -> str:
        text = self.normalize_text(text)
        text = re.sub(r"^\[(Scene|SCENE).*?\]", "", text, flags=re.MULTILINE).strip()
        lines: List[str] = []
        for raw in text.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if "물어보세요" in line or "다음 말을" in line or "질문" in line:
                continue
            if '"' in line or "'" in line:
                continue
            if self.contains_disallowed(line):
                continue
            lines.append(line)
        cleaned = "\n".join(lines).strip()
        if not cleaned or self.is_very_broken(cleaned):
            return self.make_scene_fallback(scene_no, player_name, characters)
        if not cleaned.startswith("[씬"):
            cleaned = f"[씬 {scene_no}: 시작]\n" + cleaned
        if "목표:" not in cleaned:
            cleaned += "\n\n목표: 상대와 자연스럽게 대화를 이어 간다."
        if "갈등:" not in cleaned:
            cleaned += "\n갈등: 서로의 속마음을 쉽게 드러내지 못한다."
        if "분위기:" not in cleaned:
            cleaned += "\n분위기: 일상적이지만 미묘하게 긴장된 분위기."
        return cleaned

    def extract_scene_context(self, scene_text: str) -> str:
        lines: List[str] = []
        for raw in self.normalize_text(scene_text).split("\n"):
            line = raw.strip()
            if not line or line.startswith("[씬"):
                continue
            if re.match(r"^(목표|갈등|분위기)\s*:", line):
                break
            lines.append(line)
        context = " ".join(lines).strip()
        if not context:
            return "두 사람은 조용한 분위기 속에서 마주 보고 대화하고 있다."
        return context

    def init_runtime_for_character(self, character: Dict) -> CharacterRuntimeState:
        state = CharacterRuntimeState()
        relation = character.get("relationship", "") or ""
        if any(tok in relation for tok in ["소꿉", "친구", "가깝", "오래"]):
            state.emotions["trust"] = 55
            state.emotions["interest"] = 50
        if any(tok in relation for tok in ["짝사랑", "호감", "좋아"]):
            state.emotions["affection"] = 60
            state.emotions["interest"] = 60
            state.emotions["embarrassment"] = 15
        return state

    def get_runtime(self, session: SessionState, character_name: str, character: Dict) -> CharacterRuntimeState:
        runtime = session.runtime_by_character.get(character_name)
        if runtime is None:
            runtime = self.init_runtime_for_character(character)
            session.runtime_by_character[character_name] = runtime
        return runtime

    def remember(self, runtime: CharacterRuntimeState, memory: str) -> None:
        if not memory:
            return
        if runtime.memories and runtime.memories[-1] == memory:
            return
        runtime.memories.append(memory)
        runtime.memories = runtime.memories[-8:]

    def update_emotions_and_memory(self, runtime: CharacterRuntimeState, user_input: str) -> None:
        t = user_input.strip()
        emo = runtime.emotions
        runtime.last_user_input = t

        if any(x in t for x in ["안녕", "좋은 아침", "좋은 저녁"]):
            emo["interest"] += 2
        if any(x in t for x in ["같이", "갈래", "올래", "보러", "먹을래", "먹자", "우리집"]):
            emo["affection"] += 4
            emo["trust"] += 3
            emo["interest"] += 4
        if any(x in t for x in ["좋아해", "사귀자", "너 좋아해"]):
            emo["affection"] += 8
            emo["embarrassment"] += 18
            emo["interest"] += 6
            self.remember(runtime, "플레이어가 감정을 드러냈다")
        if any(x in t for x in ["미안", "성급했지", "내가 좀"]):
            emo["hurt"] -= 8
            emo["tension"] -= 6
            emo["trust"] += 4
        if any(x in t for x in ["뭐야", "어쩌라고", "무시", "바보", "짜증", "서운"]):
            emo["hurt"] += 16
            emo["tension"] += 14
            emo["trust"] -= 10
            self.remember(runtime, "플레이어가 날카롭게 반응했다")
        if "좋아하는 사람" in t:
            emo["embarrassment"] += 8
            emo["tension"] += 4
        if any(x in t for x in ["우리집", "집에"]):
            self.remember(runtime, "플레이어가 집에 초대했다")
        if any(x in t for x in ["라면", "밥", "저녁"]):
            self.remember(runtime, "플레이어가 함께 먹는 이야기를 꺼냈다")
        if any(x in t for x in ["영화"]):
            self.remember(runtime, "플레이어가 같이 시간을 보내자고 했다")

        for k in list(emo.keys()):
            emo[k] = self.clamp(emo[k])

    def emotion_hint(self, runtime: CharacterRuntimeState) -> str:
        e = runtime.emotions
        hints: List[str] = []
        if e["hurt"] >= 45:
            hints.append("조금 상처받아 있고 말투가 조심스러워질 수 있다")
        elif e["hurt"] >= 20:
            hints.append("조금 서운한 감정이 남아 있다")
        if e["embarrassment"] >= 50:
            hints.append("상대를 의식해서 쉽게 태연한 척하기 어렵다")
        elif e["embarrassment"] >= 20:
            hints.append("조금 부끄러워하면서도 시선을 피하지는 않는다")
        if e["affection"] >= 70:
            hints.append("상대에게 강한 호감을 느끼고 있어 반응이 부드럽다")
        elif e["affection"] >= 45:
            hints.append("상대를 꽤 좋게 보고 있다")
        if e["trust"] >= 60:
            hints.append("상대 앞에서는 비교적 솔직해질 수 있다")
        elif e["trust"] <= 30:
            hints.append("아직 쉽게 마음을 열지는 못한다")
        if e["tension"] >= 45:
            hints.append("분위기가 어색해질까 신경 쓰고 있다")
        if not hints:
            hints.append("겉으로는 차분하지만 대화에는 성의 있게 임하려고 한다")
        return ", ".join(hints)

    def memory_hint(self, runtime: CharacterRuntimeState) -> str:
        if not runtime.memories:
            return "방금 전 대화의 분위기만 어렴풋이 남아 있다"
        recent = runtime.memories[-2:]
        if len(recent) == 1:
            return f"최근에 {recent[0]}는 여운이 남아 있다"
        return f"최근에 {recent[0]}고, 이어서 {recent[1]}는 여운이 남아 있다"

    def infer_response_goal(self, user_input: str, runtime: CharacterRuntimeState) -> str:
        t = user_input
        if any(x in t for x in ["뭐야", "무시", "어쩌라고", "바보"]):
            return "오해를 풀고 상대의 감정을 달랜다"
        if any(x in t for x in ["좋아해", "사귀자"]):
            return "놀람을 숨기지 않되, 가볍게 넘기지 않고 진지하게 반응한다"
        if any(x in t for x in ["미안", "성급했지"]):
            return "사과를 받아 주면서 분위기를 부드럽게 만든다"
        if any(x in t for x in ["뭐해", "뭐 할", "예정", "무슨", "어제", "오늘", "먹을래", "갈래", "올래"]):
            return "질문에 분명히 답하고, 대화가 이어질 여지를 남긴다"
        if any(x in t for x in ["렘", "왜 불렀어"]):
            return "상대의 의도를 묻되 차갑게 들리지 않게 한다"
        return "상대의 말을 듣고 생각한 흔적이 드러나게 반응한다"

    def sanitize_talk(self, text: str, character_name: str, previous_reply: str = "") -> str:
        text = self.normalize_text(text)
        fragments: List[str] = []
        for raw in text.split("\n"):
            line = raw.strip().strip('"').strip("'")
            if not line:
                continue
            line = re.sub(rf"^\s*{re.escape(character_name)}\s*[:：]\s*", "", line)
            line = re.sub(r"^[가-힣A-Za-z0-9_]+\s*[:：]\s*", "", line)
            if re.match(r"^(목표|갈등|분위기|장면|설명|현재 상황|최근 대화)\s*:", line):
                continue
            if re.search(r"말했다|대답했다|웃으며|생각했다|속으로", line):
                continue
            if self.contains_disallowed(line):
                continue
            if any(line.startswith(prefix) for prefix in ["아하", "와", "ㅎㅎ", "하하", "헤헤"]):
                line = re.sub(r"^(아하|와|ㅎㅎ|하하|헤헤)[, !\.]*", "", line).strip()
            if line:
                fragments.append(line)
        cleaned = " ".join(fragments).strip()
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = cleaned.replace("..", ".")
        parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", cleaned) if p.strip()]
        if len(parts) > 2:
            cleaned = " ".join(parts[:2])
        if not cleaned:
            cleaned = "그런 뜻은 아니야. 내 말이 조금 이상했네."
        if previous_reply and SequenceMatcher(None, cleaned, previous_reply).ratio() > 0.9:
            cleaned = "같은 말만 하고 싶진 않아. 이번에는 조금 더 제대로 말해 볼게."
        return cleaned

    def reply_addresses_input(self, user_input: str, reply: str, previous_reply: str = "") -> bool:
        if not reply or self.is_very_broken(reply) or self.contains_disallowed(reply):
            return False
        if previous_reply and SequenceMatcher(None, reply, previous_reply).ratio() > 0.9:
            return False
        if any(tok in user_input for tok in ["뭐야", "무시", "어쩌라고", "바보"]) and not any(tok in reply for tok in ["아니", "미안", "그런 뜻", "오해", "무시"]):
            return False
        if any(tok in user_input for tok in ["어제", "오늘", "뭐해", "뭐 할", "예정", "무슨", "먹을래", "갈래", "올래"]):
            if not any(tok in reply for tok in ["어제", "오늘", "아직", "없어", "있어", "괜찮아", "좋아", "갈 수", "올 수", "정한 건"]):
                return False
        return True

    def build_rule_based_fallback(self, user_input: str, runtime: CharacterRuntimeState, character: Dict) -> str:
        e = runtime.emotions
        t = user_input.strip()
        warm = e["affection"] + e["trust"]

        if any(x in t for x in ["안녕", "좋은 아침"]):
            return "응, 안녕. 네가 먼저 인사해 주니까 괜히 반갑네." if warm >= 100 else "안녕. 오늘은 조금 일찍 왔네."
        if any(x in t for x in ["무슨 소리", "뭐야", "무시", "어쩌라고", "바보"]):
            return "그런 뜻으로 말한 건 아니야. 네 말은 듣고 있었는데 내가 이상하게 답했네."
        if "어제" in t and any(x in t for x in ["뭐했", "했니", "했어"]):
            return "어제는 그냥 집에서 쉬었어. 특별한 일은 없었고, 좀 조용히 보냈지."
        if any(x in t for x in ["오늘 뭐해", "오늘 뭐 할", "오늘 예정", "오늘 뭐하"]):
            return "아직 딱 정한 건 없어. 왜, 같이 뭐 하자는 거야?"
        if any(x in t for x in ["갈래", "올래", "우리집"]):
            if e["trust"] >= 50:
                return "응, 괜찮아. 네가 편하면 나도 같이 가는 건 싫지 않아."
            return "갑자기라 조금 놀랐지만, 너무 늦지 않다면 괜찮을 것 같아."
        if any(x in t for x in ["뭐 하고 싶어", "뭐할래"]):
            if any("먹는 이야기를 꺼냈다" in m for m in runtime.memories):
                return "같이 먹으면서 천천히 얘기하는 게 좋겠어. 너무 거창한 건 아니어도 괜찮고."
            return "조용히 같이 있는 것도 괜찮고, 가볍게 영화나 얘기하면서 시간 보내도 좋을 것 같아."
        if any(x in t for x in ["라면 먹을래", "밥 먹을래", "저녁 먹을래"]):
            return "응, 좋아. 같이 먹으면 괜히 더 맛있을 것 같네."
        if any(x in t for x in ["좋아하는 사람 있어"]):
            if e["affection"] >= 55:
                return "있다고 하면… 네가 제일 먼저 신경 쓰일 것 같아."
            return "글쎄, 아직은 나도 확실히 말하기 어렵네."
        if any(x in t for x in ["나 너 좋아해", "사귀자"]):
            if e["affection"] >= 60:
                return "갑자기 들으니까 당황스럽긴 한데, 싫지는 않아. 나도 가볍게 넘기고 싶지는 않네."
            return "너무 갑작스러워서 바로 답하긴 어렵지만, 장난처럼 듣고 싶지는 않아."
        if any(x in t for x in ["미안", "성급했지"]):
            return "응, 조금 놀라긴 했어. 그래도 네가 솔직하게 말한 건 알겠어."
        if character.get("name") and character.get("name") in t:
            return "응, 듣고 있어. 왜 불렀어?"
        return "응, 네 말은 들었어. 조금만 천천히 말해 줄래?"

    def create_candidate_reply(self, state: SessionState, character: Dict, runtime: CharacterRuntimeState, user_input: str, previous_reply: str) -> str:
        scene_context = self.extract_scene_context(state.scene_text)
        recent_history = self.summarize_history(state.history, limit=8)
        prompt = build_talk_prompt(
            scene_context=scene_context,
            character=character,
            player_name=state.player_name,
            user_input=user_input,
            recent_history=recent_history,
            previous_reply=previous_reply,
            emotion_hint=self.emotion_hint(runtime),
            memory_hint=self.memory_hint(runtime),
            response_goal=self.infer_response_goal(user_input, runtime),
        )
        candidate = self.generate(prompt, temperature=0.22, num_predict=90)
        candidate = self.sanitize_talk(candidate, character.get("name", "등장인물"), previous_reply)
        if self.reply_addresses_input(user_input, candidate, previous_reply):
            rewrite = self.generate(
                build_talk_rewrite_prompt(
                    character_name=character.get("name", "등장인물"),
                    player_name=state.player_name,
                    user_input=user_input,
                    candidate_reply=candidate,
                    scene_context=scene_context,
                    recent_history=recent_history,
                    character=character,
                    emotion_hint=self.emotion_hint(runtime),
                    memory_hint=self.memory_hint(runtime),
                    response_goal=self.infer_response_goal(user_input, runtime),
                ),
                temperature=0.18,
                num_predict=90,
            )
            rewrite = self.sanitize_talk(rewrite, character.get("name", "등장인물"), previous_reply)
            if self.reply_addresses_input(user_input, rewrite, previous_reply):
                return rewrite
            return candidate
        return self.build_rule_based_fallback(user_input, runtime, character)

    def start_story(self, req: Dict) -> Dict:
        session_id = (req.get("session_id") or "").strip()
        player_name = (req.get("player_name") or "주인공").strip()
        player_gender = (req.get("player_gender") or "미정").strip()
        genre = (req.get("genre") or "일상").strip()
        world = (req.get("world") or "").strip()
        turn_limit = int(req.get("turn_limit") or 6)
        characters = req.get("characters") or []
        if not session_id:
            return {"type": "error", "message": "session_id is empty"}
        if not characters:
            return {"type": "error", "message": "characters are empty"}

        try:
            scene_text = self.generate(
                build_scene_prompt(
                    scene_no=1,
                    genre=genre,
                    world=world,
                    player_name=player_name,
                    player_gender=player_gender,
                    characters=characters,
                    prior_summary="",
                ),
                temperature=0.2,
                num_predict=180,
            )
            scene_text = self.sanitize_scene(scene_text, 1, player_name, characters)
        except Exception as exc:
            self.log(f"[story] scene generation failed: {exc}")
            scene_text = self.make_scene_fallback(1, player_name, characters)

        state = SessionState(
            session_id=session_id,
            player_name=player_name,
            player_gender=player_gender,
            genre=genre,
            world=world,
            turn_limit=turn_limit,
            characters=characters,
            scene_no=1,
            scene_text=scene_text,
        )
        for c in characters:
            if c.get("name"):
                state.runtime_by_character[c["name"]] = self.init_runtime_for_character(c)

        with self.sessions_lock:
            self.sessions[session_id] = state
        return {
            "type": "story_started",
            "scene_no": 1,
            "scene_text": scene_text,
            "characters": [c.get("name", "") for c in characters if c.get("name")],
        }

    def advance_scene(self, state: SessionState) -> None:
        summary = "최근 대화에서 두 사람은 조금 더 솔직해졌지만 아직 결론을 내리지는 못했다. 다음 만남에서는 감정의 여운이 더 선명하게 남아 있다."
        try:
            generated = self.generate(build_summary_prompt(self.summarize_history(state.history, limit=20)), temperature=0.15, num_predict=120)
            if generated and not self.contains_disallowed(generated) and not self.is_very_broken(generated):
                summary = generated
        except Exception:
            pass

        next_scene_no = state.scene_no + 1
        try:
            scene_text = self.generate(
                build_scene_prompt(
                    scene_no=next_scene_no,
                    genre=state.genre,
                    world=state.world,
                    player_name=state.player_name,
                    player_gender=state.player_gender,
                    characters=state.characters,
                    prior_summary=summary,
                ),
                temperature=0.2,
                num_predict=180,
            )
            scene_text = self.sanitize_scene(scene_text, next_scene_no, state.player_name, state.characters)
        except Exception:
            scene_text = self.make_scene_fallback(next_scene_no, state.player_name, state.characters, summary)

        state.prior_summary = summary
        state.scene_no = next_scene_no
        state.scene_text = scene_text
        state.turn_count = 0
        state.previous_reply_by_character = {}

    def talk(self, req: Dict) -> Dict:
        session_id = (req.get("session_id") or "").strip()
        character_name = (req.get("character_name") or "").strip()
        user_input = (req.get("user_input") or "").strip()
        if not session_id or not character_name or not user_input:
            return {"type": "error", "message": "missing talk arguments"}

        with self.sessions_lock:
            state = self.sessions.get(session_id)
        if not state:
            return {"type": "error", "message": "session not found"}

        character = next((c for c in state.characters if c.get("name") == character_name), None)
        if not character:
            return {"type": "error", "message": "character not found"}

        runtime = self.get_runtime(state, character_name, character)
        self.update_emotions_and_memory(runtime, user_input)
        previous_reply = state.previous_reply_by_character.get(character_name, "")

        try:
            reply = self.create_candidate_reply(state, character, runtime, user_input, previous_reply)
        except Exception as exc:
            self.log(f"[talk] generation failed: {exc}")
            reply = self.build_rule_based_fallback(user_input, runtime, character)

        state.history.append({"speaker": state.player_name, "text": user_input})
        state.history.append({"speaker": character_name, "text": reply})
        state.previous_reply_by_character[character_name] = reply
        state.turn_count += 1

        scene_advanced = False
        if state.turn_count >= state.turn_limit:
            self.advance_scene(state)
            scene_advanced = True

        return {
            "type": "reply",
            "text": reply,
            "scene_advanced": scene_advanced,
            "scene_no": state.scene_no,
            "scene_text": state.scene_text if scene_advanced else "",
        }

    def get_state(self, req: Dict) -> Dict:
        session_id = (req.get("session_id") or "").strip()
        with self.sessions_lock:
            state = self.sessions.get(session_id)
        if not state:
            return {"type": "state", "state": {}}
        return {
            "type": "state",
            "state": {
                "session_id": state.session_id,
                "player_name": state.player_name,
                "player_gender": state.player_gender,
                "genre": state.genre,
                "world": state.world,
                "turn_limit": state.turn_limit,
                "scene_no": state.scene_no,
                "scene_text": state.scene_text,
                "characters": state.characters,
                "turn_count": state.turn_count,
            },
        }

    def process_request(self, req: Dict, secret_token: str) -> Dict:
        if not isinstance(req, dict):
            return {"type": "error", "message": "invalid json object"}
        if req.get("token") != secret_token:
            return {"type": "error", "message": "unauthorized"}
        req_type = req.get("type")
        if req_type == "ping":
            return {"type": "pong", "message": "ok"}
        if req_type == "start_story":
            return self.start_story(req)
        if req_type == "talk":
            return self.talk(req)
        if req_type == "get_state":
            return self.get_state(req)
        return {"type": "error", "message": f"unknown request type: {req_type}"}


class ThreadedServer:
    def __init__(self, engine: StoryEngine, log: Callable[[str], None]):
        self.engine = engine
        self.log = log
        self.host = DEFAULT_HOST
        self.port = DEFAULT_PORT
        self.secret_token = DEFAULT_SECRET_TOKEN
        self.server_sock: Optional[socket.socket] = None
        self.accept_thread: Optional[threading.Thread] = None
        self.running = False

    def start(self, host: str, port: int, secret_token: str) -> None:
        if self.running:
            return
        self.host = host
        self.port = port
        self.secret_token = secret_token
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen()
        self.running = True
        self.accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self.accept_thread.start()
        self.log(f"[*] server listening on {self.host}:{self.port}")

    def stop(self) -> None:
        self.running = False
        try:
            if self.server_sock:
                self.server_sock.close()
        except Exception:
            pass
        self.server_sock = None
        self.log("[!] server stopped")

    def _accept_loop(self) -> None:
        while self.running:
            try:
                client_sock, client_addr = self.server_sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(client_sock, client_addr), daemon=True).start()

    def _handle_client(self, client_sock: socket.socket, client_addr) -> None:
        self.log(f"[+] connected: {client_addr}")
        try:
            while self.running:
                req = StoryEngine.recv_json(client_sock)
                if req is None:
                    break
                try:
                    resp = self.engine.process_request(req, self.secret_token)
                except requests.exceptions.RequestException as exc:
                    resp = {"type": "error", "message": f"llm request failed: {exc}"}
                except Exception as exc:
                    traceback.print_exc()
                    resp = {"type": "error", "message": f"server error: {exc}"}
                StoryEngine.send_json(client_sock, resp)
        finally:
            try:
                client_sock.close()
            except Exception:
                pass
            self.log(f"[-] disconnected: {client_addr}")
