using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using CharacterInfo = StoryNet.CharacterInfo;
namespace StoryNet
{
    // 파이썬 서버(story_logic.py)와 1:1로 대응되는 데이터 구조다.
    // 프로토콜: [4바이트 빅엔디언 길이][UTF-8 JSON]
    // 직렬화는 Newtonsoft.Json(Json.NET)을 사용한다.
    //   Package Manager > Add package by name... > com.unity.nuget.newtonsoft-json

    /// <summary>
    /// 등장인물 한 명의 설정. start_story 요청에 담겨 서버로 전송된다.
    /// 비어 있는(null) 필드는 직렬화에서 생략되며, 서버가 기본값으로 채운다.
    /// </summary>
    [Serializable]
    public class CharacterInfo
    {
        [JsonProperty("name")] public string name;
        [JsonProperty("gender")] public string gender;        // "남" / "여" 등
        [JsonProperty("role")] public string role;          // 역할
        [JsonProperty("personality")] public string personality;   // 성격
        [JsonProperty("relationship")] public string relationship;  // 플레이어와의 관계
        [JsonProperty("goal")] public string goal;          // 목표
        [JsonProperty("secret")] public string secret;        // 비밀/숨김 정보
        [JsonProperty("tone")] public string tone;          // 말투

        public CharacterInfo() { }

        public CharacterInfo(string name)
        {
            this.name = name;
        }
    }

    /// <summary>
    /// 스토리 생성 요청. 세계관 + 등장인물 정보를 모두 담는다.
    /// </summary>
    public class StartStoryRequest
    {
        [JsonProperty("type")] public string type = "start_story";
        [JsonProperty("token")] public string token;
        [JsonProperty("session_id")] public string session_id;
        [JsonProperty("player_name")] public string player_name = "주인공";
        [JsonProperty("player_gender")] public string player_gender = "미정";
        [JsonProperty("genre")] public string genre = "일상";
        [JsonProperty("world")] public string world = "";        // 세계관 설정
        [JsonProperty("turn_limit")] public int turn_limit = 6;       // 씬 전환 턴 수
        [JsonProperty("characters")] public List<CharacterInfo> characters = new List<CharacterInfo>();
    }

    /// <summary>
    /// start_story 응답. 생성된 첫 장면(스토리)과 등장인물 이름 목록이 온다.
    /// type == "story_started" 이면 성공, "error" 이면 message에 사유가 담긴다.
    /// </summary>
    public class StoryStartedResponse
    {
        [JsonProperty("type")] public string type;
        [JsonProperty("scene_no")] public int scene_no;
        [JsonProperty("scene_text")] public string scene_text;   // 생성된 장면 본문
        [JsonProperty("characters")] public List<string> characters; // 등장인물 이름 목록
        [JsonProperty("message")] public string message;       // 오류 시 사유
    }

    /// <summary>
    /// talk 응답. 캐릭터의 대사와 씬 전환 여부가 온다.
    /// </summary>
    public class TalkResponse
    {
        [JsonProperty("type")] public string type;
        [JsonProperty("text")] public string text;            // 캐릭터 대사
        [JsonProperty("scene_advanced")] public bool scene_advanced;    // 씬이 넘어갔는지
        [JsonProperty("scene_no")] public int scene_no;
        [JsonProperty("scene_text")] public string scene_text;      // 넘어갔을 때만 채워짐
        [JsonProperty("gauge")] public int gauge = -1;         // 호감 게이지(0~100), 없으면 -1
        [JsonProperty("game_over")] public bool game_over;         // 게이지 0 → 게임오버
        [JsonProperty("message")] public string message;         // 오류 시 사유
    }

    /// <summary>
    /// get_state 응답에서 state 안에 들어오는 세션 스냅샷.
    /// </summary>
    public class SessionStateDto
    {
        [JsonProperty("session_id")] public string session_id;
        [JsonProperty("player_name")] public string player_name;
        [JsonProperty("player_gender")] public string player_gender;
        [JsonProperty("genre")] public string genre;
        [JsonProperty("world")] public string world;
        [JsonProperty("turn_limit")] public int turn_limit;
        [JsonProperty("scene_no")] public int scene_no;
        [JsonProperty("scene_text")] public string scene_text;
        [JsonProperty("turn_count")] public int turn_count;
        [JsonProperty("characters")] public List<CharacterInfo> characters;
    }

    public class GetStateResponse
    {
        [JsonProperty("type")] public string type;
        [JsonProperty("state")] public SessionStateDto state;
    }
}