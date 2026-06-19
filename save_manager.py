from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional


class SaveManager:
    """세션 JSON 파일을 안전하게 저장하고 불러온다."""

    def __init__(self, save_dir: Optional[Path] = None):
        base_dir = Path(__file__).resolve().parent
        self.save_dir = Path(save_dir) if save_dir else base_dir / "data" / "saves"
        self.save_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_name(session_id: str) -> str:
        safe = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", (session_id or "").strip())
        return safe[:80] or "unnamed_session"

    def path_for(self, session_id: str) -> Path:
        return self.save_dir / f"{self._safe_name(session_id)}.json"

    def save(self, session_data: Dict) -> Path:
        session_id = str(session_data.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id is empty")
        target = self.path_for(session_id)
        fd, temp_name = tempfile.mkstemp(prefix=target.stem + "_", suffix=".tmp", dir=self.save_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(session_data, fp, ensure_ascii=False, indent=2)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.remove(temp_name)
        return target

    def load(self, session_id: str) -> Optional[Dict]:
        path = self.path_for(session_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        if not isinstance(data, dict):
            raise ValueError(f"invalid save file: {path.name}")
        return data

    def load_all(self) -> List[Dict]:
        sessions: List[Dict] = []
        for path in sorted(self.save_dir.glob("*.json")):
            try:
                with path.open("r", encoding="utf-8") as fp:
                    data = json.load(fp)
                if isinstance(data, dict) and data.get("session_id"):
                    sessions.append(data)
            except Exception:
                # 손상된 파일 하나 때문에 전체 서버가 시작되지 않는 상황은 피한다.
                continue
        return sessions

    def delete(self, session_id: str) -> bool:
        path = self.path_for(session_id)
        if not path.exists():
            return False
        path.unlink()
        return True
