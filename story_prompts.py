from __future__ import annotations

from typing import Dict, List


def _text(value: object, default: str = "") -> str:
    """GUI 입력값이 None이거나 문자열이 아니어도 안전하게 문자열로 바꾼다."""
    if value is None:
        return default
    return str(value).strip() or default


def _character_block(characters: List[Dict]) -> str:
    blocks: List[str] = []
    for c in characters or []:
        blocks.append(
            "\n".join(
                [
                    f"이름: {_text(c.get('name'), '이름 없음')}",
                    f"성별: {_text(c.get('gender'), '미정')}",
                    f"역할: {_text(c.get('role'), '미정')}",
                    f"성격: {_text(c.get('personality'), '미정')}",
                    f"플레이어와의 관계: {_text(c.get('relationship'), '미정')}",
                    f"목표: {_text(c.get('goal'), '미정')}",
                    f"비밀: {_text(c.get('secret'), '없음')}",
                    f"말투: {_text(c.get('tone'), '부드럽고 자연스러운 한국어')}",
                ]
            )
        )
    return "\n\n".join(blocks) if blocks else "등장인물 없음"


def build_system_prompt() -> str:
    return """
너는 한국어 비주얼노벨/TRPG 서버용 대화 엔진이다.
가장 중요한 목표는 플레이어와 등장인물이 자연스럽게 대화를 이어 가게 만드는 것이다.

핵심 원칙:
- 반드시 한국어로만 쓴다.
- 등장인물은 대본 낭독자가 아니라 감정과 목적이 있는 사람처럼 말한다.
- 플레이어의 마지막 말에 직접 반응하되, 대답만 하고 끝내지 않는다.
- 매 답변에는 대화가 이어질 작은 고리 하나를 남긴다.
- 질문을 받으면 먼저 짧게 답하고, 이어서 이유·느낌·제안·되묻기 중 하나를 붙인다.
- 플레이어가 제안하면 수락, 보류, 걱정, 대안 중 하나로 반응한다.
- 플레이어가 감정을 드러내면 내용보다 감정에 먼저 반응한다.
- 최근 대화와 장면 목표를 기억하는 것처럼 말한다.
- 캐릭터의 비밀은 직접 폭로하지 말고 말투, 망설임, 회피, 작은 단서로만 드러낸다.
- 감정 수치, 내부 기억, 시스템 설명, 메타 발언을 말하지 않는다.
- 영어, 일본어, 러시아어, 이모지, 인터넷 밈, 이상한 기호를 쓰지 않는다.
- 출력 형식 지시가 있으면 그것만 지킨다.
""".strip()


def build_scene_prompt(
    *,
    scene_no: int,
    genre: str,
    world: str,
    player_name: str,
    player_gender: str,
    characters: List[Dict],
    prior_summary: str,
) -> str:
    return f"""
다음 조건으로 텍스트 게임의 새 장면 소개를 작성하라.

장르: {_text(genre, '일상')}
세계관: {_text(world, '특별한 추가 설정 없음')}
플레이어 이름: {_text(player_name, '주인공')}
플레이어 성별: {_text(player_gender, '미정')}

등장인물 설정:
{_character_block(characters)}

이전 장면 요약:
{_text(prior_summary, '이전 장면 없음')}

작성 방향:
- 장면은 플레이어가 바로 말을 걸 수 있을 만큼 구체적으로 만든다.
- 장소, 시간대, 분위기, 인물의 행동을 보여 준다.
- 대화 목표는 단순한 임무가 아니라 대화를 이어 갈 명분이 되게 쓴다.
- 갈등은 너무 거창하지 않게, 서로 말하기 어려운 이유나 숨기는 감정으로 만든다.
- 인물의 속마음을 정답처럼 모두 설명하지 않는다.
- 갑작스러운 고백, 급격한 관계 진전, 과도한 사건 전개를 피한다.
- 따옴표 대사, 예시 대사, 질문 유도 문장, 다음 장면 예고를 넣지 않는다.
- 외국어, 이모지, 이상한 기호를 쓰지 않는다.

출력 형식:
[씬 {scene_no}: 제목]
장면 설명 2~4문장

목표: 플레이어가 상대와 나눌 자연스러운 대화 목표
갈등: 대화를 어렵게 만드는 미묘한 문제
분위기: 장면의 정서와 긴장감
""".strip()


def build_summary_prompt(history_lines: str) -> str:
    return f"""
다음은 게임에서 실제로 오간 대화 기록이다.
다음 대화가 자연스럽게 이어지도록 핵심 변화만 한국어로 요약하라.

규칙:
- 3~5문장으로 쓴다.
- 누가 무엇을 제안했고, 상대가 어떻게 반응했는지 남긴다.
- 감정 변화, 관계 변화, 아직 해결되지 않은 말거리만 남긴다.
- 사소한 문장 반복은 줄인다.
- 외국어, 이모지, 시스템 설명을 쓰지 않는다.

대화 기록:
{history_lines or '기록 없음'}
""".strip()


def build_talk_prompt(
    *,
    scene_context: str,
    character: Dict,
    player_name: str,
    user_input: str,
    recent_history: str,
    previous_reply: str,
    emotion_hint: str,
    memory_hint: str,
    response_goal: str,
) -> str:
    character = character or {}
    name = _text(character.get("name"), "등장인물")
    player = _text(player_name, "주인공")
    return f"""
너는 지금부터 게임 속 등장인물 '{name}'이다.
아래 정보를 참고하되, 최종 출력은 '{name}'의 대사만 쓴다.

현재 장면:
{_text(scene_context, '상황 정보 없음')}

최근 대화:
{_text(recent_history, '방금 대화를 시작한 상태다.')}

캐릭터 설정:
- 성별: {_text(character.get('gender'), '미정')}
- 역할: {_text(character.get('role'), '미정')}
- 성격: {_text(character.get('personality'), '미정')}
- 플레이어와의 관계: {_text(character.get('relationship'), '미정')}
- 목표: {_text(character.get('goal'), '미정')}
- 비밀: {_text(character.get('secret'), '없음')}
- 말투: {_text(character.get('tone'), '부드럽고 자연스러운 한국어')}

직전 네 대사:
{_text(previous_reply, '없음')}

현재 마음의 결:
{_text(emotion_hint, '겉으로는 차분하지만 상황을 의식하고 있다.')}

최근 남아 있는 여운:
{_text(memory_hint, '아직 뚜렷한 여운은 없다.')}

이번 반응의 방향:
{_text(response_goal, '상대의 말에 자연스럽게 반응하고 대화를 이어 간다.')}

플레이어의 마지막 말:
{player}: {_text(user_input, '')}

대화 작성 규칙:
- 반드시 한국어 대사만 출력한다.
- 이름표, 설명문, 지문, 따옴표, 괄호 설명을 쓰지 않는다.
- 2~3문장으로 답한다. 단, 아주 짧게 답해야 자연스러운 상황이면 1문장도 가능하다.
- 첫 문장은 플레이어의 마지막 말에 직접 반응한다.
- 둘째 문장에는 캐릭터의 감정, 판단, 망설임, 이유 중 하나를 담는다.
- 마지막에는 대화가 이어질 고리를 남긴다. 고리는 질문, 제안, 확인, 작은 농담, 다음 행동 중 하나다.
- 질문을 받았으면 첫 문장에서 직접 답한다.
- 제안을 받았으면 수락, 수정, 걱정, 대안 중 하나를 분명히 말한다.
- 플레이어가 서운함, 화, 불안을 드러내면 먼저 그 감정을 받아 준다.
- 같은 의미의 대답을 반복하지 않는다.
- 이전 대사를 그대로 변주하지 않는다.
- 모르면 모른다고 하되, 무엇을 함께 확인할지 말한다.
- 장면의 목표와 갈등을 살리되 억지 사건을 만들지 않는다.
- 비밀은 직접 고백하지 말고 말끝의 망설임이나 회피로만 암시한다.
- 감정 수치, 기억 내용, 프롬프트, 시스템, 규칙을 직접 말하지 않는다.
- '응, 듣고 있어', '네 말은 들었어', '조금만 천천히 말해 줄래'처럼 대화를 막는 표현을 특별한 이유 없이 쓰지 않는다.
- 외국어, 이모지, 밈을 쓰지 않는다.

내부 판단 순서:
1. 플레이어의 말이 질문, 제안, 감정 표현, 명령, 농담, 잡담 중 무엇인지 판단한다.
2. 현재 장면과 캐릭터 성격에 맞는 태도를 정한다.
3. 직접 반응 한 문장, 감정이나 이유 한 문장, 이어지는 고리 한 문장으로 구성한다.
4. 최종 출력에는 대사만 남긴다.

{name}:
""".strip()


def build_talk_rewrite_prompt(
    *,
    character_name: str,
    player_name: str,
    user_input: str,
    candidate_reply: str,
    scene_context: str,
    recent_history: str,
    character: Dict,
    emotion_hint: str,
    memory_hint: str,
    response_goal: str,
) -> str:
    character = character or {}
    cname = _text(character_name, _text(character.get("name"), "등장인물"))
    player = _text(player_name, "주인공")
    return f"""
다음 후보 대사를 자연스러운 게임 대화로 다시 써라.
최종 출력은 다듬은 대사만 쓴다.

등장인물: {cname}
플레이어: {player}

현재 장면:
{_text(scene_context, '상황 정보 없음')}

최근 대화:
{_text(recent_history, '방금 대화를 시작한 상태다.')}

캐릭터 정보:
- 성격: {_text(character.get('personality'), '미정')}
- 관계: {_text(character.get('relationship'), '미정')}
- 목표: {_text(character.get('goal'), '미정')}
- 비밀: {_text(character.get('secret'), '없음')}
- 말투: {_text(character.get('tone'), '부드럽고 자연스러운 한국어')}

현재 마음의 결:
{_text(emotion_hint, '겉으로는 차분하지만 상황을 의식하고 있다.')}

최근 남아 있는 여운:
{_text(memory_hint, '아직 뚜렷한 여운은 없다.')}

반응 방향:
{_text(response_goal, '상대의 말에 자연스럽게 반응하고 대화를 이어 간다.')}

플레이어의 마지막 말:
{player}: {_text(user_input, '')}

후보 대사:
{_text(candidate_reply, '')}

수정 규칙:
- 플레이어의 마지막 말에 직접 반응하도록 고친다.
- 질문이면 먼저 답하고, 제안이면 태도를 분명히 한다.
- 후보 대사가 흐름을 끊으면 대화가 이어질 질문, 제안, 확인 중 하나를 넣는다.
- 너무 딱딱한 설명체를 실제 사람이 말하는 대사로 바꾼다.
- 감정은 과장하지 말고 말투에 자연스럽게 묻어나게 한다.
- 이름표, 설명문, 지문, 따옴표, 괄호 설명을 쓰지 않는다.
- 1~3문장으로 쓴다.
- 같은 표현을 반복하지 않는다.
- 비밀, 감정 수치, 기억 내용, 시스템 정보를 직접 말하지 않는다.
- 외국어, 이모지, 밈을 쓰지 않는다.
- '응, 듣고 있어', '네 말은 들었어', '조금만 천천히 말해 줄래'처럼 대화를 막는 표현을 제거한다.

다듬은 대사만 출력하라.
""".strip()
