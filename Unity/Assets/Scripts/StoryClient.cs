using System;
using System.Collections.Concurrent;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using Newtonsoft.Json;
using UnityEngine;

namespace StoryNet
{
    /// <summary>
    /// 파이썬 스토리 서버와 TCP로 통신하는 클라이언트.
    ///
    /// - 연결을 한 번 맺어 두고(소켓 유지) start_story / talk / get_state 를 반복 요청한다.
    /// - 모든 소켓 IO는 백그라운드 스레드에서 처리하므로 게임 프레임을 막지 않는다.
    /// - 콜백(onResult/onError)은 항상 Unity 메인 스레드에서 호출되므로
    ///   콜백 안에서 GameObject/UI 등을 안전하게 만질 수 있다.
    ///
    /// 사용법은 StoryClientExample.cs 참고.
    /// </summary>
    public class StoryClient : MonoBehaviour
    {
        [Header("서버 정보")]
        public string host = "127.0.0.1";
        public int port = 5767;
        public string token = "change_this_to_a_long_random_string";

        public bool IsConnected { get; private set; }

        // 백그라운드 -> 메인 스레드로 넘길 작업 큐
        private readonly ConcurrentQueue<Action> _mainThreadActions = new ConcurrentQueue<Action>();
        // 메인 -> 백그라운드로 넘길 요청 큐 (한 번에 하나씩 직렬 처리)
        private readonly BlockingCollection<PendingRequest> _requestQueue = new BlockingCollection<PendingRequest>();

        private TcpClient _tcp;
        private NetworkStream _stream;
        private Thread _worker;
        private volatile bool _running;

        private Action _onConnected;
        private Action<string> _onConnectError;

        private class PendingRequest
        {
            public string Json;
            public Action<string> OnResponseRaw; // 메인 스레드에서 원본 JSON과 함께 호출
            public Action<string> OnError;       // 메인 스레드에서 네트워크 오류 사유와 함께 호출
        }

        // ─────────────────────────────────────────────────────────────
        // 공개 API
        // ─────────────────────────────────────────────────────────────

        /// <summary>
        /// 서버에 연결하고 ping/pong 으로 토큰을 검증한다.
        /// </summary>
        public void Connect(Action onConnected = null, Action<string> onError = null)
        {
            if (_running)
            {
                onError?.Invoke("이미 연결되어 있거나 연결 시도 중입니다.");
                return;
            }

            _onConnected = onConnected;
            _onConnectError = onError;
            _running = true;

            _worker = new Thread(WorkerLoop) { IsBackground = true, Name = "StoryClientWorker" };
            _worker.Start();
        }

        /// <summary>
        /// 세계관 + 등장인물 정보를 보내 스토리를 생성한다.
        /// 응답(StoryStartedResponse)에는 생성된 장면과 등장인물 목록이 담긴다.
        /// </summary>
        public void StartStory(StartStoryRequest request,
                               Action<StoryStartedResponse> onResult,
                               Action<string> onError = null)
        {
            request.token = token;
            EnqueueTyped(request, onResult, onError, "story_started");
        }

        /// <summary>
        /// 특정 등장인물에게 말을 건다.
        /// </summary>
        public void Talk(string sessionId, string characterName, string userInput,
                         Action<TalkResponse> onResult, Action<string> onError = null)
        {
            var payload = new
            {
                type = "talk",
                token = token,
                session_id = sessionId,
                character_name = characterName,
                user_input = userInput,
            };
            EnqueueTyped(payload, onResult, onError, "reply");
        }

        /// <summary>
        /// 현재 세션 상태를 조회한다.
        /// </summary>
        public void GetState(string sessionId,
                             Action<GetStateResponse> onResult,
                             Action<string> onError = null)
        {
            var payload = new { type = "get_state", token = token, session_id = sessionId };

            string json = JsonConvert.SerializeObject(payload, SerializerSettings);
            _requestQueue.Add(new PendingRequest
            {
                Json = json,
                OnResponseRaw = raw =>
                {
                    var resp = JsonConvert.DeserializeObject<GetStateResponse>(raw);
                    onResult?.Invoke(resp);
                },
                OnError = msg => onError?.Invoke(msg),
            });
        }

        /// <summary>
        /// 연결을 끊는다.
        /// </summary>
        public void Disconnect()
        {
            _running = false;
            _requestQueue.TryAdd(null); // 워커가 Take() 에서 깨어나도록
            CloseSocket();
            IsConnected = false;
        }

        // ─────────────────────────────────────────────────────────────
        // 내부 구현
        // ─────────────────────────────────────────────────────────────

        // 응답 type 이 기대값이면 onResult, "error"면 onError 로 라우팅하는 공통 헬퍼.
        private void EnqueueTyped<TResp>(object requestObj,
                                         Action<TResp> onResult,
                                         Action<string> onError,
                                         string expectedType) where TResp : class
        {
            if (!_running)
            {
                onError?.Invoke("서버에 연결되어 있지 않습니다.");
                return;
            }

            string json = JsonConvert.SerializeObject(requestObj, SerializerSettings);
            _requestQueue.Add(new PendingRequest
            {
                Json = json,
                OnResponseRaw = raw =>
                {
                    // 먼저 type/message 만 가볍게 확인
                    var probe = JsonConvert.DeserializeObject<ErrorProbe>(raw);
                    if (probe != null && probe.type == "error")
                    {
                        onError?.Invoke(probe.message ?? "알 수 없는 서버 오류");
                        return;
                    }
                    var resp = JsonConvert.DeserializeObject<TResp>(raw);
                    onResult?.Invoke(resp);
                },
                OnError = msg => onError?.Invoke(msg),
            });
        }

        private class ErrorProbe
        {
            [JsonProperty("type")] public string type;
            [JsonProperty("message")] public string message;
        }

        private static readonly JsonSerializerSettings SerializerSettings = new JsonSerializerSettings
        {
            NullValueHandling = NullValueHandling.Ignore, // 비어 있는 캐릭터 필드는 보내지 않음
        };

        private void WorkerLoop()
        {
            // 1) 연결 + ping/pong
            try
            {
                _tcp = new TcpClient();
                var ar = _tcp.BeginConnect(host, port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(TimeSpan.FromSeconds(10)))
                {
                    _tcp.Close();
                    throw new Exception("연결 시간 초과");
                }
                _tcp.EndConnect(ar);
                _tcp.NoDelay = true;
                _stream = _tcp.GetStream();

                SendFramed("{\"type\":\"ping\",\"token\":" + JsonConvert.ToString(token) + "}");
                string pong = ReadFramed();
                if (pong == null || !pong.Contains("\"pong\""))
                    throw new Exception("서버 응답이 올바르지 않습니다 (토큰 확인).");

                IsConnected = true;
                Dispatch(() => _onConnected?.Invoke());
            }
            catch (Exception e)
            {
                _running = false;
                IsConnected = false;
                CloseSocket();
                string msg = e.Message;
                Dispatch(() => _onConnectError?.Invoke(msg));
                return;
            }

            // 2) 요청 큐 직렬 처리 (요청 1건 -> 응답 1건)
            try
            {
                while (_running)
                {
                    PendingRequest req = _requestQueue.Take(); // 블로킹
                    if (req == null) break; // Disconnect 신호

                    try
                    {
                        SendFramed(req.Json);
                        string raw = ReadFramed();
                        if (raw == null)
                            throw new Exception("서버 연결이 끊어졌습니다.");

                        var handler = req.OnResponseRaw;
                        Dispatch(() => handler?.Invoke(raw));
                    }
                    catch (Exception e)
                    {
                        string msg = e.Message;
                        var onErr = req.OnError;
                        Dispatch(() => onErr?.Invoke(msg));
                        break; // 소켓이 깨졌을 가능성이 높으므로 루프 종료
                    }
                }
            }
            finally
            {
                IsConnected = false;
                _running = false;
                CloseSocket();
            }
        }

        // [4바이트 빅엔디언 길이][UTF-8 JSON] 형식으로 전송
        private void SendFramed(string json)
        {
            byte[] payload = Encoding.UTF8.GetBytes(json);
            int len = payload.Length;
            byte[] header = new byte[4];
            header[0] = (byte)((len >> 24) & 0xFF);
            header[1] = (byte)((len >> 16) & 0xFF);
            header[2] = (byte)((len >> 8) & 0xFF);
            header[3] = (byte)(len & 0xFF);

            _stream.Write(header, 0, 4);
            _stream.Write(payload, 0, payload.Length);
            _stream.Flush();
        }

        // 한 프레임을 읽어 JSON 문자열로 반환. 연결 종료 시 null.
        private string ReadFramed()
        {
            byte[] header = ReadExact(4);
            if (header == null) return null;
            int len = (header[0] << 24) | (header[1] << 16) | (header[2] << 8) | header[3];
            if (len < 0) return null;
            byte[] payload = ReadExact(len);
            if (payload == null) return null;
            return Encoding.UTF8.GetString(payload);
        }

        // n바이트를 모두 읽을 때까지 반복 (파이썬 recvall 과 동일)
        private byte[] ReadExact(int n)
        {
            byte[] buf = new byte[n];
            int off = 0;
            while (off < n)
            {
                int read = _stream.Read(buf, off, n - off);
                if (read <= 0) return null;
                off += read;
            }
            return buf;
        }

        private void CloseSocket()
        {
            try { _stream?.Close(); } catch { }
            try { _tcp?.Close(); } catch { }
            _stream = null;
            _tcp = null;
        }

        private void Dispatch(Action a)
        {
            _mainThreadActions.Enqueue(a);
        }

        private void Update()
        {
            // 백그라운드에서 쌓인 콜백을 메인 스레드에서 실행
            while (_mainThreadActions.TryDequeue(out var action))
            {
                try { action?.Invoke(); }
                catch (Exception e) { Debug.LogException(e); }
            }
        }

        private void OnDestroy()
        {
            Disconnect();
        }

        private void OnApplicationQuit()
        {
            Disconnect();
        }
    }
}