# s18: Voice & Vision

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > [ s18 ] > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *The primary model handles thinking and conversation; auxiliary models handle "seeing" and "hearing." They use different models, go through different providers, and don't affect each other.*

![Main Model + Auxiliary Models](../../illustrations/en/s18-voice-vision/01-framework-dual-model.png)

## What problem does this chapter solve

Through s17, the agent can "see" web pages via the accessibility tree. But if a user sends a photo on WeChat asking "What is this?" or sends a voice message -- the agent can't do anything.

Three concrete scenarios:

**Seeing images.** A user sends a screenshot asking "What does this error mean?" The agent needs to understand the image content.

**Hearing voice.** A user sends a voice message on Telegram. The agent receives a `.ogg` audio file and needs to transcribe it to text before it can process anything.

**Speaking.** The agent's replies are text, but the user wants to hear a voice reply on Telegram -- like chatting with a real person.

These three things share one trait: **the primary model doesn't need to and shouldn't handle them directly.**

## Suggested reading

- [`s17-browser-automation.md`](./s17-browser-automation.md) -- `browser_vision` relies on this chapter's vision model
- [`s13-platform-adapters.md`](./s13-platform-adapters.md) -- voice messages are transcribed to text in the adapter

## Key terms

### What is an auxiliary model

Hermes Agent uses two sets of models:

- **Primary model**: Runs every conversation turn; must be fast and cheap (e.g., Claude Haiku)
- **Auxiliary model**: Called only when needed; can be slower but must be specialized (e.g., Gemini Flash for vision)

Why not use the primary model for vision?

- The primary model may not support multimodal input (cheap text models lack vision capabilities)
- Vision analysis is only needed occasionally -- not worth using an expensive multimodal model for every turn
- A vision model failure shouldn't break the conversation (if the auxiliary model goes down, the main dialogue continues)

### What is a MEDIA tag

When an agent tool generates an audio file (e.g., TTS-generated speech), it writes a marker in the tool's return value: `MEDIA:/path/to/audio.ogg`.

When the Gateway sees this marker, instead of sending it as text to the user, it calls the adapter's `send_voice()` to deliver the audio file as a voice message.

**The MEDIA tag decouples tools from the Gateway: tools don't need to know which platform the message goes to, and the Gateway doesn't need to know how the audio was generated.**

## Starting with the simplest implementation

Have the primary model look at the image directly:

```python
def handle_vision(args, **kwargs):
    image_url = args["image_url"]
    question = args["question"]

    # Use the primary model's multimodal capabilities directly
    response = client.chat.completions.create(
        model=MODEL,  # Primary model
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

Three problems:

### Problem 1: The primary model may lack vision capabilities

If `MODEL` is Claude Haiku or another text-only model, this code throws an error. You cannot assume the primary model supports multimodal input.

### Problem 2: Vision analysis is expensive

Processing images with a multimodal model costs much more than processing text. If you switch to a multimodal model just for the occasional image, every conversation turn gets more expensive.

### Problem 3: External image URLs are unreliable

The user provides an image URL that you pass directly to the model API. But the URL may have expired (WeChat Work temporary links last only 1 hour), or it may point to an internal network address (SSRF risk). You need to download locally, validate, and convert to base64 before sending to the model.

**Solution: Use an independent auxiliary model for vision, completely separate from the primary model.**

## Minimal mental model

```text
+---------------------------------------------+
| Three multimedia capabilities                |
|                                              |
|  Vision (seeing images)                      |
|    Image -> download -> base64 -> auxiliary   |
|    vision model -> text description           |
|                                              |
|  Speech-to-Text STT (hearing voice)          |
|    Audio file -> Whisper / Groq -> text       |
|                                              |
|  Text-to-Speech TTS (speaking)               |
|    Text -> Edge TTS / OpenAI -> audio file    |
|    -> MEDIA:/path -> Gateway -> platform      |
|    voice message                              |
+---------------------------------------------+
```

The three capabilities are independent: vision uses the auxiliary vision model, STT uses Whisper, and TTS uses a speech synthesis service. None of them depend on the primary model.

## Vision: image -> text description

### How the model knows to call vision_analyze

There is no special mechanism -- it's the same process as when the model decides to call `terminal` or `read_file`.

When a user sends an image on a platform, the adapter does two things: downloads the image locally, then **includes the image path in the user's message text**. The message the model receives looks roughly like:

```text
The tool list in the system prompt includes:
  vision_analyze: "Analyze an image. Parameters: image_url (path or URL), question"

User message:
  "What does this error mean?
   [Image: /home/user/.hermes/cache/images/abc123.jpg]"
```

The model sees an image path in the message + vision_analyze in the tool list -> it decides to call it on its own. This is the same reasoning process as seeing the user say "list my files" and deciding to call `terminal("ls")`.

### Full flow

```text
1. A user sends an image on WeChat + "What does this error mean?"

2. Adapter: downloads the image -> caches to ~/.hermes/cache/images/abc123.jpg
   -> constructs MessageEvent(text="What does this error mean?", media_urls=["/.../abc123.jpg"])

3. When passed to the agent, the image path is appended to the user message:
   "What does this error mean?\n[Image: /.../abc123.jpg]"

4. Model reasoning: image path present + vision_analyze tool available -> call it
   -> tool_call: vision_analyze(image_url="/.../abc123.jpg", question="What does this error mean?")

5. vision_analyze handler executes:
   -> Reads the image -> converts to base64
   -> Sends to the auxiliary vision model (not the primary model)
   -> Auxiliary model returns: "This is a Python TypeError: 'NoneType' object is not iterable..."

6. tool_result is returned to the primary model -> the primary model continues the conversation with the description
```

### Why download locally and convert to base64

Why not pass the URL directly to the model API:

- WeChat Work image URLs expire after 1 hour; the model may not download in time
- The URL might point to an internal network (SSRF)
- Downloading locally allows size validation (prevents a 50MB image from blowing up memory)
- Base64 is supported by all providers; URL support varies

### How the auxiliary vision model is selected

Hermes auto-selects by priority:

```text
1. User configured auxiliary.vision.provider -> use it
2. The primary model's provider supports vision -> use the same provider
3. OpenRouter (default: Gemini Flash)
4. Nous Portal (free vision model)
5. None available -> vision is disabled
```

Explicit configuration in config.yaml:

```yaml
auxiliary:
  vision:
    provider: "openrouter"
    model: "google/gemini-2.5-flash"
    timeout: 120  # Local models may be slow
```

## Speech-to-Text (STT): audio -> text

A user sends a voice message on Telegram. The adapter receives a `.ogg` audio file.

### Full flow

```text
Telegram pushes a voice message
    |
    v
TelegramAdapter
    |  Downloads audio -> caches to ~/.hermes/cache/audio/voice_xxx.ogg
    |  Calls transcribe_audio("voice_xxx.ogg")
    |
    v
STT provider (selected by configuration)
    |
    +-- Local Whisper (free, first load takes ~30 seconds)
    +-- Groq (free tier, <5 seconds)
    +-- OpenAI (paid, <10 seconds)
    +-- Mistral (paid, <10 seconds)
    |
    v
Returns text: "Check tomorrow's weather for me"
    |
    v
The adapter fills the text into MessageEvent.text
    -> The agent receives an ordinary text message, unaware it was originally voice
```

**Key design: STT happens in the adapter; the agent always sees text.** The agent doesn't need to know whether the message was originally voice or text. This follows the same principle as s13's "the adapter is responsible for translation."

### STT provider comparison

| Provider | Free? | Speed | Configuration |
|----------|-------|-------|---------------|
| Local Whisper | Yes | 5-30 seconds | Model download required on first use (~150MB) |
| Groq | Free tier available | <5 seconds | Requires GROQ_API_KEY |
| OpenAI | No | <10 seconds | Requires OPENAI_API_KEY |
| Mistral | No | <10 seconds | Requires MISTRAL_API_KEY |

Auto-selection by default: use local Whisper if available; otherwise try Groq -> OpenAI -> Mistral in order.

## Text-to-Speech (TTS): text -> audio

The agent wants to send a voice reply to the user.

### Full flow

```text
The agent calls text_to_speech("Clear skies in Beijing today, high of 28 degrees.")
    |
    v
TTS provider (selected by configuration)
    |
    +-- Edge TTS (free, 100+ languages)
    +-- OpenAI TTS (paid, high quality)
    +-- ElevenLabs (paid, most natural)
    +-- Others (Mistral, MiniMax, local NeuTTS)
    |
    v
Generates audio file -> ~/.hermes/cache/audio/tts_xxx.ogg
    |
    v
Tool returns: "MEDIA:~/.hermes/cache/audio/tts_xxx.ogg"
    |
    v
Gateway sees the MEDIA tag
    |  -> calls adapter's send_voice(chat_id, audio_path)
    v
The user receives a voice message bubble on Telegram (not a file attachment)
```

### Why Telegram requires Opus format

Telegram's voice message bubble only recognizes Opus-encoded `.ogg` files. If you send an `.mp3`, it appears as a file attachment rather than a voice bubble.

Hermes's approach: detect whether the current platform is Telegram; if so, convert the audio to Opus:

```python
platform = get_session_env("HERMES_SESSION_PLATFORM")
if platform == "telegram":
    # Convert to Opus: ffmpeg -i input.mp3 -acodec libopus output.ogg
    convert_to_opus(audio_path)
```

Some TTS providers (OpenAI, ElevenLabs) natively support Opus output and don't need conversion. Edge TTS outputs MP3, which requires ffmpeg conversion.

### TTS provider comparison

| Provider | Free? | Quality | Native Opus |
|----------|-------|---------|-------------|
| Edge TTS | Yes | Good | No (needs ffmpeg) |
| OpenAI | No | High | Yes |
| ElevenLabs | No | Most natural | Yes |
| Mistral | No | High | Yes |

Default: Edge TTS (free, no API key required).

## Full end-to-end flow with Telegram voice

A user sends a voice message on Telegram asking about the weather; the agent replies with voice.

```text
1. The user records a voice message on Telegram: "Check tomorrow's weather for me"

2. Telegram adapter
   -> Downloads the .ogg file
   -> transcribe_audio() -> Whisper -> "Check tomorrow's weather for me"
   -> MessageEvent(text="Check tomorrow's weather for me")

3. GatewayRunner -> agent core loop
   -> The agent sees a text message, calls web_search for weather
   -> The agent composes a reply, calls text_to_speech("Cloudy in Beijing tomorrow, high of 25 degrees")
   -> TTS generates audio.ogg
   -> The agent returns "MEDIA:~/.hermes/cache/audio/audio.ogg"

4. Gateway sees the MEDIA tag
   -> Calls TelegramAdapter.send_voice(chat_id, audio.ogg)
   -> The user receives a voice message bubble on Telegram
```

Throughout, the agent only handles text -- STT and TTS are performed at the entry and exit points respectively, transparent to the core loop.

## How it plugs into the main loop

The three capabilities sit at different layers of the architecture:

```text
Inbound (adapter layer):
  Voice message -> STT -> text -> MessageEvent
  Image message -> download & cache -> local path -> MessageEvent

Core loop (tool layer):
  vision_analyze tool -> auxiliary vision model -> text description
  text_to_speech tool -> TTS provider -> MEDIA tag

Outbound (Gateway layer):
  MEDIA tag -> send_voice -> platform voice message
```

STT happens at the adapter layer (the agent sees text), vision happens at the tool layer (the agent calls it proactively), and TTS is generated at the tool layer and delivered at the Gateway layer. The core loop itself handles no multimedia.

## Common beginner mistakes

### 1. Using the primary model for vision analysis

The primary model is Claude Haiku, which doesn't support multimodal input. Passing it an image throws an error.

**Fix: Route vision through the auxiliary model, completely separate from the primary model.**

### 2. Passing an image URL directly to the vision model

The URL may be expired or point to an internal network.

**Fix: Download locally first, validate format and size, convert to base64, then send to the vision model.**

### 3. TTS audio shows up as a file instead of a voice bubble on Telegram

You sent an `.mp3` file. Telegram voice bubbles only recognize Opus-encoded `.ogg`.

**Fix: Detect the platform; convert to Opus for Telegram.**

### 4. Doing STT in the core loop instead of the adapter

If STT were a tool, the agent would first need to "know" it received a voice message, then decide to call the STT tool. But voice message formats differ across every platform -- that's exactly what adapters are for.

**Fix: STT is done in the adapter. MessageEvent contains only text; the agent doesn't need to know the original message was voice.**

## Scope of this chapter

This chapter covers the architecture of three multimedia capabilities, not the API details of individual providers.

It covers three things:

1. **The auxiliary model design** -- why vision and the main conversation use different models
2. **Data flow for the three capabilities** -- vision (image -> text), STT (audio -> text), TTS (text -> audio)
3. **Where they sit in the architecture** -- STT at the adapter layer, vision at the tool layer, TTS at the tool layer + Gateway layer

Not covered:

- API calling details for each TTS/STT provider -> see each provider's documentation
- Audio encoding technical details (Opus, MP3, WAV) -> audio encoding knowledge
- Vision model selection and tuning -> model benchmarking topic
- CLI voice mode (push-to-talk) -> a terminal interaction enhancement

## How this chapter relates to others

- **s13**'s adapters handle STT and media downloads -> this chapter defines the STT providers and flow
- **s17**'s `browser_vision` uses the auxiliary vision model defined in this chapter
- **s12**'s Gateway handles MEDIA tags -> this chapter defines what MEDIA tags mean

## After finishing this chapter, you should be able to answer

- Why does vision analysis use an auxiliary model instead of the primary model?
- When a user sends a voice message on Telegram, what does the agent receive? An audio file or text?
- How does the `MEDIA:/path/to/audio.ogg` returned by the TTS tool become a Telegram voice message?
- Why does Telegram require Opus format? What happens if you send MP3?
- Why does the vision tool download images and convert to base64 instead of passing the URL directly to the model?

---

**One sentence to remember: The primary model only handles text. Seeing images uses the auxiliary vision model, hearing voice is transcribed to text in the adapter, and speaking uses TTS tools to generate audio.**
