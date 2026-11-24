# 燧镜模组接口规范（apiVersion 1）

本文件是**给写模组的人（或 AI 助手）看的规格书**。照着做，产出的 `.sjmod` 就能被燧镜装上、启停、卸载。

一句话概括：`.sjmod` 是个 zip，里面一个 `manifest.json` 说清"我是谁、我要什么权限"，一个 `main.py` 实现四个钩子，能力全部通过宿主传进来的 `host` 对象申请。

---

## 1. 包结构

```
我的模组.sjmod          （其实就是一个 zip，改名而来）
├── manifest.json       （必须，放最外层）
├── main.py             （必须，kind=package 时的入口）
└── assets\             （可选，图标、图片、数据文件）
    └── lib\            （可选，纯 Python 依赖，加载时自动进 sys.path）
```

三条硬规则：

1. **包里不要放 exe**（`kind=package` 时）。放 exe 的只有 `kind=external`，那是包装现成程序用的。
2. **manifest 必须在包的最外层**。如果压成了 `我的模组/manifest.json`，安装器会自动往下找一层，但别依赖这个。
3. **文件编码统一 UTF-8**（manifest 允许带 BOM）。

**依赖自己带**：模组要用第三方纯 Python 库，就把整份塞进 `assets\lib\`（比如 `assets\lib\yt_dlp\`），宿主加载这个模组时会自动把 `assets\lib` 加进 `sys.path`，`main.py` 里直接 `import yt_dlp` 就行——不用自己改 `sys.path`，也不占安装包体积。卸载/退出时宿主自动摘掉，不会串到别的模组。

要 exe 的依赖（ffmpeg、ffprobe 这类）不能进包：要么让它躺在宿主 `bundled\` 里由你指路径，要么首次使用时提示用户放到自己的 `host.paths.data_dir` 下，并在文档里写清放哪儿。

---

## 2. manifest.json 字段

### 必填

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 唯一标识，小写字母/数字/下划线/点/横线，2–40 位。**装的时候靠它防重复**，定了就别改 |
| `name` | string | 显示名，中文可以 |
| `version` | string | 自己定，建议 `1.0.0` |
| `apiVersion` | string | **必须写 `"1"`**。写别的宿主直接拒绝 |
| `author` | string | 作者 |
| `description` | string | 一句话说明，会显示在模组详情里 |
| `kind` | string | `package`（纯 Python）或 `external`（包装现成程序） |
| `permissions` | array | 申请的权限，见第 4 节。**没申请的调不了** |

### 可选

| 字段 | 类型 | 说明 |
|---|---|---|
| `entry` | string | 入口文件，默认 `main.py`；`kind=external` 时留空 |
| `builtin` | bool | 内置模组用，用户装的包不要写 |
| `minAppVersion` | string | 要求的最低燧镜版本，如 `"1.10.0"` |
| `external` | object | `kind=external` 必填，见下 |

`external` 对象：

```json
"external": {
  "path": "bin\\口琴可视化曲谱.exe",
  "args": ["--profile=profile"]
}
```

`path` 相对包目录（也可以写绝对路径），宿主启动时把工作目录设成 exe 所在目录。

### 两个完整例子

**纯 Python 模组**

```json
{
  "id": "com.you.hello",
  "name": "你好模组",
  "version": "1.0.0",
  "apiVersion": "1",
  "author": "你的名字",
  "description": "点一下弹条通知，演示最小可用模组",
  "kind": "package",
  "entry": "main.py",
  "permissions": ["notify", "events"]
}
```

**包装现成程序（口琴就是这么搬过来的）**

```json
{
  "id": "com.flint.harmonica",
  "name": "口琴可视化曲谱",
  "version": "1.0.0",
  "apiVersion": "1",
  "author": "燧镜",
  "description": "跟着曲谱吹口琴，实时可视化",
  "kind": "external",
  "permissions": [],
  "external": { "path": "bin\\口琴可视化曲谱.exe", "args": [] }
}
```

---

## 3. main.py 的四个钩子

```python
def on_load(host):
    """加载时调一次。只做注册：注册页面、注册热键、订阅事件，别在这里启业务。"""

def on_enable():
    """用户点「启用」时调。真正的业务启动放这里。"""

def on_disable():
    """用户点「停用」时调。必须把东西彻底收干净：停音频、关窗、停线程、
    取消定时器。宿主会兜底停掉 host.schedule 里的定时器，但你自己起的线程要自己收。"""

def on_unload():
    """卸载或退出程序时调。清掉自己写的临时文件、保存配置。"""
```

四个钩子**都可以不写**，但 `on_load` 是唯一必须有的（不然拿不到 host）。钩子抛异常会被宿主捕获写进 `logs\mods.log`，不会把燧镜带崩。

**为什么要分开 load 和 enable**：加载（读包、执行 import）是轻的，启用（起业务）是重的。这样用户在模组页里能立刻看到列表，但只有他点开才占资源。

---

## 4. host 能给你的东西

`on_load(host)` 拿到的 `host` 就这些。括号里是需要的权限，没申请会抛 `_PermDenied`。

### 基础（不需要权限）

```python
host.spec.id / .name / .version / .root     # 自己的元信息、包目录
host.app_version                            # 宿主版本，如 "1.10.0"
host.api_version                            # "1"
```

### 日志

```python
host.log.info("xxx")     # 写进 logs\mods.log，前缀自动带模组 id
host.log.warn("xxx")
host.log.error("xxx")
host.log.error("xxx", exc=True)   # 第三个参数 True 会连堆栈一起记
```

### 配置（每个模组独立一份，存 mods_data\<id>\config.json）

```python
host.cfg.get("voice", 80)
host.cfg.set("voice", 90)
```

### 路径

```python
host.paths.data_dir    # 自己的可写目录（Path），放用户数据
host.paths.resource    # 包目录（Path），只读
host.paths.assets      # 包里的 assets 目录（Path）
```

### 通知（权限 `notify`）

```python
host.notify("标题", "正文", "info")     # level: info / warn / error
```

### 界面页（权限 `ui.page`）

```python
host.ui.register_page("my_page", builder)     # 注册一个界面页
host.ui.unregister_page("my_page")            # 撤回它，卡片菜单里那一项跟着消失
```

`builder` 是个无参函数，返回一个 Qt 控件（`QWidget`）。**不要自己造 QMainWindow**。

点开的位置：模组卡片/磁贴的「⋯」菜单里会多一项「打开界面：my_page」，点了就在一个 560×420 的对话框里显示 `builder()` 返回的控件。

几条实话：

- 每个 `key` 只显示成菜单里一项，**不会变成模组页上的一个标签页**
- `builder()` 在点击时才调用，可以每次返回新控件；控件销毁交给 Qt
- 同一个 `key` 重复注册会覆盖前一个 builder
- `unregister_page(key)` 撤回一个入口。模组停用后卡片菜单里就不列这些项了（注册还留着，重新启用又出现），卸载时连注册一起清
- 界面里要刷新自己，用 `QTimer` 或 `host.schedule.every()`，别在 `builder` 里起长循环

**要盖在游戏上的浮窗**：模组可以自己 `new` 一个顶层 `QWidget`（无边框 + 置顶），但两条底线——**不要造 `QMainWindow`**（那是宿主的主窗口，模组别去接管生命周期），**这个窗口必须在 `on_disable` 里隐藏并销毁**（连播放器、线程一起收）。停用之后还挂着一个透明窗口，用户只能去任务管理器解决。

### 热键（权限 `hotkey`）

```python
host.hotkey.register("Ctrl+Alt+K", my_fn)
host.hotkey.unregister("Ctrl+Alt+K")
```

写法同燧镜自己的热键：`Ctrl` / `Alt` / `Shift` / `Win` 组合 `+` 一个键名（A–Z、0–9、F1–F12、空格等）。

- 冲突检测由宿主做：被别的程序占了就注册失败（会弹提示），**注意检查 host 端不会抛异常，只是没生效**
- 热键管理器不支持单独注销，`unregister` 之后键位仍被本进程占着，只是模组停用后按了不触发
- 回调在宿主主线程执行，别在里面干重活

### 事件（权限 `events`）

```python
host.events.on("game.started", lambda **kw: ...)
host.events.emit("my.thing", value=1)
```

宿主会发的事件（apiVersion 1 已实现）：

| 事件名 | 时机 | 参数 |
|---|---|---|
| `app.started` | 界面起来后约 1.5 秒，所有模组 load 完之后广播一次 | 无 |
| `game.started` | 「自动化」里配了进程的规则，那个进程启动时 | `process`（规则里写的进程名） |
| `game.stopped` | 同上，那个进程退出时 | `process` |
| `mod.enabled` | 某个模组被启用 | `id` |
| `mod.disabled` | 某个模组被停用 | `id` |

**game.\* 的前提**：模组自己看不到"所有游戏的启动"，宿主只在「自动化」里有进程规则的条件下监视进程（每 2 秒一次）。所以想要 `game.started`，用户得先在自动化里配一条以那个进程为触发条件的规则。没配就永远收不到——**别把核心功能挂在这个事件上**，用 `host.schedule.every()` 自己轮询更稳。

模组之间也能用同一套事件互相通知，名字自己起（如 `my.thing`），互不干扰。

### 定时器（权限 `schedule`）

```python
host.schedule.every(30, my_fn)     # 每 30 秒跑一次，首次也要等 30 秒
```

停用/卸载时宿主自动全部掐掉，不用自己管。

### 启动外部程序（权限 `shell`）

```python
host.shell.launch(r"C:\xxx\tool.exe", ["--arg"])          # 发射后不管，返回有没有起来
code, out, err = host.shell.capture([r"C:\xxx\ffmpeg.exe", "-version"], 10)
```

- `launch` 只管起来，拿不到输出，也不知道后来是不是崩了。
- `capture(args, timeout=30)` 会等程序跑完，返回 `(返回码, 标准输出, 标准错误)`。返回码 `>= 0` 是程序自己的；`-1` 是超时被掐；`-2` 是根本没起来。适合探测类、跑一次就要知道结果的活。
- `capture` 是**同步**的，会占住调用线程。几十秒以上的长任务别用它——那种要能随时中止，模组自己管进程更合适（权限照样申请 `shell`，用户装之前看得见）。

---

## 5. 权限清单

| 权限 | 用途 | 不给会怎样 |
|---|---|---|
| `notify` | 弹通知 | `host.notify()` 抛错 |
| `ui.page` | 在模组页加一个自己的界面 | `register_page` 抛错 |
| `hotkey` | 注册全局热键 | `register` 抛错 |
| `shell` | 启动外部程序（`launch` / `capture`） | 两个都抛错 |
| `events` | 收发事件 | `on/emit` 抛错 |
| `schedule` | 定时任务 | `every` 抛错 |
| `fs.data` | 声明"我要往 data_dir 写文件"。**没有对应的 host API**，拿到 `host.paths.data_dir` 后用普通 `open()` 写 | 不申请也能写，但审核时看不到你在用 |

**原则：只申请你真用到的。** 安装时会把权限列在模组卡片上，用户看得见。

---

## 6. 自带依赖与第三方程序

模组是「谁需要谁自己带」：宿主不给你装 yt-dlp，也不保证 PATH 里有 ffmpeg。你要用，就放进包里。

### 三种放法

| 东西 | 放哪 | 怎么用 |
|---|---|---|
| 纯 Python 包（yt-dlp、requests…） | `assets/lib/<包名>/` | 宿主在 `on_load` 之前就把 `assets/lib` 挂进 `sys.path`，直接 `import` 即可。目录名写 `pylibs` 也认（早先的模组都这么放的） |
| 独立命令行程序（ffmpeg.exe、yt-dlp.exe…） | `assets/bin/` 或运行时下到 `host.paths.data_dir / "bin"` | `host.shell.capture([exe, "-version"], 15)` 取返回码和输出；长时间任务自己 `subprocess.Popen` 并留好 terminate 口 |
| 图标、模板等静态文件 | `assets/` 直接放 | `host.paths.assets` 就是它 |

`host.paths.assets` 指向 `<模组目录>\assets`（只读，别往里写东西）；要缓存就往 `host.paths.data_dir` 写。

### 三条硬规矩

1. **包内的 .exe / .dll / .bat 只能放在 `assets/` 下**，塞在包根会跟入口文件混在一起，也不允许。
2. **带了可执行程序就必须申请 `shell` 权限**。没申请，`host.shell` 调不动；而且用户装之前看不到"这包会跑外部程序"这句提醒。
3. 安装前宿主会把包里的可执行文件逐个列给用户看。单个程序超过 60 MB 会提示包变大，能裁就裁（ffmpeg 的 essentials 版就比 full 版小得多）。

### 打包时要知道的

- `tool/mod_test.py` 会检查上面两条（位置 + 权限），不合规直接判不合格。
- `.sjmod` 是 zip，纯 Python 包别带 `__pycache__`、`.pyc`，体积能小一半。
- 依赖只在**用到时**才 import（放函数里），别写顶层 —— 顶层 import 失败会让整个模组加载不起来，宿主只能看到一句 `ImportError`。

---

## 7. 打包

用项目里的脚本，不用手搓 zip（手搓容易多套一层目录、漏改编码）：

```powershell
cd C:\Users\1\Desktop\游戏助手
.\.venv313\Scripts\python.exe tool\make_sjmod.py 我的模组文件夹
```

产出 `我的模组文件夹.sjmod`，落在同目录。脚本会做四件事：校验 manifest、检查入口文件、按 UTF-8 打包、打印体积。

想看包里的东西对不对：

```powershell
.\.venv313\Scripts\python.exe tool\mod_test.py 我的模组.sjmod
```

它会只读地校验 manifest、检查文件齐不齐、模拟一次 `parse_manifest`，**不会真的装进去**。

---

## 8. 装上之后的行为

1. 把 `.sjmod` 拖进模组页，或者点「安装模组文件」选文件
2. 解压到 `文档\燧镜\mods\<id>\`
3. 同 `id` 已存在 → 拒绝安装，提示先卸载
4. manifest 不合格 → 包复制到 `文档\燧镜\mods\_invalid\`，列表里显示红色错误项，鼠标悬停看原因
5. 装好的模组默认**不自动启用**，用户自己点

---

## 9. 调试常见错误

| 现象 | 原因 |
|---|---|
| 装了但列表没出现 | manifest 不在包最外层，或者 id 重复被拒 |
| 显示"manifest 不合格" | 缺必填字段、`apiVersion` 不是 `"1"`、id 带大写字母 |
| 加载失败、日志里有 ImportError | `main.py` 里 `import` 了没一起打包的兄弟文件 |
| 点了启用没反应 | `on_enable` 抛异常了，去 `logs\mods.log` 搜自己的 id |
| 停用之后后台还在跑 | `on_disable` 里没停自己起的线程/定时器/音频 |
| 页面打开是空白 | `builder` 返回了 None，或者返回的不是 QWidget |

---

## 10. 给 AI 助手写模组时的提示词模板

> 我在写燧镜（Flint Mirror）的模组，框架 apiVersion 1。请严格按 `docs\MOD_API.md` 的规范产出：
> 1. 先给 `manifest.json`（id 用 `com.<你的名字>.<功能>` 格式，permissions 只写真正用到的）
> 2. 再给 `main.py`，只实现需要的钩子，业务逻辑放 `on_enable`，清理放 `on_disable`
> 3. 只用 host 提供的能力，不要自己弹 QMainWindow、不要读写别的模组目录、不要 import 燧镜内部私有模块
> 4. 代码要能直接跑，不要留 `TODO`
>
> 我的模组要做的事：（在这里写需求）
