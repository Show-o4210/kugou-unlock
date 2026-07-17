# 酷狗音乐本地解密工具

纯 Python、离线、**无第三方依赖**的酷狗加密音频解密工具。

更适合在安卓端使用 **「酷狗音乐」** 或 **「酷狗音乐概念版」** 本地下载后的歌曲。

| 扩展名 | 说明 | 是否需要密钥库 |
|--------|------|----------------|
| `.kgg` | 酷狗新加密 | 需要安卓端 `mggkey` |
| `.kgm` / `.kgma` | 酷狗旧加密 | 不需要 |
| `.vpr` | 酷狗 VPR | 不需要 |

本工具仅面向**酷狗音乐**本地已下载文件的解密还原。

---

## 适用场景与客户端

| 客户端 | 安卓包名 | 密钥目录 |
|--------|----------|----------|
| 酷狗音乐 | `com.kugou.android` | `/data/data/com.kugou.android/files/mmkv/` |
| 酷狗音乐概念版 | `com.kugou.android.lite` | `/data/data/com.kugou.android.lite/files/mmkv/` |

密钥数据库常见文件名：

- `mggkey_multi_process`（必需，解密 `.kgg` 时）
- `mggkey_multi_process.crc`（可选，校验文件，可不拷贝）

> 上述 `/data/data/...` 路径位于应用私有目录，需要 **root**、系统备份或其它有权限的导出方式才能取出。  
> 取出后把 `mggkey_multi_process` 放到本工具的 `input/key_database/` 即可。

### 建议流程

1. 在手机上用酷狗 / 概念版**播放或下载**目标歌曲（`.kgg` 的密钥会在此时写入 mggkey）。
2. 导出 `mmkv` 目录中的 `mggkey_multi_process`。
3. 把加密音频（下载目录里的 `.kgg` / `.kgm` 等）和密钥文件放进本工具对应文件夹。
4. 运行本工具，在 `output/` 取得标准音频。

`.kgm` / `.kgma` / `.vpr` **不依赖** mggkey，只放音频文件即可。

---

## 目录结构

```
kugou-unlock/
├── input/
│   ├── key_database/     # 安卓导出的 mggkey_multi_process（仅 .kgg 需要）
│   └── music_files/      # 待解密 .kgg / .kgm / .kgma / .vpr
├── output/               # 解密后的标准音频
├── tools/
│   └── kgg.key           # 从 mggkey 自动生成的密钥映射（运行后产生，勿提交）
├── kugou_unlock/         # 核心代码包
│   ├── tea.py            # TEA（ekey）
│   ├── qmc2.py           # QMC2 / .kgg 密码
│   ├── kgm.py            # .kgm / .kgma / .vpr
│   ├── mmkv.py           # MMKV / mggkey 解析
│   ├── kgg.py            # .kgg 文件解密
│   ├── audio.py          # 音频容器嗅探
│   ├── keys.py           # kgg.key 读写
│   ├── report.py         # MMKV 查询输出格式
│   ├── auto.py           # 自动模式
│   └── cli.py            # 命令行
├── unlock_tool.py        # 入口（双击 / 命令行）
├── mggkey_to_kggkey.py   # 历史命令兼容入口
├── run.bat               # Windows 一键运行
├── LICENSE               # GPL-3.0
└── README.md
```

---

## 快速使用

1. **放入文件**
   - 加密音频 → `input/music_files/`
   - 若有 `.kgg`：将 `mggkey_multi_process` → `input/key_database/`
2. **运行**
   - Windows：双击 `run.bat`
   - 或：`python unlock_tool.py`
3. **取结果** → `output/`

---

## 自动模式逻辑

无命令行参数时：

1. 扫描 `input/key_database/`，若有 mggkey → 写出 `tools/kgg.key`
2. 用 `tools/kgg.key` 解密 `.kgg`
3. 纯算法解密 `.kgm` / `.kgma` / `.vpr`
4. 按文件头识别真实容器（FLAC / MP3 / M4A 等）并写入 `output/`

---

## 高级命令行

```powershell
python unlock_tool.py --help
```

```powershell
# 从 mggkey 导出密钥表
python unlock_tool.py -i input/key_database/mggkey_multi_process -o tools/kgg.key -f kgg

# 解密指定 .kgg
python unlock_tool.py -d "input/music_files/song.kgg" -k tools/kgg.key

# 以 JSON 查看 MMKV 内容
python unlock_tool.py -i input/key_database/mggkey_multi_process -f json -t auto
```

---

## 运行环境

- **Python 3.10+**（推荐 3.11～3.14）
- **无 pip 依赖**：仅标准库

## 许可证

本项目以 [GNU GPL v3](LICENSE) 发布。

---

## 说明与限制

- 仅处理你本人合法持有、已在本地下载的酷狗加密文件。
- KGM 族当前支持 **encryption version 3**（主流下载文件）。
- `.kgg` 必须在密钥库中匹配到对应 hash；提示 `EKey not found` 时，说明导出 mggkey 的设备上未播放/下载过该曲，需更新密钥库。
- 解密失败不会把乱码当成音频写出（会校验文件头）。
- **请勿把个人 `mggkey`、测试歌曲、`kgg.key`、解密成品提交到公开仓库。** 仓库已提供 `.gitignore` 忽略这些路径。

---

## 故障排查

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| `.kgg` 提示 EKey not found | 密钥库不含该曲 hash | 用播过该曲的安卓端重新导出 mggkey |
| 输出无法播放 | 旧版本误把 VPR 密钥套到 KGM | 使用当前版本重新解密 |
| 无任何输出 | `input/music_files/` 为空 | 放入加密文件后重试 |
| unsupported encryption version | 非 v3 的 KGM 变体 | 当前不支持，可反馈文件头 |
| 找不到 mggkey | 路径/包名不对 | 对照上文「酷狗 / 概念版」目录再导出 |

---

## 模块说明（维护用）

| 模块 | 职责 |
|------|------|
| `kugou_unlock/tea.py` | TEA CBC，供 ekey 使用 |
| `kugou_unlock/qmc2.py` | ekey 解密、QMC2 Map/RC4 |
| `kugou_unlock/kgg.py` | 读 hash、流式解密 `.kgg` |
| `kugou_unlock/kgm.py` | 解密 `.kgm` / `.kgma` / `.vpr` |
| `kugou_unlock/mmkv.py` | 解析 mggkey、导出 kgg.key |
| `kugou_unlock/auto.py` | 傻瓜自动批处理 |
| `kugou_unlock/cli.py` | argparse 高级接口 |
| `unlock_tool.py` | 薄入口，勿堆业务逻辑 |
