using System.Collections.Generic;
using UnityEngine;
using StoryNet;
using CharacterInfo = StoryNet.CharacterInfo; // UnityEngine.CharacterInfo 와의 모호함 방지

/// <summary>
/// StoryClient 사용 예시.
///
/// 사용법:
///  1) 빈 GameObject 를 하나 만들고 StoryClient 컴포넌트를 붙인다. (host/port/token 설정)
///  2) 이 StoryClientExample 컴포넌트를 같은(또는 다른) GameObject 에 붙이고,
///     인스펙터에서 client 슬롯에 위 StoryClient 를 연결한다.
///  3) 재생하면 자동으로 연결 -> 스토리 생성 -> 첫 대사를 보낸다.
/// </summary>
public class StoryClientExample : MonoBehaviour
{
    [SerializeField] private StoryClient client;

    [Header("스토리 설정")]
    [SerializeField] private string sessionId = "story_demo01";
    [SerializeField] private string playerName = "지훈";
    [SerializeField] private string playerGender = "남";
    [SerializeField] private string genre = "학원 청춘물";
    [SerializeField, TextArea(3, 6)]
    private string world = "평범한 고등학교. 봄 학기 초, 새 학년이 시작된 지 얼마 안 된 시점.";
    [SerializeField] private int turnLimit = 6;

    private string _currentSessionId;
    private string _firstCharacter;

    private void Start()
    {
        if (client == null)
        {
            Debug.LogError("[StoryClientExample] StoryClient 를 연결해 주세요.");
            return;
        }

        Debug.Log("[Story] 서버에 연결 중...");
        client.Connect(
            onConnected: OnConnected,
            onError: err => Debug.LogError($"[Story] 연결 실패: {err}")
        );
    }

    private void OnConnected()
    {
        Debug.Log("[Story] 연결 성공. 스토리 생성 요청을 보냅니다.");

        var request = new StartStoryRequest
        {
            session_id = sessionId,
            player_name = playerName,
            player_gender = playerGender,
            genre = genre,
            world = world,
            turn_limit = turnLimit,
            characters = new List<CharacterInfo>
            {
                new CharacterInfo("서연")
                {
                    gender = "여",
                    role = "같은 반 친구",
                    personality = "차분하고 속을 잘 안 드러냄",
                    relationship = "최근 부쩍 가까워진 사이",
                    goal = "플레이어와 좀 더 솔직하게 이야기하고 싶어 한다",
                    secret = "사실 전학을 고민하고 있다",
                    tone = "조용하고 다정한 말투",
                },
            }
        };

        client.StartStory(
            request,
            onResult: OnStoryStarted,
            onError: err => Debug.LogError($"[Story] 스토리 생성 실패: {err}")
        );
    }

    private void OnStoryStarted(StoryStartedResponse resp)
    {
        _currentSessionId = sessionId;
        Debug.Log($"[Story] === 씬 {resp.scene_no} 생성 완료 ===\n{resp.scene_text}");

        if (resp.characters != null && resp.characters.Count > 0)
        {
            _firstCharacter = resp.characters[0];
            Debug.Log($"[Story] 등장인물: {string.Join(", ", resp.characters)}");

            // 데모: 곧바로 첫 대사를 건넨다.
            SendTalk(_firstCharacter, "안녕, 오늘 표정이 좀 안 좋아 보여서.");
        }
    }

    public void SendTalk(string characterName, string message)
    {
        if (string.IsNullOrEmpty(_currentSessionId))
        {
            Debug.LogWarning("[Story] 아직 스토리가 시작되지 않았습니다.");
            return;
        }

        Debug.Log($"[Story] {playerName} -> {characterName}: {message}");
        client.Talk(
            _currentSessionId, characterName, message,
            onResult: resp =>
            {
                Debug.Log($"[Story] {characterName}: {resp.text}");
                if (resp.scene_advanced)
                    Debug.Log($"[Story] === 다음 씬({resp.scene_no})으로 전환 ===\n{resp.scene_text}");
            },
            onError: err => Debug.LogError($"[Story] 대화 실패: {err}")
        );
    }
}