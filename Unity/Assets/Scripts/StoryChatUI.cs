using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using StoryNet;
using CharacterInfo = StoryNet.CharacterInfo; // UnityEngine.CharacterInfo 와의 모호함 방지

/// <summary>
/// 비주얼노벨형 UI.
///  - 풀스크린 배경 이미지
///  - 캐릭터 입상(서 있는 그림) 여러 개를 배경 위에 배치
///  - 하단 대사창(이름표 + 대사) + 입력창
///
/// 빈 GameObject 에 이 스크립트만 붙이면 Canvas 전체가 코드로 생성된다.
///
/// 이미지는 서버가 주지 않으므로 인스펙터에서 직접 등록한다.
///  - background : 풀스크린 배경
///  - characterSprites : 캐릭터별 입상 (characterName 은 서버 캐릭터 이름과 일치시켜야 말할 때 강조됨)
///
/// 편집 모드(우상단 ··· 버튼으로 토글):
///  - 캐릭터 입상을 마우스로 드래그하면 이동
///  - 입상 위에서 마우스 휠을 굴리면 크기 조절
/// </summary>
public class StoryChatUI : MonoBehaviour
{
    [System.Serializable]
    public class CharacterSprite
    {
        public string characterName;            // 서버의 등장인물 이름과 동일하게
        public Sprite sprite;
        [Range(0f, 1f)] public float anchorX = 0.5f; // 가로 위치 (0 왼쪽 ~ 1 오른쪽)
        public float yOffset = 0f;              // 바닥에서의 세로 오프셋
        [Range(0.2f, 1.5f)] public float heightRatio = 0.95f; // 화면 높이 대비 입상 높이
    }

    [Header("연결 (다른 오브젝트의 StoryClient 를 여기로 드래그)")]
    [SerializeField] private StoryClient client;

    [Header("이미지")]
    public Sprite background;
    public List<CharacterSprite> characterSprites = new List<CharacterSprite>();
    public bool spriteEditMode = true;          // ··· 버튼으로 토글
    public bool dimNonSpeaker = true;           // 대화 상대만 밝게, 나머지는 어둡게
    public bool debugKeys = true;               // [테스트] F9: 게이지-10, F10: 즉시 게임오버

    [Header("스토리 기본값 (게임 시작 전 설정창의 초기값으로만 사용됨)")]
    public string playerName = "지훈";
    public string playerGender = "남";
    public string genre = "학원 청춘물";
    [TextArea(3, 6)]
    public string world = "평범한 고등학교. 봄 학기 초, 새 학년이 시작된 지 얼마 안 된 시점.";
    [HideInInspector] public string sessionId = "story_demo01"; // 시작 시 자동 생성됨

    public List<CharacterInfo> characters = new List<CharacterInfo>
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
        }
    };

    private const float REF_W = 1280f;
    private const float REF_H = 720f;
    private static readonly Color DIM = new Color(0.55f, 0.55f, 0.6f, 1f);

    private Font _font;
    private Image _background;
    private RectTransform _spriteLayer;
    private readonly Dictionary<string, Image> _sprites = new Dictionary<string, Image>();
    private readonly List<Image> _spriteOrder = new List<Image>();
    private readonly List<string> _spriteKeys = new List<string>();
    private GameObject _namePlate;
    private Text _nameText;
    private Text _dialogueText;
    private ScrollRect _dialogueScroll;
    private InputField _input;
    private Button _sendButton;

    private string _character;
    private bool _busy;

    // 호감 게이지 / 게임오버
    private Text _gaugeLabel;
    private RectTransform _gaugeFill;
    private const float GAUGE_W = 220f;
    private GameObject _gameOverRoot;
    private int _gauge = 100;   // 현재 게이지 값(테스트 디버그용 포함)

    // 설정창
    private GameObject _setupRoot;
    private Text _setupStatus;
    private Button _setupStartButton;
    private InputField _inPlayerName, _inGenre, _inWorld;
    private System.Func<string> _playerGenderGetter;
    private Transform _cardsParent;
    private readonly List<CharCard> _cards = new List<CharCard>();

    private class CharCard
    {
        public GameObject root;
        public InputField name, role, personality, relationship, goal, secret, tone;
        public System.Func<string> genderGetter;
    }

    private void Awake()
    {
        if (client == null) client = GetComponent<StoryClient>();
        if (client == null)
        {
            client = gameObject.AddComponent<StoryClient>();
            Debug.LogWarning("[StoryChatUI] StoryClient 자동 추가. 이미 다른 오브젝트에 있다면 Client 슬롯에 드래그하세요.");
        }

        EnsureEventSystem();
        LoadKoreanFont();
        BuildUI();
        BuildSprites();
        BuildSetupUI();
    }

    private void Start()
    {
        SetBusy(true);
        SetSetupStatus("서버에 연결 중...");
        client.Connect(
            onConnected: OnConnected,
            onError: err => SetSetupStatus($"[연결 실패] {err}  (호스트/포트/토큰 확인)"));
    }

    // ───────────────────────── 서버 흐름 ─────────────────────────

    private void OnConnected()
    {
        SetSetupStatus("연결됨 · 설정을 마치고 [게임 시작]을 누르세요.");
        if (_setupStartButton != null) _setupStartButton.interactable = true;
    }

    // 설정창의 [게임 시작] → 입력값을 모아 서버로 전송
    private void OnStartGameClicked()
    {
        playerName = Safe(_inPlayerName.text, "주인공");
        playerGender = _playerGenderGetter != null ? _playerGenderGetter() : "미정";
        genre = Safe(_inGenre.text, "일상");
        world = _inWorld.text ?? "";

        var list = new List<CharacterInfo>();
        foreach (var cc in _cards)
        {
            string nm = (cc.name.text ?? "").Trim();
            if (string.IsNullOrEmpty(nm)) continue; // 이름 없는 인물은 제외
            list.Add(new CharacterInfo(nm)
            {
                gender = cc.genderGetter != null ? cc.genderGetter() : "미정",
                role = cc.role.text.Trim(),
                personality = cc.personality.text.Trim(),
                relationship = cc.relationship.text.Trim(),
                goal = cc.goal.text.Trim(),
                secret = cc.secret.text.Trim(),
                tone = cc.tone.text.Trim(),
            });
        }
        if (list.Count == 0) { SetSetupStatus("등장인물을 최소 1명(이름 필수) 입력하세요."); return; }

        characters = list;
        sessionId = "story_" + System.Guid.NewGuid().ToString("N").Substring(0, 8);

        _setupStartButton.interactable = false;
        SetSetupStatus("스토리를 생성하는 중...");

        var req = new StartStoryRequest
        {
            session_id = sessionId,
            player_name = playerName,
            player_gender = playerGender,
            genre = genre,
            world = world,
            turn_limit = 0,                // 0 = 턴 제한 없음(서버가 씬 자동 전환 안 함)
            characters = characters,
        };
        client.StartStory(req, OnStoryStarted,
            err => { SetSetupStatus($"[스토리 생성 실패] {err}"); _setupStartButton.interactable = true; });
    }

    private void OnStoryStarted(StoryStartedResponse resp)
    {
        if (_setupRoot != null) _setupRoot.SetActive(false); // 설정창 닫고 게임 화면 노출
        SetBusy(false);
        if (resp.characters != null && resp.characters.Count > 0)
            _character = resp.characters[0];
        RemapSpriteKeys(resp.characters);   // 서버 이름에 스프라이트 연결
        UpdateGauge(100);                   // 호감 게이지 초기화
        ShowNarration(resp.scene_text);
        _input.ActivateInputField();
    }

    private void OnSendClicked()
    {
        if (_busy) return;
        string msg = _input.text.Trim();
        if (string.IsNullOrEmpty(msg)) return;
        if (string.IsNullOrEmpty(_character)) { ShowNarration("아직 스토리가 시작되지 않았습니다."); return; }

        _input.text = "";
        ShowLine(playerName, msg);
        SetBusy(true);

        client.Talk(sessionId, _character, msg,
            onResult: resp =>
            {
                SetBusy(false);
                ShowLine(_character, resp.text);
                if (resp.scene_advanced) ShowNarration(resp.scene_text);
                if (resp.gauge >= 0) UpdateGauge(resp.gauge);

                if (resp.game_over || (resp.gauge >= 0 && resp.gauge <= 0))
                {
                    ShowNarration("상대가 마음을 닫았다...");
                    ShowGameOver();
                    return;
                }
                _input.ActivateInputField();
            },
            onError: err => { SetBusy(false); ShowNarration($"[대화 실패] {err}"); _input.ActivateInputField(); });
    }

    // ───────────────────────── 표시 ─────────────────────────

    private void ShowLine(string speaker, string text)
    {
        bool narration = string.IsNullOrEmpty(speaker);
        _namePlate.SetActive(!narration);
        if (!narration) _nameText.text = speaker;

        // 한 줄을 로그에 누적 (덮어쓰지 않음 → 위로 스크롤해서 지난 대사 확인 가능)
        string entry;
        if (narration)
        {
            entry = $"<color=#C8CCD0>{text}</color>";
        }
        else
        {
            string nameColor = (speaker == playerName) ? "#7FB2FF" : "#FFD27F";
            entry = $"<color={nameColor}><b>{speaker}</b></color>\n{text}";
        }

        if (_dialogueText.text.Length > 0) _dialogueText.text += "\n\n";
        _dialogueText.text += entry;

        // 너무 길어지면 오래된 부분을 잘라낸다 (메모리/렌더 과부하 방지)
        const int MAX = 8000;
        if (_dialogueText.text.Length > MAX)
        {
            int cut = _dialogueText.text.IndexOf("\n\n", _dialogueText.text.Length - MAX);
            if (cut > 0) _dialogueText.text = _dialogueText.text.Substring(cut + 2);
        }

        Canvas.ForceUpdateCanvases();
        if (_dialogueScroll != null) _dialogueScroll.verticalNormalizedPosition = 0f; // 최신 대사로 내려가기

        UpdateSpriteHighlight(speaker);
    }

    // 말하는 캐릭터만 밝게. 플레이어가 말하거나 나레이션이면 캐릭터 모두 어둡게.
    private void UpdateSpriteHighlight(string speaker)
    {
        bool playerOrNarration = string.IsNullOrEmpty(speaker) || speaker == playerName;
        foreach (var kv in _sprites)
        {
            bool on;
            if (!dimNonSpeaker) on = true;                 // 효과 끄면 항상 밝게
            else if (playerOrNarration) on = false;        // 플레이어/나레이션: 캐릭터 모두 어둡게
            else if (_sprites.Count == 1) on = true;       // 캐릭터 1명이 말하는 중이면 밝게
            else on = string.Equals(kv.Key.Trim(), speaker.Trim()); // 말하는 캐릭터만 밝게
            kv.Value.color = on ? Color.white : DIM;
        }
    }

    private void ShowNarration(string text) => ShowLine(null, text);

    private void SetBusy(bool busy)
    {
        _busy = busy;
        if (_input != null) _input.interactable = !busy;
        if (_sendButton != null) _sendButton.interactable = !busy;
    }

    // ───────────────────────── UI 생성 ─────────────────────────

    private void EnsureEventSystem()
    {
        if (FindObjectOfType<EventSystem>() == null)
        {
            var es = new GameObject("EventSystem");
            es.AddComponent<EventSystem>();
            es.AddComponent<StandaloneInputModule>();
        }
    }

    private void LoadKoreanFont()
    {
        string[] names = { "Malgun Gothic", "맑은 고딕", "NanumGothic", "나눔고딕",
                           "Noto Sans CJK KR", "Noto Sans KR", "Apple SD Gothic Neo", "Arial" };
        _font = Font.CreateDynamicFontFromOSFont(names, 18);
    }

    private void BuildUI()
    {
        var canvasGO = new GameObject("StoryCanvas",
            typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
        canvasGO.transform.SetParent(transform, false);
        canvasGO.GetComponent<Canvas>().renderMode = RenderMode.ScreenSpaceOverlay;
        var scaler = canvasGO.GetComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        scaler.referenceResolution = new Vector2(REF_W, REF_H);
        scaler.matchWidthOrHeight = 0.5f;
        var canvas = canvasGO.transform;

        // 배경 (풀스크린)
        var bgGO = new GameObject("Background", typeof(RectTransform), typeof(Image));
        bgGO.transform.SetParent(canvas, false);
        _background = bgGO.GetComponent<Image>();
        _background.color = new Color(0.12f, 0.13f, 0.16f, 1f);
        _background.raycastTarget = false;
        _background.preserveAspect = false;
        if (background != null) { _background.sprite = background; }
        Stretch(bgGO, 0, 0, 0, 0);

        // 캐릭터 입상 레이어
        var layerGO = new GameObject("SpriteLayer", typeof(RectTransform));
        layerGO.transform.SetParent(canvas, false);
        _spriteLayer = layerGO.GetComponent<RectTransform>();
        Stretch(layerGO, 0, 0, 0, 0);

        // 하단 대사창
        BuildDialogue(canvas);

        // 우상단 ··· (편집 모드 토글)
        var menuBtn = MakePanel(canvas, "MenuButton", new Color(0.15f, 0.16f, 0.2f, 0.8f));
        var mrt = menuBtn.GetComponent<RectTransform>();
        mrt.anchorMin = mrt.anchorMax = new Vector2(1, 1);
        mrt.pivot = new Vector2(1, 1);
        mrt.sizeDelta = new Vector2(56, 40);
        mrt.anchoredPosition = new Vector2(-18, -16);
        var btn = menuBtn.AddComponent<Button>();
        var mt = MakeText(menuBtn.transform, "Dots", 22, TextAnchor.MiddleCenter);
        mt.text = "···"; Stretch(mt.gameObject, 0, 0, 0, 0);
        btn.onClick.AddListener(() =>
        {
            spriteEditMode = !spriteEditMode;
            ShowNarration(spriteEditMode
                ? "[편집 모드 ON] 캐릭터를 드래그해 이동, 휠로 크기 조절."
                : "[편집 모드 OFF]");
        });

        BuildGaugeUI(canvas);
        BuildGameOverUI(canvas);
    }

    // ───────────────────────── 호감 게이지 / 게임오버 ─────────────────────────

    private void BuildGaugeUI(Transform canvas)
    {
        var root = MakePanel(canvas, "GaugeBar", new Color(0, 0, 0, 0));
        var rt = root.GetComponent<RectTransform>();
        rt.anchorMin = rt.anchorMax = new Vector2(0, 1); rt.pivot = new Vector2(0, 1);
        rt.sizeDelta = new Vector2(GAUGE_W + 8, 46); rt.anchoredPosition = new Vector2(18, -14);

        _gaugeLabel = MakeText(root.transform, "Label", 14, TextAnchor.LowerLeft);
        _gaugeLabel.text = "호감 100";
        var lrt = _gaugeLabel.rectTransform;
        lrt.anchorMin = new Vector2(0, 1); lrt.anchorMax = new Vector2(1, 1); lrt.pivot = new Vector2(0, 1);
        lrt.sizeDelta = new Vector2(0, 18); lrt.anchoredPosition = Vector2.zero;

        var barBg = MakePanel(root.transform, "BarBg", new Color(0.1f, 0.1f, 0.12f, 0.85f));
        var brt = barBg.GetComponent<RectTransform>();
        brt.anchorMin = new Vector2(0, 1); brt.anchorMax = new Vector2(0, 1); brt.pivot = new Vector2(0, 1);
        brt.sizeDelta = new Vector2(GAUGE_W, 18); brt.anchoredPosition = new Vector2(0, -22);

        var fill = MakePanel(barBg.transform, "Fill", new Color(0.3f, 0.8f, 0.4f, 1f));
        _gaugeFill = fill.GetComponent<RectTransform>();
        _gaugeFill.anchorMin = new Vector2(0, 0); _gaugeFill.anchorMax = new Vector2(0, 1); _gaugeFill.pivot = new Vector2(0, 0.5f);
        _gaugeFill.sizeDelta = new Vector2(GAUGE_W, 0); _gaugeFill.anchoredPosition = Vector2.zero;
    }

    private void UpdateGauge(int g)
    {
        g = Mathf.Clamp(g, 0, 100);
        _gauge = g;
        float r = g / 100f;
        if (_gaugeFill != null)
        {
            _gaugeFill.sizeDelta = new Vector2(GAUGE_W * r, 0);
            var img = _gaugeFill.GetComponent<Image>();
            // 초록(높음) → 노랑 → 빨강(낮음)
            img.color = (r > 0.5f)
                ? Color.Lerp(new Color(0.9f, 0.8f, 0.2f), new Color(0.3f, 0.8f, 0.4f), (r - 0.5f) * 2f)
                : Color.Lerp(new Color(0.85f, 0.25f, 0.25f), new Color(0.9f, 0.8f, 0.2f), r * 2f);
        }
        if (_gaugeLabel != null) _gaugeLabel.text = $"호감 {g}";
    }

    private void BuildGameOverUI(Transform canvas)
    {
        _gameOverRoot = MakePanel(canvas, "GameOver", new Color(0.03f, 0.03f, 0.05f, 0.92f));
        Stretch(_gameOverRoot, 0, 0, 0, 0);

        var title = MakeText(_gameOverRoot.transform, "Title", 40, TextAnchor.MiddleCenter);
        title.text = "게임 오버";
        var trt = title.rectTransform;
        trt.anchorMin = trt.anchorMax = new Vector2(0.5f, 0.5f); trt.pivot = new Vector2(0.5f, 0.5f);
        trt.sizeDelta = new Vector2(600, 80); trt.anchoredPosition = new Vector2(0, 60);

        var sub = MakeText(_gameOverRoot.transform, "Sub", 18, TextAnchor.MiddleCenter);
        sub.text = "상대의 마음이 완전히 식었습니다.";
        sub.color = new Color(0.8f, 0.8f, 0.82f, 1f);
        var srt = sub.rectTransform;
        srt.anchorMin = srt.anchorMax = new Vector2(0.5f, 0.5f); srt.pivot = new Vector2(0.5f, 0.5f);
        srt.sizeDelta = new Vector2(600, 40); srt.anchoredPosition = new Vector2(0, 8);

        var btnGO = MakePanel(_gameOverRoot.transform, "Restart", new Color(0.27f, 0.45f, 0.85f, 1f));
        var grt = btnGO.GetComponent<RectTransform>();
        grt.anchorMin = grt.anchorMax = new Vector2(0.5f, 0.5f); grt.pivot = new Vector2(0.5f, 0.5f);
        grt.sizeDelta = new Vector2(200, 52); grt.anchoredPosition = new Vector2(0, -60);
        var b = btnGO.AddComponent<Button>();
        var bt = MakeText(btnGO.transform, "T", 18, TextAnchor.MiddleCenter);
        bt.text = "다시 시작"; Stretch(bt.gameObject, 0, 0, 0, 0);
        b.onClick.AddListener(() =>
            UnityEngine.SceneManagement.SceneManager.LoadScene(
                UnityEngine.SceneManagement.SceneManager.GetActiveScene().buildIndex));

        _gameOverRoot.SetActive(false);
    }

    private void ShowGameOver()
    {
        SetBusy(true);
        if (_gameOverRoot != null) _gameOverRoot.SetActive(true);
    }

    // [테스트용] 게임오버를 바로 확인하기 위한 디버그 키.
    //  F9  : 게이지 -10 (서서히 깎아 보기)
    //  F10 : 즉시 게임오버
    private void Update()
    {
        if (!debugKeys) return;
        if (_gameOverRoot != null && _gameOverRoot.activeSelf) return; // 이미 게임오버면 무시

        if (Input.GetKeyDown(KeyCode.F9))
        {
            UpdateGauge(_gauge - 10);
            ShowNarration($"[테스트] 게이지 -10 → {_gauge}");
            if (_gauge <= 0) { ShowNarration("상대가 마음을 닫았다..."); ShowGameOver(); }
        }
        else if (Input.GetKeyDown(KeyCode.F10))
        {
            UpdateGauge(0);
            ShowNarration("[테스트] 즉시 게임오버");
            ShowGameOver();
        }
    }

    private void BuildDialogue(Transform canvas)
    {
        // 대사 패널 (하단, 반투명)
        var panel = MakePanel(canvas, "DialoguePanel", new Color(0.04f, 0.05f, 0.08f, 0.62f));
        var prt = panel.GetComponent<RectTransform>();
        prt.anchorMin = new Vector2(0, 0);
        prt.anchorMax = new Vector2(1, 0);
        prt.pivot = new Vector2(0.5f, 0);
        prt.sizeDelta = new Vector2(-40, 220);
        prt.anchoredPosition = new Vector2(0, 16);

        // 이름표 (왼쪽 위, 내용에 맞춰 크기)
        _namePlate = MakePanel(panel.transform, "NamePlate", new Color(0.18f, 0.2f, 0.28f, 0.92f));
        var nrt = _namePlate.GetComponent<RectTransform>();
        nrt.anchorMin = nrt.anchorMax = new Vector2(0, 1);
        nrt.pivot = new Vector2(0, 1);
        nrt.anchoredPosition = new Vector2(20, -14);
        var hlg = _namePlate.AddComponent<HorizontalLayoutGroup>();
        hlg.padding = new RectOffset(16, 16, 6, 6);
        hlg.childControlWidth = hlg.childControlHeight = true;
        hlg.childForceExpandWidth = hlg.childForceExpandHeight = false;
        var nfit = _namePlate.AddComponent<ContentSizeFitter>();
        nfit.horizontalFit = nfit.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
        _nameText = MakeText(_namePlate.transform, "NameText", 18, TextAnchor.MiddleLeft);
        _nameText.text = "";

        // 대사 본문 (스크롤 영역: 일정 높이만 보이고 넘치면 스크롤됨)
        var scrollGO = new GameObject("DialogueScroll", typeof(RectTransform), typeof(ScrollRect));
        scrollGO.transform.SetParent(panel.transform, false);
        var srt = scrollGO.GetComponent<RectTransform>();
        srt.anchorMin = new Vector2(0, 0);
        srt.anchorMax = new Vector2(1, 1);
        srt.offsetMin = new Vector2(28, 58);     // 아래: 입력줄 공간
        srt.offsetMax = new Vector2(-28, -56);    // 위: 이름표 공간
        _dialogueScroll = scrollGO.GetComponent<ScrollRect>();
        _dialogueScroll.horizontal = false;
        _dialogueScroll.vertical = true;
        _dialogueScroll.scrollSensitivity = 22f;
        _dialogueScroll.movementType = ScrollRect.MovementType.Clamped;

        var vp = new GameObject("Viewport", typeof(RectTransform), typeof(RectMask2D));
        vp.transform.SetParent(scrollGO.transform, false);
        Stretch(vp, 0, 0, 0, 0);
        _dialogueScroll.viewport = vp.GetComponent<RectTransform>();

        // 내용 컨테이너: 레이아웃 그룹으로 감싸 하단 여백을 줘서 마지막 줄이 잘리지 않게 한다
        var contentGO = new GameObject("Content", typeof(RectTransform));
        contentGO.transform.SetParent(vp.transform, false);
        var crt = contentGO.GetComponent<RectTransform>();
        crt.anchorMin = new Vector2(0, 1);
        crt.anchorMax = new Vector2(1, 1);
        crt.pivot = new Vector2(0.5f, 1f);
        crt.sizeDelta = new Vector2(0, 0);
        crt.anchoredPosition = Vector2.zero;
        var vlg = contentGO.AddComponent<VerticalLayoutGroup>();
        vlg.padding = new RectOffset(4, 4, 6, 16); // 하단 16: 마지막 줄 디센더 잘림 방지
        vlg.childAlignment = TextAnchor.UpperLeft;
        vlg.childControlWidth = true;
        vlg.childControlHeight = true;
        vlg.childForceExpandWidth = true;
        vlg.childForceExpandHeight = false;
        var cfit = contentGO.AddComponent<ContentSizeFitter>();
        cfit.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
        cfit.horizontalFit = ContentSizeFitter.FitMode.Unconstrained;
        _dialogueScroll.content = crt;

        _dialogueText = MakeText(contentGO.transform, "DialogueText", 20, TextAnchor.UpperLeft);
        _dialogueText.text = "";

        // 입력줄 (대사창 하단)
        var inputRow = MakePanel(panel.transform, "InputRow", new Color(0, 0, 0, 0));
        var irt = inputRow.GetComponent<RectTransform>();
        irt.anchorMin = new Vector2(0, 0);
        irt.anchorMax = new Vector2(1, 0);
        irt.pivot = new Vector2(0.5f, 0);
        irt.sizeDelta = new Vector2(-56, 42);
        irt.anchoredPosition = new Vector2(0, 12);
        BuildInputBar(inputRow.transform);
    }

    private void BuildInputBar(Transform parent)
    {
        var ifGO = MakePanel(parent, "InputField", new Color(0.95f, 0.96f, 0.98f, 0.95f));
        Stretch(ifGO, 0, 92, 0, 0);
        _input = ifGO.AddComponent<InputField>();
        _input.lineType = InputField.LineType.SingleLine;

        var textComp = MakeText(ifGO.transform, "Text", 17, TextAnchor.MiddleLeft);
        textComp.color = new Color(0.1f, 0.1f, 0.1f, 1f);
        textComp.supportRichText = false;
        Stretch(textComp.gameObject, 12, 12, 4, 4);

        var ph = MakeText(ifGO.transform, "Placeholder", 17, TextAnchor.MiddleLeft);
        ph.color = new Color(0.45f, 0.45f, 0.45f, 1f);
        ph.text = "대사를 입력하세요...";
        Stretch(ph.gameObject, 12, 12, 4, 4);

        _input.textComponent = textComp;
        _input.placeholder = ph;
        _input.onEndEdit.AddListener(_ =>
        {
            if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter))
                OnSendClicked();
        });

        var btnGO = MakePanel(parent, "SendButton", new Color(0.27f, 0.45f, 0.85f, 1f));
        var brt = btnGO.GetComponent<RectTransform>();
        brt.anchorMin = new Vector2(1, 0);
        brt.anchorMax = new Vector2(1, 1);
        brt.pivot = new Vector2(1, 0.5f);
        brt.sizeDelta = new Vector2(84, 0);
        brt.anchoredPosition = Vector2.zero;
        _sendButton = btnGO.AddComponent<Button>();
        _sendButton.onClick.AddListener(OnSendClicked);
        var bt = MakeText(btnGO.transform, "Text", 16, TextAnchor.MiddleCenter);
        bt.text = "전송"; Stretch(bt.gameObject, 0, 0, 0, 0);
    }

    private void BuildSprites()
    {
        _sprites.Clear();
        _spriteOrder.Clear();
        _spriteKeys.Clear();
        foreach (var cs in characterSprites)
        {
            if (cs == null || cs.sprite == null) continue; // 그림만 있으면 표시(이름 없어도 OK)
            string key = string.IsNullOrEmpty(cs.characterName) ? $"_anon{_sprites.Count}" : cs.characterName;

            var go = new GameObject($"Sprite_{cs.characterName}", typeof(RectTransform), typeof(Image));
            go.transform.SetParent(_spriteLayer, false);
            var img = go.GetComponent<Image>();
            img.sprite = cs.sprite;
            img.raycastTarget = true; // 드래그를 위해

            var rt = go.GetComponent<RectTransform>();
            float h = REF_H * Mathf.Clamp(cs.heightRatio, 0.2f, 1.5f);
            float aspect = cs.sprite.rect.width / Mathf.Max(cs.sprite.rect.height, 1f);
            rt.sizeDelta = new Vector2(h * aspect, h);
            rt.anchorMin = rt.anchorMax = new Vector2(Mathf.Clamp01(cs.anchorX), 0);
            rt.pivot = new Vector2(0.5f, 0);
            rt.anchoredPosition = new Vector2(0, cs.yOffset);

            var handle = go.AddComponent<SpriteHandle>();
            handle.ui = this;

            _sprites[key] = img;
            _spriteOrder.Add(img);   // 인스펙터 등록 순서 기억
            _spriteKeys.Add(key);
        }
    }

    // 스토리 시작 시: 서버가 준 등장인물 이름에 스프라이트를 연결한다.
    // 1) 이름이 일치하는 스프라이트 먼저, 2) 못 찾으면 남은 스프라이트를 순서대로 배정.
    private void RemapSpriteKeys(List<string> names)
    {
        if (names == null || names.Count == 0 || _spriteOrder.Count == 0) return;

        var newMap = new Dictionary<string, Image>();
        var used = new bool[_spriteOrder.Count];

        foreach (var nm in names)
            for (int i = 0; i < _spriteOrder.Count; i++)
                if (!used[i] && string.Equals(_spriteKeys[i].Trim(), (nm ?? "").Trim()))
                { newMap[nm] = _spriteOrder[i]; used[i] = true; break; }

        foreach (var nm in names)
        {
            if (newMap.ContainsKey(nm)) continue;
            for (int i = 0; i < _spriteOrder.Count; i++)
                if (!used[i]) { newMap[nm] = _spriteOrder[i]; used[i] = true; break; }
        }

        for (int i = 0; i < _spriteOrder.Count; i++)
            if (!used[i]) newMap[_spriteKeys[i]] = _spriteOrder[i];

        _sprites.Clear();
        foreach (var kv in newMap) _sprites[kv.Key] = kv.Value;

        Debug.Log($"[Story] 대화 상대='{_character}' / 스프라이트 키=[{string.Join(", ", _sprites.Keys)}]");
    }

    // ───────────────────────── 설정창 ─────────────────────────

    private void SetSetupStatus(string s) { if (_setupStatus != null) _setupStatus.text = s; }
    private static string Safe(string s, string def) => string.IsNullOrWhiteSpace(s) ? def : s.Trim();

    private void BuildSetupUI()
    {
        var canvas = _spriteLayer.parent; // StoryCanvas
        _setupRoot = MakePanel(canvas, "SetupOverlay", new Color(0.06f, 0.07f, 0.10f, 0.99f));
        Stretch(_setupRoot, 0, 0, 0, 0);

        // 제목
        var title = MakeText(_setupRoot.transform, "Title", 26, TextAnchor.MiddleCenter);
        title.text = "게임 설정";
        var trt = title.rectTransform;
        trt.anchorMin = new Vector2(0, 1); trt.anchorMax = new Vector2(1, 1); trt.pivot = new Vector2(0.5f, 1);
        trt.sizeDelta = new Vector2(-40, 48); trt.anchoredPosition = new Vector2(0, -16);

        // 스크롤 영역
        var scrollGO = new GameObject("SetupScroll", typeof(RectTransform), typeof(ScrollRect));
        scrollGO.transform.SetParent(_setupRoot.transform, false);
        var srt = scrollGO.GetComponent<RectTransform>();
        srt.anchorMin = new Vector2(0, 0); srt.anchorMax = new Vector2(1, 1);
        srt.offsetMin = new Vector2(40, 96); srt.offsetMax = new Vector2(-40, -72);
        var scroll = scrollGO.GetComponent<ScrollRect>();
        scroll.horizontal = false; scroll.vertical = true; scroll.scrollSensitivity = 26f;
        scroll.movementType = ScrollRect.MovementType.Clamped;

        var vp = new GameObject("VP", typeof(RectTransform), typeof(RectMask2D));
        vp.transform.SetParent(scrollGO.transform, false); Stretch(vp, 0, 0, 0, 0);
        scroll.viewport = vp.GetComponent<RectTransform>();

        var content = new GameObject("Content", typeof(RectTransform));
        content.transform.SetParent(vp.transform, false);
        var crt = content.GetComponent<RectTransform>();
        crt.anchorMin = new Vector2(0, 1); crt.anchorMax = new Vector2(1, 1); crt.pivot = new Vector2(0.5f, 1); crt.sizeDelta = Vector2.zero;
        var cvlg = content.AddComponent<VerticalLayoutGroup>();
        cvlg.padding = new RectOffset(8, 8, 8, 16); cvlg.spacing = 4;
        cvlg.childControlWidth = cvlg.childControlHeight = true;
        cvlg.childForceExpandWidth = true; cvlg.childForceExpandHeight = false;
        var cfit = content.AddComponent<ContentSizeFitter>();
        cfit.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
        cfit.horizontalFit = ContentSizeFitter.FitMode.Unconstrained;
        scroll.content = crt;
        var c = content.transform;

        _inPlayerName = AddLabeledInput(c, "플레이어 이름", playerName, false);
        _playerGenderGetter = AddGenderRow(c, "플레이어 성별", playerGender);
        _inGenre = AddLabeledInput(c, "장르", genre, false);
        _inWorld = AddLabeledInput(c, "세계관", world, true);

        AddSpacer(c, 6);
        var sec = MakeText(c, "Sec", 18, TextAnchor.LowerLeft);
        sec.text = "등장인물";
        var sle = sec.gameObject.AddComponent<LayoutElement>(); sle.preferredHeight = 28; sle.flexibleWidth = 1;

        var cardsGO = new GameObject("Cards", typeof(RectTransform));
        cardsGO.transform.SetParent(c, false);
        var cvg = cardsGO.AddComponent<VerticalLayoutGroup>();
        cvg.spacing = 8; cvg.childControlWidth = cvg.childControlHeight = true;
        cvg.childForceExpandWidth = true; cvg.childForceExpandHeight = false;
        _cardsParent = cardsGO.transform;

        foreach (var ch in characters) AddCharacterCard(ch);
        if (_cards.Count == 0) AddCharacterCard(null);

        var addBtn = AddButton(c, "+ 등장인물 추가", new Color(0.2f, 0.4f, 0.3f, 1f), 38);
        addBtn.onClick.AddListener(() => AddCharacterCard(null));

        // 하단: 상태 + 게임 시작
        _setupStatus = MakeText(_setupRoot.transform, "Status", 14, TextAnchor.MiddleLeft);
        _setupStatus.color = new Color(0.72f, 0.74f, 0.78f, 1f);
        var strt = _setupStatus.rectTransform;
        strt.anchorMin = new Vector2(0, 0); strt.anchorMax = new Vector2(1, 0); strt.pivot = new Vector2(0, 0);
        strt.sizeDelta = new Vector2(-240, 28); strt.anchoredPosition = new Vector2(40, 22);
        _setupStatus.text = "서버에 연결 중...";

        var startGO = MakePanel(_setupRoot.transform, "StartGame", new Color(0.27f, 0.45f, 0.85f, 1f));
        var grt = startGO.GetComponent<RectTransform>();
        grt.anchorMin = new Vector2(1, 0); grt.anchorMax = new Vector2(1, 0); grt.pivot = new Vector2(1, 0);
        grt.sizeDelta = new Vector2(180, 46); grt.anchoredPosition = new Vector2(-40, 16);
        _setupStartButton = startGO.AddComponent<Button>();
        _setupStartButton.interactable = false; // 연결되면 활성화
        var gt = MakeText(startGO.transform, "T", 18, TextAnchor.MiddleCenter);
        gt.text = "게임 시작"; Stretch(gt.gameObject, 0, 0, 0, 0);
        _setupStartButton.onClick.AddListener(OnStartGameClicked);
    }

    private void AddCharacterCard(CharacterInfo seed)
    {
        seed = seed ?? new CharacterInfo("");
        var card = MakePanel(_cardsParent, "CharCard", new Color(0.12f, 0.13f, 0.17f, 1f));
        var vlg = card.AddComponent<VerticalLayoutGroup>();
        vlg.padding = new RectOffset(12, 12, 10, 12); vlg.spacing = 4;
        vlg.childControlWidth = vlg.childControlHeight = true;
        vlg.childForceExpandWidth = true; vlg.childForceExpandHeight = false;

        var cc = new CharCard { root = card };
        var del = AddButton(card.transform, "이 인물 삭제", new Color(0.5f, 0.2f, 0.22f, 1f), 30);
        cc.name = AddLabeledInput(card.transform, "이름", seed.name, false);
        cc.genderGetter = AddGenderRow(card.transform, "성별", seed.gender);
        cc.role = AddLabeledInput(card.transform, "역할", seed.role, false);
        cc.personality = AddLabeledInput(card.transform, "성격", seed.personality, false);
        cc.relationship = AddLabeledInput(card.transform, "플레이어와의 관계", seed.relationship, false);
        cc.goal = AddLabeledInput(card.transform, "목표", seed.goal, false);
        cc.secret = AddLabeledInput(card.transform, "비밀", seed.secret, false);
        cc.tone = AddLabeledInput(card.transform, "말투", seed.tone, false);

        del.onClick.AddListener(() => { _cards.Remove(cc); Destroy(card); });
        _cards.Add(cc);
    }

    // ── 설정창용 작은 빌더 ──

    private InputField AddLabeledInput(Transform parent, string label, string value, bool multiline)
    {
        AddLabel(parent, label);
        var ifGO = MakePanel(parent, "Input", new Color(0.16f, 0.17f, 0.21f, 1f));
        var le = ifGO.AddComponent<LayoutElement>();
        le.preferredHeight = multiline ? 88 : 38; le.flexibleWidth = 1;
        var input = ifGO.AddComponent<InputField>();
        input.lineType = multiline ? InputField.LineType.MultiLineNewline : InputField.LineType.SingleLine;

        var txt = MakeText(ifGO.transform, "Text", 16, multiline ? TextAnchor.UpperLeft : TextAnchor.MiddleLeft);
        txt.supportRichText = false;
        Stretch(txt.gameObject, 10, 10, 6, 6);
        var ph = MakeText(ifGO.transform, "PH", 16, multiline ? TextAnchor.UpperLeft : TextAnchor.MiddleLeft);
        ph.color = new Color(0.5f, 0.5f, 0.55f, 1f); ph.text = label;
        Stretch(ph.gameObject, 10, 10, 6, 6);

        input.textComponent = txt; input.placeholder = ph;
        input.text = value ?? "";
        return input;
    }

    private void AddLabel(Transform parent, string text)
    {
        var t = MakeText(parent, "Label", 14, TextAnchor.LowerLeft);
        t.color = new Color(0.75f, 0.77f, 0.8f, 1f); t.text = text;
        var le = t.gameObject.AddComponent<LayoutElement>(); le.preferredHeight = 22; le.flexibleWidth = 1;
    }

    private System.Func<string> AddGenderRow(Transform parent, string label, string initial)
    {
        AddLabel(parent, label);
        string[] v = { string.IsNullOrEmpty(initial) ? "여" : initial };
        var btnGO = MakePanel(parent, "Gender", new Color(0.2f, 0.22f, 0.28f, 1f));
        var le = btnGO.AddComponent<LayoutElement>(); le.preferredHeight = 38; le.flexibleWidth = 1;
        var btn = btnGO.AddComponent<Button>();
        var t = MakeText(btnGO.transform, "T", 16, TextAnchor.MiddleCenter);
        t.text = "성별: " + v[0]; Stretch(t.gameObject, 0, 0, 0, 0);
        btn.onClick.AddListener(() => { v[0] = v[0] == "여" ? "남" : "여"; t.text = "성별: " + v[0]; });
        return () => v[0];
    }

    private void AddSpacer(Transform parent, float h)
    {
        var go = new GameObject("Spacer", typeof(RectTransform));
        go.transform.SetParent(parent, false);
        var le = go.AddComponent<LayoutElement>(); le.preferredHeight = h;
    }

    private Button AddButton(Transform parent, string text, Color color, float height)
    {
        var go = MakePanel(parent, "Btn", color);
        var le = go.AddComponent<LayoutElement>(); le.preferredHeight = height; le.flexibleWidth = 1;
        var b = go.AddComponent<Button>();
        var t = MakeText(go.transform, "T", 16, TextAnchor.MiddleCenter);
        t.text = text; Stretch(t.gameObject, 0, 0, 0, 0);
        return b;
    }

    // ── 헬퍼 ──

    private GameObject MakePanel(Transform parent, string name, Color color)
    {
        var go = new GameObject(name, typeof(RectTransform), typeof(Image));
        go.transform.SetParent(parent, false);
        go.GetComponent<Image>().color = color;
        return go;
    }

    private Text MakeText(Transform parent, string name, int size, TextAnchor anchor)
    {
        var go = new GameObject(name, typeof(RectTransform));
        go.transform.SetParent(parent, false);
        var t = go.AddComponent<Text>();
        t.font = _font; t.fontSize = size; t.color = Color.white; t.alignment = anchor;
        t.horizontalOverflow = HorizontalWrapMode.Wrap;
        t.verticalOverflow = VerticalWrapMode.Overflow;
        return t;
    }

    private void Stretch(GameObject go, float left, float right, float bottom, float top)
    {
        var rt = go.GetComponent<RectTransform>();
        rt.anchorMin = Vector2.zero; rt.anchorMax = Vector2.one;
        rt.offsetMin = new Vector2(left, bottom);
        rt.offsetMax = new Vector2(-right, -top);
    }
}

/// <summary>
/// 캐릭터 입상에 붙어 편집 모드에서 드래그 이동 + 휠 크기조절을 처리한다.
/// </summary>
public class SpriteHandle : MonoBehaviour, IDragHandler, IScrollHandler
{
    public StoryChatUI ui;
    private RectTransform _rt;
    private Canvas _canvas;

    private void Awake()
    {
        _rt = GetComponent<RectTransform>();
        _canvas = GetComponentInParent<Canvas>();
    }

    public void OnDrag(PointerEventData e)
    {
        if (ui == null || !ui.spriteEditMode) return;
        float s = _canvas != null ? _canvas.scaleFactor : 1f;
        _rt.anchoredPosition += e.delta / Mathf.Max(s, 0.0001f);
    }

    public void OnScroll(PointerEventData e)
    {
        if (ui == null || !ui.spriteEditMode) return;
        float f = 1f + e.scrollDelta.y * 0.08f;
        Vector2 size = _rt.sizeDelta * f;
        if (size.y < 80f || size.y > 2400f) return; // 과도한 축소/확대 방지
        _rt.sizeDelta = size;
    }
}