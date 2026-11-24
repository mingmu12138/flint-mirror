# 平台视频 · 燧镜模组

把 B 站 / YouTube 的攻略视频粘进悬浮窗，边玩边看——置顶、可半透明、鼠标能穿透（不挡操作），可拖动可缩放。适合跑图类、跟着攻略一步步走的游戏，也适合任何「想开着小窗看视频」的场景。

**下载**：见右侧 Releases 里的 `com.flint.platform_video.sjmod`（2.9 MB）。

## 这是什么

燧镜（Flint Mirror）的模组包（`.sjmod`），不是独立程序。装上之后在「模组」页出现「平台视频」卡片，启用即用。

## 运行环境

- 燧镜 v1.10.3 及以上（模组接口 apiVersion 1）
- Windows 10 / 11
- 一个 `ffmpeg.exe`（转码用，**包里不带**，见下方「关于依赖」）

## 安装

1. 把 `com.flint.platform_video.sjmod` 拖进燧镜「模组」页空白处，或点「安装模组文件」选中它
2. 弹权限卡时看一眼这六项，点「安装」：通知、界面页、全局热键、事件、模组数据目录、**启动外部程序**
3. 列表里点「平台视频」→ 启用
4. 按 `Ctrl+Alt+V` 开 / 关浮窗，或在卡片菜单里点「打开界面」

## 用法

1. 粘一个视频链接（B 站 `https://www.bilibili.com/video/BV...`、YouTube `https://www.youtube.com/watch?v=...`），点「下载并播放」
2. 模组调 yt-dlp 下视频流 + 音频流，再用 ffmpeg 转成 H.264 + AAC 的 MP4（保证 Windows 播放器能放），然后自动在浮窗里播
3. 浮窗操作：底部那条是拖动条；右下角可缩放；勾「鼠标穿透」后点击直接穿透到游戏里；音量、静音、关闭都在面板上

## 关于依赖（重要）

- **yt-dlp 已在包内**（`assets\pylibs\yt_dlp`，纯 Python），装完即用，不需要你装 Python 或 pip
- **ffmpeg 需要你自己准备**，查找顺序：模组数据目录 `bin\ffmpeg.exe` → 系统 PATH → 包内 `assets\bin\ffmpeg.exe`。都没有时界面会给三条指引。推荐从 <https://www.gyan.dev/ffmpeg/builds/> 或 <https://github.com/BtbN/FFmpeg-Builds/releases> 下 Windows 版，把 `bin\ffmpeg.exe` 拷进
  `%USERPROFILE%\Documents\燧镜\mods_data\com.flint.platform_video\bin\`
  放好后在模组页点「停用」再「启用」，让它重新探测。
- 包内**不含任何 exe**，安装包体积小就是为了这个：谁需要 ffmpeg 谁自己带，不替所有人多下 80 MB

## 常见问题

- 「缺少 yt-dlp」→ 说明包不完整，请重新下载完整的 `.sjmod`（正常应有 1073 个条目 / 2.9 MB）
- 「找不到可用的 ffmpeg」→ 按上面第二条放 `bin\ffmpeg.exe`，然后停用再启用
- 下载慢 / 失败 → 换网络环境，或先用 yt-dlp 在命令行下好；模组依赖平台当前接口，站点改版可能导致暂时失效
- 停用 / 卸载后：窗口销毁、下载线程结束、子进程终止、`temp` 清空；`bin` 与 `config.json` 会保留（配置不丢）。要彻底清干净就删 `mods_data\com.flint.platform_video` 整个目录

## 权限说明

| 权限 | 用途 |
| --- | --- |
| notify | 下载完成 / 失败的桌面通知 |
| ui.page | 注册面板与浮窗入口 |
| hotkey | `Ctrl+Alt+V` 开关浮窗 |
| events | 广播 `platform_video.state`，让自动化能跟着联动 |
| fs.data | 在模组数据目录写配置、临时视频 |
| shell | 调用 yt-dlp 与 ffmpeg 这两个外部程序 |

## 免责

仅供个人学习与看攻略使用。下载内容请遵守对应平台的用户协议与版权规定，不要二次分发。本模组与 B 站、YouTube、yt-dlp、FFmpeg 官方均无关联。
