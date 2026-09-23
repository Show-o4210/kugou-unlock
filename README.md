# 酷狗音乐本地解密工具

纯 Python 的酷狗加密音频解密工具。核心解密离线运行、仅使用标准库；可选的
歌词/封面标签写入功能使用 mutagen。

更适合安卓端“酷狗音乐”或“酷狗音乐概念版”本地下载的歌曲。本工具仅用于处理
你本人合法持有的本地文件。

## 先看：安卓资源路径速查

需要的资源集中列在这里。正式版包名是 com.kugou.android，概念版包名是
com.kugou.android.lite。

| 资源 | 酷狗音乐 | 酷狗音乐概念版 | 说明 |
|---|---|---|---|
| 加密音频 | /storage/emulated/0/kgmusic/ | /storage/emulated/0/kgmusic/ | 通常可直接复制；实际下载目录可能由客户端设置改变 |
| KGG 密钥 | /data/user/0/com.kugou.android/files/mmkv/mggkey_multi_process | /data/user/0/com.kugou.android.lite/files/mmkv/mggkey_multi_process | 应用私有目录，需要 root、备份或其它获授权的导出方式 |
| KRC 歌词 | /sdcard/Android/data/com.kugou.android/files/kugou/lyrics/ | /sdcard/Android/data/com.kugou.android.lite/files/kugou/lyrics/ | 用于生成同名 LRC |
| 歌曲数据库 | /data/user/0/com.kugou.android/databases/kugou_music_phone_v7.db | /data/user/0/com.kugou.android.lite/databases/kugou_music_phone_v7.db | 用于匹配歌曲和封面；文件名可能随版本变化 |

部分 root 文件管理器会把应用私有目录显示为 /data/data/包名/；在常见 Android
系统中它与表内的 /data/user/0/包名/ 指向同一位置。

先关闭酷狗再导出数据库；若数据库旁存在同名 -wal 或 -shm，也应一起导出。工具不会
自动取得 root、连接 ADB 或修改手机端文件。完整导出命令见“歌词与封面”一节。

| 扩展名 | 说明 | 是否需要密钥库 |
|---|---|---|
| .kgg | 酷狗新加密 | 需要安卓端 mggkey |
| .kgm / .kgma | 酷狗旧加密 | 不需要 |
| .vpr | 酷狗 VPR | 不需要 |

## 建议流程

1. 在安卓端播放或下载目标歌曲，使 KGG 密钥写入 mggkey。
2. 手动导出 mggkey_multi_process 到 input/key_database/。
3. 把加密音频放入 input/music_files/。
4. 运行工具，在 output/ 取得标准音频。
5. 如需歌词与封面，再按下文手动导出 KRC 缓存和歌曲数据库。

KGM、KGMA、VPR 不依赖 mggkey。

## 目录结构

~~~text
kugou-unlock/
├── input/
│   ├── key_database/       # 手动导出的 mggkey
│   ├── music_files/        # 待处理音频
│   └── metadata/           # 可选：手动导出的歌曲数据库与 KRC
├── output/                 # 标准音频、同名 LRC 与封面
├── tools/
│   ├── kgg.key             # 运行后产生的密钥映射
│   └── cover_cache/        # 下载的封面缓存
├── kugou_unlock/
│   ├── audio.py            # 内容嗅探与复合后缀解析
│   ├── enrich.py           # KRC、封面与标签补全
│   ├── kgg.py / qmc2.py    # KGG / QMC2
│   ├── kgm.py              # KGM / KGMA / VPR
│   ├── mmkv.py             # MMKV / mggkey
│   └── cli.py              # 命令行
├── unlock_tool.py          # CLI 入口
├── unlock_gui.py           # PySide6 GUI 入口
├── enrich_from_android.py  # 补全功能的兼容入口
└── APK_DEVELOPMENT_GUIDE.md
~~~

## 快速使用

1. 加密音频放入 input/music_files/。
2. 如有 KGG，把 mggkey_multi_process 放入 input/key_database/。
3. 命令行运行 python unlock_tool.py，或安装依赖后运行 python unlock_gui.py。
4. 从 output/ 取得结果。

无参数自动模式会提取 KGG 密钥、并发解密所有支持的文件、记录断点进度，并按文件头
纠正真实的 FLAC、MP3、OGG、M4A 或 WAV 容器。

## 特殊后缀识别

识别采用“内容优先、文件名回退”：

- 文件头能明确判断明文、KGG mode 5、KGM version 3 时，以文件内容为准。
- 内容不足以判断时，在整个复合后缀链中从右向左寻找加密后缀。
- song.kgg.flac.download、song.kgm.custom 和没有已知后缀但文件头正确的文件均可识别。
- 文件名写着 KGG，但文件头实际为 KGM 或明文 FLAC 时，按真实内容处理。

解密指定 KGG：

~~~powershell
python unlock_tool.py -d "input/music_files/song.kgg.flac.download" -k tools/kgg.key
~~~

## 歌词与封面：Python 版推荐手动导出

Python 版不会自行取得 root、不会自动连接 ADB，也不会读取手机中其它应用的数据。
推荐先明确地把所需文件导出到电脑，再让工具处理本地副本。

以概念版 com.kugou.android.lite 为例：

~~~powershell
# 先关闭酷狗，避免数据库与 WAL 处于不一致状态
adb shell su -c "am force-stop com.kugou.android.lite"

# KRC 歌词缓存通常位于共享存储
adb pull "/sdcard/Android/data/com.kugou.android.lite/files/kugou/lyrics" "input/metadata/lyrics"

# root 设备：经 cmd 做二进制重定向，兼容 Windows PowerShell 5
cmd /c "adb exec-out su -c 'cat /data/user/0/com.kugou.android.lite/databases/kugou_music_phone_v7.db' > input\metadata\kugou_music_phone_v7.db"
~~~

若数据库旁存在同名 -wal 或 -shm 文件，也要在应用关闭后原样导出并放在数据库旁。
正式版酷狗请把包名替换为 com.kugou.android。数据库文件名、表结构和缓存路径可能
随客户端版本变化；应先在设备上确认实际路径，不要猜测或覆盖设备文件。

导出后运行：

~~~powershell
# 生成同名 LRC、封面，并嵌入标题、歌手、专辑、歌词和封面
python unlock_tool.py --enrich --metadata-db "input/metadata/kugou_music_phone_v7.db" --lyrics-dir "input/metadata/lyrics"

# 只生成播放器容易识别的同名外置文件，不改写音频
python unlock_tool.py --enrich --metadata-db "input/metadata/kugou_music_phone_v7.db" --lyrics-dir "input/metadata/lyrics" --external-only
~~~

处理规则：

- KRC 按歌曲 hash 匹配并转成 UTF-8 BOM 的同名 LRC，保留逐行时间轴。
- 从数据库读取准确封面 URL，输出同名 JPEG、PNG 或 WebP，并缓存到 tools/cover_cache/。
- 默认将纯文本歌词和封面嵌入 FLAC、Ogg Vorbis、MP3；写入使用临时副本和原子替换。
- PotPlayer 等播放器占用文件时，Windows 可能拒绝替换。关闭播放器后重试，或先用
  --external-only。
- 数据库可能含播放记录等个人信息，不要提交数据库、KRC、密钥或生成音频。

## 高级命令行

~~~powershell
python unlock_tool.py --help

# 从 mggkey 导出密钥表
python unlock_tool.py -i input/key_database/mggkey_multi_process -o tools/kgg.key -f kgg

# 以 JSON 查看 MMKV
python unlock_tool.py -i input/key_database/mggkey_multi_process -f json -t auto

# 仅清理临时文件
python unlock_tool.py --cleanup
~~~

## 运行环境与依赖

- Python 3.10+，推荐 3.11 至 3.14。
- 核心解密无 pip 依赖。
- GUI 使用 PySide6。
- 标签嵌入使用 mutagen；只生成外置文件时可用 --external-only 跳过。

执行 pip install -r requirements.txt 会安装 GUI 与标签写入依赖。

## 说明与限制

- KGM 族当前支持主流的 encryption version 3。
- KGG 必须在密钥库中找到对应 hash；EKey not found 表示需从播放过该曲的设备更新密钥。
- 解密结果必须通过音频文件头校验，不会把乱码冒充音频写出。
- 歌词/封面补全要求 KRC 和数据库来自同一客户端数据集；数据库结构不兼容会明确报错。
- 当前补全标签支持 FLAC、Ogg Vorbis、MP3。
- 仓库以 GNU GPL v3 发布，详见 LICENSE。

## 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| EKey not found | 密钥库没有该曲 hash | 从播放过该曲的安卓端重新导出 mggkey |
| 无输出 | input/music_files/ 为空 | 放入文件后重试 |
| unsupported encryption version | 非 KGM v3 变体 | 反馈文件头，不要公开完整歌曲 |
| 特殊后缀仍未识别 | 文件头不完整且无加密后缀标记 | 保留前 32 字节和文件名用于问题报告 |
| enrich 找不到歌曲 | 文件基名与数据库 musicname 不一致 | 保留歌手 - 歌名基名，检查额外质量后缀 |
| SQLite incomplete/unsupported | 复制时仍在写、遗漏 WAL 或结构变化 | 关闭应用后重导出，并带上 WAL/SHM |
| Permission denied | 播放器占用音频 | 关闭播放器后重试或使用 --external-only |

## 模块说明

| 模块 | 职责 |
|---|---|
| kugou_unlock/audio.py | 文件头嗅探、特殊后缀与明文透传 |
| kugou_unlock/tea.py | TEA CBC |
| kugou_unlock/qmc2.py | ekey、QMC2 Map/RC4 |
| kugou_unlock/kgg.py | KGG hash 与流式解密 |
| kugou_unlock/kgm.py | KGM、KGMA、VPR |
| kugou_unlock/mmkv.py | 解析 mggkey、导出 kgg.key |
| kugou_unlock/enrich.py | KRC 转 LRC、数据库匹配、封面下载与标签写入 |
| kugou_unlock/auto.py | 自动批处理 |
| kugou_unlock/cli.py | 命令行接口 |
