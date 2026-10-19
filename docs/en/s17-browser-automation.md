# s17: Browser Automation

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > [ s17 ] > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *The terminal lets the agent operate the file system; the browser lets the agent operate web pages. What the agent sees is not HTML, but a semantic tree describing "what on the page can be clicked."*

![Browser Automation and Accessibility Tree](../../illustrations/en/s17-browser/01-flowchart-accessibility-tree.png)

## What problem does this chapter solve

The agent can run commands via the terminal and read files with read_file. But if you ask it to "file an issue on GitHub," all it can do is call an API.

The problem is: many websites don't have an API. Or the API requires complex authentication. Or you simply need the agent to act like a human -- "open a page -> click a button -> fill out a form -> submit."

This is what the browser tool solves: **letting the agent operate web pages like a human would.**

## Suggested reading

- [`s02-tool-system.md`](./s02-tool-system.md) -- browser tools are registered in the same registry
- [`s14-terminal-backends.md`](./s14-terminal-backends.md) -- the terminal operates the file system, the browser operates the web; they complement each other

## Key terms

### What is an accessibility tree

A semantic tree maintained internally by the browser that describes "what interactive elements are on the page." It was designed for screen readers, but it suits agents equally well -- because it answers exactly the question the agent cares about: **what on this page can be clicked, filled in, or read.**

The difference from the HTML DOM: the DOM describes page structure (divs nested inside divs), while the accessibility tree describes page semantics ("this is a search box," "this is a submit button").

### What is an element reference (@ref)

Every interactive element in the accessibility tree has a number, such as `@e1`, `@e2`. When the agent wants to click a button, it doesn't need to write a CSS selector -- it just says `browser_click(ref="e3")`.

Numbers are regenerated each time a page snapshot is taken. If the DOM changes (e.g., a dialog pops up), you need to take a new snapshot, and old numbers become invalid.

### What is agent-browser

The external tool Hermes Agent uses to control the browser. It is a Node.js CLI that uses Playwright under the hood to drive Chromium. Hermes calls it via subprocess and does not interact with the browser directly.

## Starting with the simplest implementation

The most straightforward idea for having the agent operate web pages: use the `requests` library to fetch HTML.

```python
def browser_navigate(args, **kwargs):
    import requests
    resp = requests.get(args["url"])
    return resp.text[:5000]  # Return the first 5000 characters of HTML
```

Three problems:

### Problem 1: HTML is not meant for reading

Returning 5000 characters of `<div class="css-1a2b3c"><span aria-label="...">` -- the model has to sift through these tags to find "where is the search box" and "where is the submit button." Expensive, slow, and error-prone.

### Problem 2: No interactivity

`requests.get` can only read pages; it cannot click buttons, fill forms, or wait for page loads. And modern web pages rely heavily on JavaScript rendering -- the HTML you fetch might be empty.

### Problem 3: No state

Each request is independent. You log in to a website, but the next request won't carry the cookie. You type a keyword in the search box, but you can't see the search results in the next step.

**You need a real browser -- one that can render JavaScript, interact with elements, and maintain state.** But the model doesn't need to "see" the full visual rendering of a web page; what it needs is a **structured representation describing "what's on the page."**

That's where the accessibility tree comes in.

## Minimal mental model

```text
The agent calls browser_navigate("https://github.com")
    |
    v
Browser tool (Python)
    |  subprocess call
    v
agent-browser CLI (Node.js)
    |  Playwright -> CDP
    v
Chromium browser (headless)
    |  Renders the page
    v
agent-browser extracts the accessibility tree
    |
    v
Returns a text snapshot:
    navigation "GitHub"
      link "Sign in" [ref=e1]
      link "Sign up" [ref=e2]
      search "Search GitHub" [ref=e3]
      heading "Let's build from here" [level=1]
    |
    v
The agent reads the snapshot and decides: browser_click(ref="e3") <- click the search box
```

What the agent sees is not a screenshot, not HTML, but a **semantic tree** -- "here's a link called Sign in, numbered e1," "here's a search box, numbered e3."

### Why use the accessibility tree instead of HTML or screenshots

| Approach | Pros | Cons |
|----------|------|------|
| Raw HTML | Complete | Too long, too messy, lots of irrelevant tags |
| Screenshot + vision model | Closest to what a human sees | Slow, expensive, coordinate-based targeting is unstable |
| Accessibility tree | Compact, semantic, built-in element references | Cannot see visual styles |

Hermes Agent defaults to the accessibility tree (fast, cheap, LLM-friendly) and only uses screenshots when visual understanding is needed.

## What actions the agent can perform

The browser tool provides 9 actions in total:

| Tool | What it does | Example |
|------|-------------|---------|
| `browser_navigate(url)` | Open a web page | `browser_navigate("https://github.com")` |
| `browser_snapshot()` | Get a page snapshot | Returns the accessibility tree |
| `browser_click(ref)` | Click an element | `browser_click(ref="e3")` |
| `browser_type(ref, text)` | Type text in an input field | `browser_type(ref="e3", text="hermes agent")` |
| `browser_scroll(direction)` | Scroll the page | `browser_scroll(direction="down")` |
| `browser_back()` | Go back to the previous page | |
| `browser_press(key)` | Press a keyboard key | `browser_press(key="Enter")` |
| `browser_vision(question)` | Screenshot + visual analysis | `browser_vision(question="What does the page layout look like?")` |
| `browser_console(expression)` | Execute JavaScript | `browser_console(expression="document.title")` |

### A complete interaction walkthrough

The agent helps you search for "hermes agent" on GitHub:

```text
1. browser_navigate("https://github.com")
   -> Returns snapshot: ... search "Search GitHub" [ref=e3] ...

2. browser_click(ref="e3")
   -> The search box gains focus

3. browser_type(ref="e3", text="hermes agent")
   -> Text is entered in the search box

4. browser_press(key="Enter")
   -> The search is submitted

5. browser_snapshot()
   -> Returns a snapshot of the search results page:
     link "NousResearch/hermes-agent" [ref=e5]
     text "Self-improving AI agent..."
     link "NousResearch/hermes-agent-ui" [ref=e6]
     ...

6. The agent reads the snapshot and summarizes the search results for the user
```

Throughout the entire process, no CSS selectors were written, no HTML was parsed, and no coordinates were used for targeting. The agent accomplished everything through element references (@ref) and semantic descriptions.

## Screenshot + visual analysis: when the accessibility tree is not enough

Some scenarios where the accessibility tree falls short:

- Page layout and visual styling ("Where on the page is this button?")
- CAPTCHAs and image content
- Complex visualizations (charts, maps)

In these cases, use `browser_vision`:

```text
The agent calls browser_vision(question="Is there a CAPTCHA on the page?")
    |
    v
The browser tool takes a screenshot -> saves screenshot.png
    |
    v
Sends the screenshot to a vision model (Gemini / Claude Vision)
    |  "Look at this screenshot and answer: Is there a CAPTCHA on the page?"
    v
The vision model returns a text description
    |
    v
The agent receives the description and decides on the next action
```

**Default to the accessibility tree (fast, cheap); only use screenshots when you need to "see."**

## Browser sessions: state persists across calls

Similar to the terminal backend in s14, the browser also needs to maintain state across calls -- cookies, login state, content already typed in forms.

But the browser doesn't need a snapshot mechanism. Why? Because the browser itself is a long-running process (unlike the terminal's spawn-per-call model). Hermes starts a single Chromium instance, and all operations execute within the same browser. Cookies and localStorage persist naturally.

```text
browser_navigate("https://example.com/login")
browser_type(ref="e1", text="username")
browser_type(ref="e2", text="password")
browser_click(ref="e3")                      <- Click login
# Login succeeds, the browser remembers the cookie

browser_navigate("https://example.com/dashboard")
# You see the logged-in dashboard directly, no need to log in again
```

Each `task_id` has its own independent browser session. The main agent and sub-agents (s10) each have separate browsers.

## How it plugs into the main loop

Like all tools, browser tools are registered in s02's registry. The core loop requires no changes.

```text
Core loop
  |  tool_call: browser_navigate(url="https://github.com")
  v
registry.dispatch("browser_navigate", args)
  |
  v
Browser tool handler
  |  subprocess: agent-browser navigate "https://github.com"
  v
agent-browser CLI -> Playwright -> Chromium
  |  Renders page -> extracts accessibility tree
  v
Returns snapshot text -> registry -> core loop
```

## Common beginner mistakes

### 1. Taking a screenshot and using the vision model for every action

Screenshot + visual analysis takes 2-5 seconds per call and consumes vision model tokens. The accessibility tree is sufficient for most operations.

**Fix: Default to `browser_snapshot`; only use `browser_vision` when visual understanding is actually needed.**

### 2. Using stale @ref values on a page that has changed

You clicked a link and the page navigated. The old @ref numbers are now invalid, but the agent is still trying to click `e3`.

**Fix: After any page change, call `browser_snapshot` again to get new reference numbers. `browser_navigate` automatically returns a new snapshot.**

### 3. Unable to find an element in the accessibility tree

Some websites have poor accessibility annotations, and the element you want to interact with doesn't appear in the accessibility tree.

**Fix: Use `browser_console(expression="document.querySelector('...')")` to manipulate the DOM directly, or use `browser_vision` to take a screenshot and locate the element visually.**

### 4. Operating before the page finishes loading

After `browser_navigate` returns, the page might still be loading JavaScript content. If you immediately call `browser_snapshot`, you get a half-loaded page.

**Fix: agent-browser waits for the page to stabilize before returning. If content is lazy-loaded via AJAX, call `browser_snapshot` to check whether the content is complete; if not, wait a moment and try again.**

## Scope of this chapter

This chapter only covers how the agent operates the browser through tools.

It covers three things:

1. **How the agent "sees" web pages** -- the accessibility tree, not HTML or screenshots
2. **How the agent operates web pages** -- 9 actions, targeting via element references
3. **How browser state is maintained** -- a long-running Chromium process with natural cookie persistence

Not covered:

- Internal implementation of the agent-browser CLI -> Node.js + Playwright; doesn't affect the agent's tool layer
- Anti-detection (Camofox, proxies) -> production-level enhancements
- Cloud browsers (Browserbase) -> an alternative backend with the same usage pattern as local
- Vision model selection and tuning -> covered in s18's vision capabilities

## How this chapter relates to others

- **s02** registered the browser tools -> they coexist with built-in tools and MCP tools in the same registry
- **s14**'s terminal backend operates the file system -> browser tools operate the web; the two complement each other
- **s18** covers vision and voice capabilities -> `browser_vision` depends on the vision model, making s18 a follow-up
- **s10**'s sub-agents can have their own browser sessions -> isolated via task_id

## After finishing this chapter, you should be able to answer

- What does the agent see after calling `browser_navigate`? HTML? A screenshot? Or something else?
- What are element references like @e1 and @e2? Why not use CSS selectors?
- When would you use `browser_snapshot` vs. `browser_vision`?
- Do browser cookies and login state persist across multiple calls? Why?
- What is the relationship between browser tools and terminal tools?

---

**One sentence to remember: The agent "sees" web pages through the accessibility tree and operates them through element references -- no CSS selectors or HTML parsing required.**
