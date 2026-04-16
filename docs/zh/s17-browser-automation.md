# s17: Browser Automation (浏览器自动化)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > [ s17 ] > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *terminal 让 agent 操作文件系统，browser 让 agent 操作网页。agent 看到的不是 HTML，而是一棵"页面上有什么可以点"的语义树。*

![浏览器自动化与无障碍树](../../illustrations/s17-browser/01-flowchart-accessibility-tree.png)

## 这一章要解决什么问题

agent 可以用 terminal 跑命令、用 read_file 读文件。但如果你让它"帮我在 GitHub 上提一个 issue"，它能做的只有调 API。

问题是：很多网站没有 API。或者 API 需要复杂的认证。或者你就是需要 agent 像人一样"打开网页 → 点按钮 → 填表单 → 提交"。

这就是浏览器工具要解决的：**让 agent 像人一样操作网页。**

## 建议联读

- [`s02-tool-system.md`](./s02-tool-system.md) — 浏览器工具注册在同一个 registry 里
- [`s14-terminal-backends.md`](./s14-terminal-backends.md) — terminal 操作文件系统，browser 操作网页，互补

## 先解释几个名词

### 什么是 accessibility tree（无障碍树）

浏览器内部维护的一棵语义树，描述"页面上有哪些可交互的元素"。它是给屏幕阅读器用的，但同样适合 agent——因为它回答的正好是 agent 关心的问题：**这个页面上有什么可以点、可以填、可以看的。**

和 HTML DOM 的区别：DOM 描述页面结构（div 嵌套 div），accessibility tree 描述页面语义（"这是一个搜索框""这是一个提交按钮"）。

### 什么是元素引用（@ref）

accessibility tree 里每个可交互的元素有一个编号，比如 `@e1`、`@e2`。agent 想点击一个按钮，不需要写 CSS 选择器，只需要说 `browser_click(ref="e3")`。

编号在每次获取页面快照时重新生成。DOM 变了（比如弹出了一个对话框），需要重新获取快照，旧的编号就失效了。

### 什么是 agent-browser

Hermes Agent 用来控制浏览器的外部工具。它是一个 Node.js CLI，底层用 Playwright 驱动 Chromium。Hermes 通过 subprocess 调用它，不直接操作浏览器。

## 从最笨的实现开始

让 agent 操作网页，最直接的想法：用 `requests` 库抓 HTML。

```python
def browser_navigate(args, **kwargs):
    import requests
    resp = requests.get(args["url"])
    return resp.text[:5000]  # 返回前 5000 字符的 HTML
```

三个问题：

### 问题一：HTML 不是人看的

返回 5000 字符的 `<div class="css-1a2b3c"><span aria-label="...">`——模型要从这堆标签里找出"搜索框在哪""提交按钮在哪"，又贵又慢又容易出错。

### 问题二：不能交互

`requests.get` 只能读页面，不能点按钮、填表单、等页面加载。而现代网页大量靠 JavaScript 渲染——你抓到的 HTML 可能是空的。

### 问题三：没有状态

每次请求都是独立的。你登录了网站，下一次请求不会带 cookie。你在搜索框里输了关键词，下一步看不到搜索结果。

**需要一个真正的浏览器——能渲染 JavaScript、能交互、能保持状态。** 但模型不需要"看到"完整的网页画面，它需要的是一个**结构化的、描述"页面上有什么"的表示**。

这就是 accessibility tree 的用处。

## 最小心智模型

```text
agent 调用 browser_navigate("https://github.com")
    │
    v
browser 工具（Python）
    │  subprocess 调用
    v
agent-browser CLI（Node.js）
    │  Playwright → CDP
    v
Chromium 浏览器（headless）
    │  渲染页面
    v
agent-browser 提取 accessibility tree
    │
    v
返回文本快照：
    navigation "GitHub"
      link "Sign in" [ref=e1]
      link "Sign up" [ref=e2]
      search "Search GitHub" [ref=e3]
      heading "Let's build from here" [level=1]
    │
    v
agent 看到快照，决定：browser_click(ref="e3") ← 点击搜索框
```

agent 看到的不是截图，不是 HTML，而是一棵**语义树**——"这里有一个链接叫 Sign in，编号 e1""这里有一个搜索框，编号 e3"。

### 为什么用 accessibility tree 而不是 HTML 或截图

| 方式 | 优点 | 缺点 |
|------|------|------|
| 原始 HTML | 完整 | 太长、太乱、大量无关标签 |
| 截图 + 视觉模型 | 最像人看到的 | 慢、贵、坐标定位不稳定 |
| accessibility tree | 紧凑、语义化、自带元素引用 | 看不到视觉样式 |

Hermes Agent 默认用 accessibility tree（快、便宜、对 LLM 友好），需要视觉理解时才用截图。

## agent 能做哪些操作

浏览器工具一共提供 9 个动作：

| 工具 | 做什么 | 例子 |
|------|--------|------|
| `browser_navigate(url)` | 打开网页 | `browser_navigate("https://github.com")` |
| `browser_snapshot()` | 获取页面快照 | 返回 accessibility tree |
| `browser_click(ref)` | 点击元素 | `browser_click(ref="e3")` |
| `browser_type(ref, text)` | 在输入框填文字 | `browser_type(ref="e3", text="hermes agent")` |
| `browser_scroll(direction)` | 滚动页面 | `browser_scroll(direction="down")` |
| `browser_back()` | 返回上一页 | |
| `browser_press(key)` | 按键盘键 | `browser_press(key="Enter")` |
| `browser_vision(question)` | 截图 + 视觉分析 | `browser_vision(question="页面布局是怎样的？")` |
| `browser_console(expression)` | 执行 JavaScript | `browser_console(expression="document.title")` |

### 一个完整的交互过程

agent 帮你在 GitHub 上搜索 "hermes agent"：

```text
1. browser_navigate("https://github.com")
   → 返回快照：... search "Search GitHub" [ref=e3] ...

2. browser_click(ref="e3")
   → 搜索框获得焦点

3. browser_type(ref="e3", text="hermes agent")
   → 搜索框里填入文字

4. browser_press(key="Enter")
   → 提交搜索

5. browser_snapshot()
   → 返回搜索结果页的快照：
     link "NousResearch/hermes-agent" [ref=e5]
     text "Self-improving AI agent..."
     link "NousResearch/hermes-agent-ui" [ref=e6]
     ...

6. agent 读快照，给用户总结搜索结果
```

全程没有写 CSS 选择器，没有解析 HTML，没有坐标定位。agent 通过元素引用（@ref）和语义描述完成所有操作。

## 截图 + 视觉分析：accessibility tree 不够用时

有些场景 accessibility tree 搞不定：

- 页面布局和视觉样式（"这个按钮在页面的什么位置？"）
- 验证码和图片内容
- 复杂的可视化（图表、地图）

这时用 `browser_vision`：

```text
agent 调用 browser_vision(question="页面上有验证码吗？")
    │
    v
browser 工具截图 → 保存 screenshot.png
    │
    v
把截图发给视觉模型（Gemini / Claude Vision）
    │  "看这张截图，回答：页面上有验证码吗？"
    v
视觉模型返回文字描述
    │
    v
agent 拿到描述，决定下一步操作
```

**默认用 accessibility tree（快、便宜），需要"看"的时候才用截图。**

## 浏览器会话：状态在调用之间保持

和 s14 的 terminal 后端类似，浏览器也需要跨调用保持状态——cookie、登录态、表单里已填的内容。

但浏览器不需要 snapshot 机制。为什么？因为浏览器本身就是一个长驻进程（不像 terminal 的 spawn-per-call 模型）。Hermes 启动一个 Chromium 实例，所有操作都在同一个浏览器里执行。cookie 和 localStorage 自然保持。

```text
browser_navigate("https://example.com/login")
browser_type(ref="e1", text="username")
browser_type(ref="e2", text="password")
browser_click(ref="e3")                      ← 点击登录
# 登录成功，浏览器记住了 cookie

browser_navigate("https://example.com/dashboard")
# 直接看到登录后的 dashboard，不需要重新登录
```

每个 `task_id` 有自己独立的浏览器会话。主 agent 和子 agent（s10）各自有独立的浏览器。

## 如何接到主循环里

和所有工具一样，浏览器工具注册在 s02 的 registry 里。核心循环不需要改动。

```text
核心循环
  │  tool_call: browser_navigate(url="https://github.com")
  v
registry.dispatch("browser_navigate", args)
  │
  v
browser 工具 handler
  │  subprocess: agent-browser navigate "https://github.com"
  v
agent-browser CLI → Playwright → Chromium
  │  渲染页面 → 提取 accessibility tree
  v
返回快照文本 → registry → 核心循环
```

## 初学者最容易犯的错

### 1. 每次操作都截图走视觉模型

截图 + 视觉分析一次要 2-5 秒，还消耗视觉模型的 token。大部分操作用 accessibility tree 就够了。

**修：默认用 `browser_snapshot`，只在需要视觉理解时才用 `browser_vision`。**

### 2. 用旧的 @ref 操作已经变化的页面

点击了一个链接，页面跳转了。旧的 @ref 编号已经失效，但 agent 还在用 `e3` 去点击。

**修：页面变化后必须重新调 `browser_snapshot` 获取新的引用编号。`browser_navigate` 会自动返回新快照。**

### 3. 在 accessibility tree 里找不到元素

有些网站的无障碍标注做得很差，accessibility tree 里看不到你想操作的元素。

**修：用 `browser_console(expression="document.querySelector('...')")` 直接操作 DOM，或者用 `browser_vision` 看截图找到位置。**

### 4. 不等页面加载完就操作

`browser_navigate` 返回后页面可能还在加载 JavaScript 内容。你立刻 `browser_snapshot`，拿到的是半截页面。

**修：agent-browser 会等页面稳定后再返回。如果内容靠 AJAX 延迟加载，可以先 `browser_snapshot` 检查内容是否完整，不完整就等一下再获取。**

## 教学边界

这一章只讲 agent 如何通过工具操作浏览器。

讲三件事：

1. **agent 怎么"看"网页** — accessibility tree 而不是 HTML 或截图
2. **agent 怎么操作网页** — 9 个动作，通过元素引用定位
3. **浏览器状态怎么保持** — 长驻 Chromium 进程，cookie 自然保持

不讲的：

- agent-browser CLI 的内部实现 → Node.js + Playwright，不影响 agent 工具层
- 反检测（Camofox、代理） → 生产环境的增强
- 云端浏览器（Browserbase） → 另一种后端，模式和本地相同
- 视觉模型的选择和调优 → s18 讲视觉能力

## 这一章和后续章节的关系

- **s02** 注册了浏览器工具 → 和内置工具、MCP 工具共存在同一个 registry
- **s14** 的终端后端操作文件系统 → 浏览器工具操作网页，两者互补
- **s18** 讲视觉和语音能力 → `browser_vision` 依赖视觉模型，是 s18 的前置
- **s10** 的子 agent 可以有自己的浏览器会话 → 通过 task_id 隔离

## 学完这章后，你应该能回答

- agent 调用 `browser_navigate` 后看到的是什么？HTML？截图？还是别的？
- 元素引用 @e1、@e2 是什么？为什么不用 CSS 选择器？
- `browser_snapshot` 和 `browser_vision` 分别在什么场景下用？
- 浏览器的 cookie 和登录态在多次调用之间会丢吗？为什么？
- 浏览器工具和 terminal 工具有什么关系？

---

**一句话记住：agent 通过 accessibility tree "看"网页，通过元素引用操作网页，不需要写 CSS 选择器或解析 HTML。**
