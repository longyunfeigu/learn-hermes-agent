# s18: Voice & Vision (语音与视觉)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > [ s18 ] > s19 > s20 > s21 > s22 > s23 > s24`

> *主模型负责思考和对话，辅助模型负责"看"和"听"。两者用不同的模型，走不同的提供商，互不影响。*

![主模型 + 辅助模型双管线](../../illustrations/s18-voice-vision/01-framework-dual-model.png)

## 这一章要解决什么问题

到 s17，agent 能通过 accessibility tree "看"网页。但如果用户在微信里发了一张图片问"这是什么"，或者发了一段语音消息——agent 什么都做不了。

三个具体场景：

**看图片。** 用户发了一张截图问"这个报错什么意思"。agent 需要理解图片内容。

**听语音。** 用户在 Telegram 里发了一段语音消息。agent 收到的是一个 `.ogg` 音频文件，需要转成文字才能处理。

**说话。** agent 的回复是文字，但用户希望在 Telegram 里听到语音回复——像和真人聊天一样。

这三件事有一个共同特点：**主模型不需要也不应该直接做。**

## 建议联读

- [`s17-browser-automation.md`](./s17-browser-automation.md) — `browser_vision` 依赖本章的视觉模型
- [`s13-platform-adapters.md`](./s13-platform-adapters.md) — 语音消息在适配器里转文字

## 先解释几个名词

### 什么是辅助模型（auxiliary model）

Hermes Agent 用两套模型：

- **主模型**：跑每一轮对话，必须快、便宜（比如 Claude Haiku）
- **辅助模型**：只在需要时调用，可以慢一点但要专业（比如 Gemini Flash 做视觉）

为什么不用主模型做视觉？

- 主模型可能不支持多模态（便宜的文本模型没有视觉能力）
- 视觉分析偶尔才用一次，不值得让每轮对话都用贵的多模态模型
- 视觉模型失败不应该影响对话（辅助模型挂了，主对话继续）

### 什么是 MEDIA 标签

agent 的工具生成了一个音频文件（比如 TTS 生成的语音），它在工具返回值里写一个标记：`MEDIA:/path/to/audio.ogg`。

Gateway 看到这个标记后，不是把它当文字发给用户，而是调用适配器的 `send_voice()` 把音频文件作为语音消息发出去。

**MEDIA 标签让工具和 Gateway 解耦：工具不需要知道消息发到哪个平台，Gateway 不需要知道音频怎么生成的。**

## 从最笨的实现开始

让主模型直接看图片：

```python
def handle_vision(args, **kwargs):
    image_url = args["image_url"]
    question = args["question"]

    # 直接用主模型的多模态能力
    response = client.chat.completions.create(
        model=MODEL,  # 主模型
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }],
    )
    return response.choices[0].message.content
```

三个问题：

### 问题一：主模型可能没有视觉能力

如果 `MODEL` 是 Claude Haiku 或其他纯文本模型，这段代码会直接报错。你不能假设主模型支持多模态。

### 问题二：视觉分析很贵

多模态模型处理图片比处理文字贵得多。如果只为了偶尔看一张图就把主模型换成多模态的，每轮对话的成本都上去了。

### 问题三：外部图片 URL 不可靠

用户给了一个图片 URL，你直接传给模型 API。但这个 URL 可能已经过期（企业微信的临时链接只有 1 小时），也可能是内网地址（SSRF 风险）。你需要先下载到本地、验证、转 base64，再发给模型。

**解法：用独立的辅助模型处理视觉，和主模型完全分开。**

## 最小心智模型

```text
┌─────────────────────────────────────────────┐
│ 三种多媒体能力                                │
│                                             │
│  视觉（看图片）                               │
│    图片 → 下载 → base64 → 辅助视觉模型 → 文字描述  │
│                                             │
│  语音转文字 STT（听语音）                      │
│    音频文件 → Whisper / Groq → 文字           │
│                                             │
│  文字转语音 TTS（说话）                        │
│    文字 → Edge TTS / OpenAI → 音频文件        │
│    → MEDIA:/path → Gateway → 平台语音消息     │
└─────────────────────────────────────────────┘
```

三种能力各自独立：视觉用辅助视觉模型，STT 用 Whisper，TTS 用语音合成服务。它们和主模型没有依赖关系。

## 视觉：图片 → 文字描述

### 模型怎么知道要调 vision_analyze

没有任何特殊机制——和模型决定调 `terminal` 或 `read_file` 是同一个过程。

当用户在平台上发了一张图片时，适配器做了两件事：下载图片到本地，然后**把图片路径写进用户消息文本里**。模型收到的消息大致是：

```text
system prompt 里的工具列表包含：
  vision_analyze: "Analyze an image. Parameters: image_url (path or URL), question"

用户消息：
  "这个报错什么意思
   [Image: /home/user/.hermes/cache/images/abc123.jpg]"
```

模型看到消息里有图片路径 + 工具列表里有 vision_analyze → 自己决定调用。和看到用户说"帮我列一下文件"然后决定调 `terminal("ls")` 是同一个推理过程。

### 完整流程

```text
1. 用户在微信发了一张图片 + "这个报错什么意思"

2. 适配器：下载图片 → 缓存到 ~/.hermes/cache/images/abc123.jpg
   → 构造 MessageEvent(text="这个报错什么意思", media_urls=["/.../abc123.jpg"])

3. 传给 agent 时，图片路径拼进用户消息：
   "这个报错什么意思\n[Image: /.../abc123.jpg]"

4. 模型推理：有图片路径 + 有 vision_analyze 工具 → 调用
   → tool_call: vision_analyze(image_url="/.../abc123.jpg", question="这个报错什么意思")

5. vision_analyze handler 执行：
   → 读取图片 → 转 base64
   → 发给辅助视觉模型（不是主模型）
   → 辅助模型返回："这是一个 Python TypeError: 'NoneType' object is not iterable..."

6. tool_result 返回给主模型 → 主模型拿到描述后继续对话
```

### 为什么下载到本地再转 base64

不直接把 URL 传给模型 API：

- 企业微信的图片 URL 1 小时后过期，模型可能来不及下载
- URL 可能指向内网（SSRF）
- 下载时可以做大小验证（防止 50MB 图片撑爆内存）
- base64 所有提供商都支持，URL 有些不支持

### 辅助视觉模型怎么选

Hermes 按优先级自动选择：

```text
1. 用户配了 auxiliary.vision.provider → 用它
2. 主模型的提供商支持视觉 → 用同一个提供商
3. OpenRouter（默认 Gemini Flash）
4. Nous Portal（免费视觉模型）
5. 都不行 → 视觉不可用
```

在 config.yaml 里可以显式配置：

```yaml
auxiliary:
  vision:
    provider: "openrouter"
    model: "google/gemini-2.5-flash"
    timeout: 120  # 本地模型可能很慢
```

## 语音转文字（STT）：音频 → 文字

用户在 Telegram 发了一段语音消息。适配器收到的是一个 `.ogg` 音频文件。

### 完整流程

```text
Telegram 推来语音消息
    │
    v
TelegramAdapter
    │  下载音频 → 缓存到 ~/.hermes/cache/audio/voice_xxx.ogg
    │  调 transcribe_audio("voice_xxx.ogg")
    │
    v
STT 提供商（按配置选择）
    │
    ├── 本地 Whisper（免费，首次加载模型要 30 秒）
    ├── Groq（免费额度，<5 秒）
    ├── OpenAI（付费，<10 秒）
    └── Mistral（付费，<10 秒）
    │
    v
返回文字："帮我查一下明天的天气"
    │
    v
适配器把文字填进 MessageEvent.text
    → agent 收到的就是普通文字消息，不知道原来是语音
```

**关键设计：STT 发生在适配器里，agent 看到的永远是文字。** agent 不需要知道消息原来是语音还是文字。这和 s13 的"适配器负责翻译"是同一个思路。

### STT 提供商对比

| 提供商 | 免费？ | 速度 | 配置 |
|--------|--------|------|------|
| 本地 Whisper | 是 | 5-30 秒 | 首次要下载模型（~150MB） |
| Groq | 有免费额度 | <5 秒 | 需要 GROQ_API_KEY |
| OpenAI | 否 | <10 秒 | 需要 OPENAI_API_KEY |
| Mistral | 否 | <10 秒 | 需要 MISTRAL_API_KEY |

默认自动选择：有本地 Whisper 就用本地，没有就按 Groq → OpenAI → Mistral 顺序找。

## 文字转语音（TTS）：文字 → 音频

agent 想给用户发一条语音回复。

### 完整流程

```text
agent 调用 text_to_speech("今天北京天气晴朗，最高温度 28 度。")
    │
    v
TTS 提供商（按配置选择）
    │
    ├── Edge TTS（免费，100+ 语言）
    ├── OpenAI TTS（付费，高质量）
    ├── ElevenLabs（付费，最自然）
    └── 其他（Mistral、MiniMax、本地 NeuTTS）
    │
    v
生成音频文件 → ~/.hermes/cache/audio/tts_xxx.ogg
    │
    v
工具返回: "MEDIA:~/.hermes/cache/audio/tts_xxx.ogg"
    │
    v
Gateway 看到 MEDIA 标签
    │  → 调适配器的 send_voice(chat_id, audio_path)
    v
用户在 Telegram 收到语音消息气泡（不是文件附件）
```

### 为什么 Telegram 要 Opus 格式

Telegram 的语音消息气泡只认 Opus 编码的 `.ogg` 文件。如果你发 `.mp3`，它会显示为文件附件而不是语音气泡。

Hermes 的做法：检测当前平台是不是 Telegram，是的话把音频转成 Opus：

```python
platform = get_session_env("HERMES_SESSION_PLATFORM")
if platform == "telegram":
    # 转换成 Opus：ffmpeg -i input.mp3 -acodec libopus output.ogg
    convert_to_opus(audio_path)
```

有些 TTS 提供商（OpenAI、ElevenLabs）原生支持 Opus 输出，不需要转换。Edge TTS 输出 MP3，需要 ffmpeg 转。

### TTS 提供商对比

| 提供商 | 免费？ | 质量 | Opus 原生 |
|--------|--------|------|-----------|
| Edge TTS | 是 | 好 | 否（需 ffmpeg 转） |
| OpenAI | 否 | 高 | 是 |
| ElevenLabs | 否 | 最自然 | 是 |
| Mistral | 否 | 高 | 是 |

默认用 Edge TTS（免费，不需要 API key）。

## 用 Telegram 语音走一遍完整流程

用户在 Telegram 里发了一段语音问天气，agent 用语音回复。

```text
1. 用户在 Telegram 录了一段语音："帮我查一下明天的天气"

2. Telegram 适配器
   → 下载 .ogg 文件
   → transcribe_audio() → Whisper → "帮我查一下明天的天气"
   → MessageEvent(text="帮我查一下明天的天气")

3. GatewayRunner → agent 核心循环
   → agent 看到文字消息，调用 web_search 查天气
   → agent 组织回复，调用 text_to_speech("明天北京多云，最高 25 度")
   → TTS 生成 audio.ogg
   → agent 返回 "MEDIA:~/.hermes/cache/audio/audio.ogg"

4. Gateway 看到 MEDIA 标签
   → 调 TelegramAdapter.send_voice(chat_id, audio.ogg)
   → 用户在 Telegram 收到语音消息气泡
```

agent 全程只处理文字——STT 和 TTS 分别在入口和出口做，对核心循环透明。

## 如何接到主循环里

三种能力在架构中的位置不同：

```text
入站（适配器层）：
  语音消息 → STT → 文字 → MessageEvent
  图片消息 → 下载缓存 → 本地路径 → MessageEvent

核心循环（工具层）：
  vision_analyze 工具 → 辅助视觉模型 → 文字描述
  text_to_speech 工具 → TTS 提供商 → MEDIA 标签

出站（Gateway 层）：
  MEDIA 标签 → send_voice → 平台语音消息
```

STT 在适配器层做（agent 看到的是文字），视觉在工具层做（agent 主动调用），TTS 在工具层生成、Gateway 层投递。核心循环本身不处理任何多媒体。

## 初学者最容易犯的错

### 1. 用主模型做视觉分析

主模型是 Claude Haiku，不支持多模态。直接传图片会报错。

**修：视觉走辅助模型，和主模型完全分开。**

### 2. 把图片 URL 直接传给视觉模型

URL 可能过期或指向内网。

**修：先下载到本地、验证格式和大小、转 base64，再发给视觉模型。**

### 3. TTS 音频发到 Telegram 变成文件而不是语音气泡

发了 `.mp3` 格式。Telegram 语音气泡只认 Opus 编码的 `.ogg`。

**修：检测平台，Telegram 时转 Opus。**

### 4. STT 在核心循环里做，而不是在适配器里

如果 STT 是一个工具，agent 要先"知道"收到了语音消息，再决定调 STT 工具。但语音消息的格式每个平台都不一样——这正是适配器该做的事。

**修：STT 在适配器里做。MessageEvent 里只有文字，agent 不需要知道原来是语音。**

## 教学边界

这一章讲三种多媒体能力的架构，不讲每个提供商的 API 细节。

讲三件事：

1. **辅助模型的设计** — 为什么视觉和主对话用不同的模型
2. **三种能力的数据流** — 视觉（图片→文字）、STT（音频→文字）、TTS（文字→音频）
3. **它们在架构中的位置** — STT 在适配器层，视觉在工具层，TTS 在工具层 + Gateway 层

不讲的：

- 每种 TTS/STT 提供商的 API 调用细节 → 各家文档
- 音频编码（Opus、MP3、WAV）的技术细节 → 音频编码知识
- 视觉模型的选择和调优 → 模型评测话题
- CLI 语音模式（push-to-talk） → 是终端的交互增强

## 这一章和后续章节的关系

- **s13** 的适配器负责 STT 和媒体下载 → 本章定义 STT 的提供商和流程
- **s17** 的 `browser_vision` 用的就是本章的辅助视觉模型
- **s12** 的 Gateway 负责处理 MEDIA 标签 → 本章定义 MEDIA 标签的含义

## 学完这章后，你应该能回答

- 为什么视觉分析不用主模型，而是用辅助模型？
- 用户在 Telegram 发了一段语音，agent 收到的是什么？是音频文件还是文字？
- TTS 工具返回的 `MEDIA:/path/to/audio.ogg` 是怎么变成 Telegram 语音消息的？
- 为什么 Telegram 要 Opus 格式？发 MP3 会怎样？
- 视觉工具为什么不直接把图片 URL 传给模型，而是先下载再转 base64？

---

**一句话记住：主模型只处理文字。看图片用辅助视觉模型，听语音在适配器里转文字，说话用 TTS 工具生成音频。**
