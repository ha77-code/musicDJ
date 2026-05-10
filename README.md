# Music DJ — clauseekio

一个懂你口味的 AI 电台 DJ，名字叫 **clauseekio**。打开就能自动推歌聊天，实时策展，不是预制菜。

## 安装

### 环境要求

- **Python 3.10+**（推荐 Anaconda）
- **Node.js**（用于网易云 API 服务）

### 安装步骤

```bash
# 1. 安装 Python 依赖
pip install flask requests mutagen pycryptodome websocket-client

# 2. 安装网易云 API 依赖
cd NeteaseCloudMusicApi/api-enhanced-main
npm install
cd ../..

# 3. 配置 API 密钥（编辑 config.json）
#   - agent.llm.api_key: DeepSeek API Key (platform.deepseek.com)
#   - tts.app_id + tts.token: 火山引擎 TTS (console.volcengine.com)
#   - netease.cookie + netease.uid: 网易云音乐 (浏览器 F12 获取)
#   - weather.api_key: OpenWeatherMap (可选，不填也能用)
```

### 启动

```bash
# 方式 1: 一键启动（推荐）
双击 start_dj.bat

# 方式 2: 手动启动
cd NeteaseCloudMusicApi/api-enhanced-main && node app.js &   # 端口 3000
cd backend && python dj_server.py                             # 端口 8765
```

浏览器打开 `http://localhost:8765`。DJ 会自动打招呼并开始放歌。

## 使用说明

### 听歌

打开页面后 DJ 自动开始。当前播放的歌曲信息显示在中央面板。

| 操作 | 方式 |
|------|------|
| 播放/暂停 | 点击 ▶ 按钮或按空格 |
| 下一首 | 点击 ⏭ 或按 → |
| 上一首 | 点击 ⏮ 或按 ← |
| 导入歌曲 | 点击 📁 按钮，输入文件夹路径 |
| 调节音量 | 拖动底部滑块 |

DJ 模式下每首歌之间 DJ 会说一段串词，然后自动选出下一首歌。

### 和 DJ 聊天

右侧聊天面板直接打字。DJ 可以：

- **闲聊**: "今天心情不错"
- **搜歌**: "搜一下周杰伦的晴天"
- **放歌**: "放RADWIMPS的前前前世"（自动从网易云搜索播放，不限于歌单）
- **切歌**: "切歌"或"换一首"
- **推荐**: "推荐一首适合现在听的"
- **调音量**: "音量调到50"

DJ 会用语音回复。如果不想听语音，关掉页面音量即可，文字仍然显示。

### 调整口味

点击活动标签告诉 DJ 你在做什么：

| 标签 | 效果 |
|------|------|
| 随便听听 | 按品味自然推荐 |
| 📚 学习 | 安静背景音乐，不吵 |
| 💼 工作 | 专注向，轻音乐/后摇 |
| 🛋️ 放松 | 氛围感，沉浸式 |
| 🏃 运动 | 有节奏有能量 |
| 🌙 睡前 | 安静助眠，钢琴/氛围 |

### 双模式

- **DJ 模式**: AI 策展 + 串词 + 主动插话（默认）
- **Normal 模式**: 顺序播放歌单，无 AI

点击顶部 ON AIR 旁边的按钮切换。

## 配置

### config.json 说明

```json
{
  "app": { "port": 8765 },
  "dj": {
    "name": "clauseekio",
    "style": "嘴碎但走心的深夜DJ，像跟老朋友连麦",
    "voice": "zh-CN"
  },
  "agent": {
    "pool_size": 15,
    "discovery_ratio": 0.85,
    "llm": {
      "api_key": "你的DeepSeek Key",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-chat",
      "temperature": 1.05,
      "max_tokens": 500
    }
  },
  "tts": {
    "provider": "volcano",
    "app_id": "火山引擎AppID",
    "token": "火山引擎Token",
    "voice_type": "BV700_V2_streaming",
    "ssml_enabled": true,
    "streaming_enabled": true,
    "realtime_voice": { "enabled": true, "model": "O2.0" }
  },
  "netease": {
    "enabled": true,
    "api_host": "http://localhost:3000",
    "cookie": "你的网易云Cookie",
    "uid": "你的网易云UID"
  },
  "weather": {
    "api_key": "OpenWeatherMap Key（可选）",
    "city": "Chengdu,CN"
  },
  "scheduler": {
    "enabled": true,
    "check_interval_seconds": 30,
    "global_cooldown_minutes": 2
  }
}
```

### 功能开关

所有开关都在 config.json 中，设为 false 即可回退：

| 开关 | 位置 | 作用 |
|------|------|------|
| `ssml_enabled` | tts | 关掉则回到纯文本 TTS |
| `streaming_enabled` | tts | 关掉则回到一次性 HTTP TTS |
| `realtime_voice.enabled` | tts | 关掉则 Chat 走 SSML TTS |
| `scheduler.enabled` | scheduler | 关掉则停止主动插话 |
| `discovery_ratio` | agent | 0=纯歌单，1=纯网易云发现 |

## 文件结构

```
musicDJ/
├── backend/
│   ├── dj_server.py            # Flask 后端，所有 API 路由
│   ├── collect_listening_data.py
│   └── agent/
│       ├── dj_brain.py         # 大脑：选歌+串词+编排
│       ├── llm_provider.py     # DeepSeek API
│       ├── prompts.py          # 提示词模板
│       ├── actions.py          # DJ 动作解析
│       ├── context.py          # 上下文组装
│       ├── memory.py           # SQLite 记忆
│       ├── scheduler.py        # 主动插话调度
│       ├── rules.py            # 插话触发规则
│       ├── song_picker.py      # 候选歌池构建
│       ├── taste_profile.py    # 品味画像
│       ├── music_discovery.py  # 网易云搜索发现
│       ├── tts_provider.py     # 火山 TTS (SSML+流式)
│       ├── realtime_voice.py   # 实时语音 WebSocket
│       └── session.py          # 会话管理
├── frontend/
│   └── index.html              # 单文件 SPA
├── user_profile/
│   ├── taste.md                # 音乐口味画像
│   ├── routines.md             # 作息场景
│   └── mood-rules.md           # 情绪场景规则
├── data/
│   ├── playlist.json           # 播放列表
│   ├── state.db                # SQLite 记忆库
│   ├── personality.json        # fallback 串词库
│   └── listening_history/      # 网易云监听数据
├── NeteaseCloudMusicApi/       # 网易云 API (Node.js)
├── config.json                 # 全局配置
└── start_dj.bat               # 一键启动
```

## DJ 工作原理

### 选歌

1. 根据品味画像（top 艺人、偏好流派）生成搜索词
2. 结合当前时段、天气、活动
3. 从网易云曲库搜索候选歌曲
4. 候选池 85% 新歌 + 15% 歌单混合
5. LLM 选出最适合此刻的一首

### 串词

每句串词实时生成：
- 提到具体歌名和歌手
- 根据时段/天气/聊天内容调整语气
- SSML 控制语速、语调、停顿、重音
- 不报播放次数

### 记忆

DJ 会记住：
- 你跳过了哪些歌（避免再选）
- 你喜欢哪些歌
- 刚才聊天说了什么（影响下一首选歌）

## 常见问题

**Q: DJ 只放歌单的歌？**
A: 确认网易云 API 在运行（页面顶部显示 Netease: Connected）。用 `start_dj.bat` 启动会自动拉起。

**Q: 语音有叠音？**
A: 已修复，新语音播放前自动停止旧语音。

**Q: 怎么让 DJ 放歌单里没有的歌？**
A: 直接跟 DJ 说"放XXX"，DJ 会自动搜网易云播放。

**Q: 没配置 API 密钥能用吗？**
A: 能启动，但只能用 fallback 模式（简单串词模板，无 AI）。

**Q: 支持什么音频格式？**
A: MP3 / FLAC / WAV / M4A / OGG / AAC / WMA / Opus / NCM。

## 鸣谢

- 网易云音乐 API 基于 [NeteaseCloudMusicApiEnhanced/api-enhanced](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced)（MIT 协议）

## License

MIT
