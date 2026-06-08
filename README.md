# Music DJ

MusicDJ 是一个自用 AI 电台 DJ agent。它不是普通播放器：打开页面后，DJ 会尝试主动开台、聊天、推歌、说自然串词，并根据你的历史口味和当前状态做电台式随机选歌。

当前版本重点：
- 上半区是黑白绿 broadcast 音乐舞台，负责歌曲信息、频谱、播放控制、进度和音量。
- 下半区是 DJ 稿纸区，优先显示 DJ 正在说的话、串词、推荐理由和聊天内容。
- 选歌结合离线口味画像、运行时播放统计、跳过记录、新鲜度和网易云发现。
- 普通闲聊不会自动变成推歌；只有明确说放歌、搜歌、推荐、切歌、暂停、继续或调音量时才触发音乐动作。
- DJ 说到的下一首歌应和实际播放的 `pendingSong` 保持一致。

## What It Is

MusicDJ 由 Flask 后端和单文件 React/Babel 前端组成：
- 本地播放和网易云搜索/播放并存。
- LLM 负责聊天、选歌理由和串词。
- TTS/实时语音负责 DJ 播报。
- SQLite 和 JSON 文件记录听歌记忆、跳过、喜欢、播放次数和口味画像。
- 前端使用 Web Audio 做频谱和波形律动。

网易云音乐接口使用的是 [NeteaseCloudMusicApiBackup](https://github.com/nooblong/NeteaseCloudMusicApiBackup) 项目，本仓库的 `NeteaseCloudMusicApi/` 目录基于该 API 服务用于本地搜索、歌单、喜欢列表和听歌记录导入。

这个项目主要面向个人使用，不追求公共产品式完整包装。

## Quick Start

环境要求：
- Python 3.10+
- Node.js，用于运行 [NeteaseCloudMusicApiBackup](https://github.com/nooblong/NeteaseCloudMusicApiBackup) 网易云 API 服务
- 可选：DeepSeek API、火山引擎 TTS、OpenWeatherMap、网易云 Cookie

安装 Python 依赖：

```bash
pip install flask requests mutagen pycryptodome websocket-client
```

安装网易云 API 依赖：

```bash
cd NeteaseCloudMusicApi/api-enhanced-main
npm install
cd ../..
```

复制或参考 `config_example.json` 配置 `config.json`。常用字段：
- `agent.llm.api_key`: DeepSeek API Key
- `tts.app_id` 和 `tts.token`: 火山引擎 TTS
- `netease.cookie` 和 `netease.uid`: 网易云音乐登录信息
- `weather.api_key`: OpenWeatherMap，可选

启动方式：

```text
start_dj.bat
```

也可以手动启动：

```bash
cd NeteaseCloudMusicApi/api-enhanced-main
node app.js
```

```bash
cd backend
python dj_server.py
```

浏览器打开：

```text
http://127.0.0.1:8765/
```

## How To Use

听歌：
- 页面打开后默认进入 DJ 模式。
- 顶部音乐舞台显示当前歌曲、歌手、播放状态、频谱、进度和控制按钮。
- 播放/暂停：点击播放按钮或按空格。
- 上一首/下一首：点击按钮或按左右方向键。
- 进度和音量：使用舞台控件，也可以聊天说“音量调到 50”。
- 歌单、搜索、导入：使用顶部工具按钮或歌单抽屉。
- 如果浏览器阻止自动播放，DJ 文案会先显示，点击播放或开台提示后继续播放待播歌曲。

和 DJ 聊天：
- 底部 DJ 稿纸区有小输入条。
- 闲聊示例：`今天有点累`、`陪我聊会儿`、`你觉得我该怎么办`。
- 音乐指令示例：`放 RADWIMPS 的 前前前世`、`搜一下周杰伦 晴天`、`推荐一首适合现在听的`、`听点日语的`、`切歌`、`暂停一下`、`声音小点`。
- 前后端都有 music-intent guard。没有明确音乐意图时，即使模型误生成 `[[play]]` 或 `[[recommend]]`，也应该只显示聊天文本，不执行隐藏播放动作。

场景和模式：
- 随便听听：按当前口味自然推荐。
- 学习/工作：安静、专注、低干扰。
- 放松：氛围感、沉浸式。
- 运动：节奏和能量。
- 睡前：安静、助眠、钢琴或氛围。
- DJ 模式是默认模式，会主动开台、说串词、智能选歌。
- 普通听歌模式只顺序播放歌单，不做 AI 编排。

## Configuration

配置以 `config_example.json` 为准，README 只列核心含义：

```json
{
  "app": { "port": 8765 },
  "dj": {
    "name": "MusicDJ",
    "style": "嘴碎但走心的深夜DJ"
  },
  "agent": {
    "pool_size": 15,
    "discovery_ratio": 0.85,
    "llm": {
      "api_key": "your-deepseek-key",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-chat"
    }
  },
  "tts": {
    "provider": "volcano",
    "app_id": "your-volcano-app-id",
    "token": "your-volcano-token",
    "streaming_enabled": true,
    "realtime_voice": { "enabled": true }
  },
  "netease": {
    "enabled": true,
    "api_host": "http://localhost:3000",
    "cookie": "your-netease-cookie",
    "uid": "your-netease-uid"
  }
}
```

常用开关：
- `tts.streaming_enabled`: 控制是否使用流式 TTS。
- `tts.realtime_voice.enabled`: 控制聊天语音是否使用实时语音。
- `scheduler.enabled`: 控制主动插话调度。
- `agent.discovery_ratio`: 控制网易云发现和本地歌单的混合倾向。

## Project Structure

```text
musicDJ/
├── backend/
│   ├── dj_server.py             # Flask 后端入口和 API 路由
│   ├── collect_listening_data.py # 网易云听歌数据采集
│   └── agent/
│       ├── dj_brain.py          # DJ 决策核心：开台、选歌、串词、记忆
│       ├── song_picker.py       # 分桶随机候选池
│       ├── runtime_taste.py     # 运行时口味评分和歌曲标签
│       ├── music_discovery.py   # 网易云发现搜索
│       ├── taste_profile.py     # 离线口味画像读取和搜索画像
│       ├── memory.py            # SQLite 长期记忆
│       ├── prompts.py           # DJ prompt 模板
│       ├── tts_provider.py      # 火山 TTS
│       └── realtime_voice.py    # 实时语音 WebSocket
├── frontend/
│   └── index.html               # React/Babel 单文件前端
├── user_profile/
│   └── taste.md                 # 人工口味偏好
├── data/
│   ├── playlist.json            # 当前歌单
│   ├── listening_stats.json     # 运行时播放统计
│   ├── state.db                 # SQLite DJ 记忆
│   └── listening_history/       # 网易云听歌历史和处理后的口味画像
├── NeteaseCloudMusicApi/        # 基于 NeteaseCloudMusicApiBackup 的网易云 API 服务
├── config_example.json          # 配置模板
├── config.json                  # 本地配置，含私密信息
└── start_dj.bat                 # 一键启动
```

## How The DJ Works

开台：
- 前端的 `runOpeningShow` 会在 DJ 模式下尝试主动开台。
- 后端 transition 返回 `selected_song` 后，前端写入 `pendingSong`。
- DJ 先显示/播报串词，再播放这首待播歌曲。

选歌：
- 离线口味画像来自 `training_songs_top300.json`、歌手统计和 `user_profile/taste.md`。
- 运行时统计来自 `listening_stats.json` 的播放次数和最近播放时间。
- 长期记忆来自 `state.db` 中的 skip、like、transition 和 song interaction。
- 网易云发现会按语种、风格、时间、天气和活动场景搜索。
- `song_picker.py` 用熟悉锚点、少听本地歌、fresh discovery 分桶抽样。
- LLM 最后从候选池里选择适合当前氛围的一首，并生成理由和串词。

串词：
- 串词实时生成，应该自然、短而有画面感。
- 核心约束是 DJ 说到的下一首歌必须和实际播放的 `pendingSong` 一致。

聊天：
- 聊天接口会流式返回文本和语音。
- 前端有顺序播放队列，保证聊天语音播完后才执行可能产生第二句语音的动作。
- 无音乐意图时，后端会清理动作标记，前端也会阻止动作执行。

记忆：
- 最近播过的歌会降权或避开。
- 跳过的歌和歌手会被记录。
- 喜欢、完整听完、重复播放会影响倾向。
- 当前聊天上下文会影响下一首歌的氛围。

## Data And Privacy

- `config.json` 可能包含 API Key、网易云 Cookie 和 UID，不要公开。
- `data/playlist.json`、`data/state.db`、`data/listening_stats.json` 是个人数据，不要随意删除。
- `.gitignore` 已覆盖部分运行时文件，但已经被 Git 跟踪过的文件仍可能出现在 `git status`。
- 网易云发现依赖本地 `NeteaseCloudMusicApi` 服务和可用 Cookie。

## Public Release Safety

- Public builds must not include your personal `config.json`.
- The packaged app only ships `config_example.json`; each user should open the top `账号` button and save their own NetEase Cloud Music Cookie/UID, model key, and voice settings locally.
- `config_example.json` keeps `netease.enabled` as `false` by default, with empty `cookie`, `uid`, LLM key, and Volcano token.
- Runtime data is isolated by NetEase UID under `data/users/<uid>/`; switching accounts does not reuse the previous user's playlist, memory, listening stats, or training profile.
- The account settings UI lets users clear old local account data explicitly. Old account data is not deleted automatically.
- `/api/config` returns only a redacted configuration summary in normal runs. Full config writes are available only when `MUSICDJ_DEBUG` is set.
- Account-backed NetEase routes now reject requests until the local user enables NetEase and provides a real `MUSIC_U` cookie.

## Troubleshooting

**Q: 网易云搜索或播放失败？**
A: 确认 `NeteaseCloudMusicApi` 在 `http://localhost:3000` 运行，并检查 `config.json` 里的 Cookie 和 UID。

**Q: DJ 不主动开台？**
A: 确认后端运行正常，页面在 DJ 模式。浏览器可能阻止自动播放，点击播放按钮或开台提示继续。

**Q: TTS 没声音？**
A: 检查火山 TTS 配置。如果 realtime voice 不可用，可以在配置里关闭实时语音或切到普通 TTS。

**Q: 闲聊时 DJ 仍然推歌？**
A: 需要继续收紧 music-intent guard。当前设计目标是普通聊天不执行 `[[play]]` 或 `[[recommend]]`。

**Q: 为什么推荐还是有点重复？**
A: 检查 `listening_stats.json`、`state.db` 和 runtime taste key 是否能正确匹配歌曲，尤其是本地文件歌。

## License

Personal/local project. Use and modify for your own setup.
