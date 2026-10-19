# s14: Terminal Backends

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > [ s14 ] > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *Tools call the terminal to execute commands. But where the command runs -- locally, in Docker, or on a remote machine via SSH -- is something the tool doesn't need to know.*

![Terminal Backend Abstraction](../../illustrations/en/s14-terminal-backends/01-framework-backend-abstraction.png)

## What problem does this chapter solve

In s01-s11, the terminal tool's implementation is four lines of code:

```python
def run_terminal(args, **kwargs):
    result = subprocess.run(
        args["command"], shell=True,
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout + result.stderr
```

It runs directly on the local machine. Now product says: "Can we let the agent run commands inside a Docker container?"

The most obvious approach is adding if-else to the tool function. But you'll immediately hit two problems.

## Suggested reading

- [`s02-tool-system.md`](./s02-tool-system.md) -- How the terminal tool is registered and dispatched
- [`s00-architecture-overview.md`](./s00-architecture-overview.md) -- Where the execution environment layer sits in the five-layer architecture

## Key terminology

### What is a snapshot

The agent runs `cd /tmp` then runs `pwd`, expecting to see `/tmp`. But `subprocess.run` starts a new bash each time. The previous bash's directory and variables are lost when that process exits.

Snapshot solves this problem: **after each command executes, the current environment variables and working directory are saved to a file; before the next command executes, they are restored from that file.** This way, even though each command runs in a new bash, the state is continuous.

A snapshot consists of two files, with paths generated when the BaseEnvironment is created:

```python
self._session_id = uuid.uuid4().hex[:12]   # Random 12 chars, e.g. "a1b2c3d4e5f6"
self._snapshot_path = f"/tmp/hermes-snap-{self._session_id}.sh"   # Environment variables
self._cwd_file = f"/tmp/hermes-cwd-{self._session_id}.txt"        # Working directory
```

All commands within the same BaseEnvironment instance share these two files. Their contents look like:

```bash
# /tmp/hermes-snap-a1b2c3.sh
export PATH="/usr/local/bin:/usr/bin:/bin"
export MY_VAR="hello"
```

```text
# /tmp/hermes-cwd-a1b2c3.txt
/workspace/myproject
```

### What is BaseEnvironment

The abstract base class for all terminal backends. On creation, it generates a session_id and snapshot paths. Subclasses only need to implement two methods:

- `_run_bash(cmd_string)` -- How to start bash (subprocess / docker exec / ssh)
- `cleanup()` -- How to release resources (delete files / stop container / close connection)

Command wrapping, snapshot restore/save, and timeout handling are all in the base class, shared by every backend.

## Starting with the simplest possible implementation

Adding if-else in the terminal tool:

```python
if backend == "local":
    result = subprocess.run(command, shell=True, ...)
elif backend == "docker":
    result = subprocess.run(["docker", "exec", container, "bash", "-c", command], ...)
elif backend == "ssh":
    result = subprocess.run(["ssh", f"{user}@{host}", "bash", "-c", command], ...)
```

It works, but has two problems.

### Problem 1: Non-continuous state

The agent executes three commands in sequence:

```text
Command 1: cd /workspace/myproject
Command 2: export MY_VAR=hello
Command 3: echo $MY_VAR && pwd
```

Each command starts a new bash process:

```text
Command 1 -> Process #1 -> cd succeeds -> process exits, directory lost
Command 2 -> Process #2 -> export succeeds -> process exits, variable lost
Command 3 -> Process #3 -> $MY_VAR doesn't exist, pwd outputs the initial directory
```

You might think: "Maintain a long-running bash process, write commands to stdin, and state naturally persists."

This path is a dead end, with three pitfalls:

- **Output boundaries.** You wrote `ls` -- how do you know when `ls`'s output is done? There's no delimiter. You'd have to sneak in an `echo __MARKER__` after every command and look for the marker in stdout. Very fragile.
- **Hang propagation.** The agent ran `cat` (without a filename -- it waits for input forever). You can't kill just that command -- either kill the entire bash (losing all state) or wait for timeout.
- **Multi-line commands.** The agent wrote `for i in 1 2 3; do ... done`. Bash won't execute until it sees `done`. You'd need to understand bash syntax to know when to read output -- essentially rewriting a shell parser.

**Hermes Agent's approach: Each command still starts a new bash, but state is passed between them via snapshot files.**

### Problem 2: If-else explosion

After adding Docker and SSH, if you also need Modal, Daytona, and Singularity, that's six branches. This is the same problem as s12 -- and the solution is the same: **extract a common interface and let each backend implement it.**

## Walking through the full flow with three commands

See how snapshots let state persist across new bash processes.

Before each command is sent to the backend, the base class wraps it into a five-line script:

```text
source snapshot.sh       <-- Restore environment variables from last time
cd {last working dir}    <-- Restore last directory
{user's command}         <-- The actual command to execute
export -p > snapshot.sh  <-- Save new environment variables
pwd -P > cwd.txt         <-- Save new working directory
```

The complete flow for three commands:

```text
=== Command 1: cd /workspace/myproject ===

Wrapped as:
  source snapshot.sh          <-- Empty on first run, skipped
  cd /home/user               <-- Initial directory
  cd /workspace/myproject     <-- User's command
  export -p > snapshot.sh     <-- Save environment
  pwd -P > cwd.txt            <-- Save /workspace/myproject

-> Bash process #1 finishes, exits
-> Base class reads cwd.txt -> remembers directory is /workspace/myproject

=== Command 2: export MY_VAR=hello ===

Wrapped as:
  source snapshot.sh          <-- Restore environment from command 1
  cd /workspace/myproject     <-- Restore directory from end of command 1
  export MY_VAR=hello         <-- User's command
  export -p > snapshot.sh     <-- Save (now includes MY_VAR=hello)
  pwd -P > cwd.txt

-> Bash process #2 finishes, exits

=== Command 3: echo $MY_VAR && pwd ===

Wrapped as:
  source snapshot.sh          <-- Restore, includes MY_VAR=hello
  cd /workspace/myproject     <-- Correct directory
  echo $MY_VAR && pwd         <-- User's command

Output:
  hello
  /workspace/myproject         OK
```

Three different bash processes, but the agent sees continuous state.

**The core is this five-line wrapper script.** Every backend (local, Docker, SSH) uses the same wrapping logic -- the only difference is "where these five lines execute."

## Minimal mental model

```text
terminal tool
    |
    |  execute("pip install numpy")
    v
BaseEnvironment (base class)
    |
    |  1. Wrap: source snap -> cd -> user command -> export -p -> pwd
    |  2. Hand to subclass: _run_bash(wrapped command)
    |  3. Wait for output, read cwd.txt to update directory
    |
    +-- LocalBackend:   subprocess.Popen(["bash", "-c", ...])
    +-- DockerBackend:  subprocess.Popen(["docker", "exec", ..., "bash", "-c", ...])
    +-- SSHBackend:     subprocess.Popen(["ssh", ..., "bash", "-c", ...])
```

The base class handles steps 1 and 3 (shared by all backends); subclasses only handle step 2 (each is different).

## Minimal implementation

### Command wrapping (base class, shared by all backends)

```python
def _wrap_command(self, command: str) -> str:
    parts = []
    if self._snapshot_ready:
        parts.append(f"source {self._snapshot_path} 2>/dev/null")
    parts.append(f"cd {shlex.quote(self.cwd)} 2>/dev/null")
    parts.append(command)
    # Save exit code first, then save snapshot, then exit with saved code
    # Otherwise export -p's exit code (always 0) would overwrite the user command's exit code
    parts.append(f"_exit=$?; export -p > {self._snapshot_path} 2>/dev/null; "
                  f"pwd -P > {self._cwd_file} 2>/dev/null; exit $_exit")
    return "; ".join(parts)
```

### Local backend

The simplest -- just calls subprocess:

```python
class LocalBackend(BaseEnvironment):

    def _run_bash(self, cmd_string, *, timeout):
        # Filter API keys to prevent agent commands from reading OPENAI_API_KEY etc.
        env = {k: v for k, v in os.environ.items()
               if k not in _SECRET_BLOCKLIST}
        return subprocess.Popen(
            ["bash", "-c", cmd_string],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env,
        )

    def cleanup(self):
        for f in [self._snapshot_path, self._cwd_file]:
            try: os.unlink(f)
            except FileNotFoundError: pass
```

Why filter environment variables? Because the local backend's subprocess inherits all of the host machine's environment variables. Without filtering, the agent could run `env | grep KEY` to grab your API keys. Docker and SSH backends don't need this -- containers and remote machines don't have these variables by nature.

### Docker backend

The key difference: start a long-running container first, then send each command via `docker exec`.

```python
class DockerBackend(BaseEnvironment):

    def __init__(self, image="python:3.11-slim", **kwargs):
        super().__init__(**kwargs)
        self._image = image
        self._container_id = None

    def _ensure_container(self):
        """Start a container before the first command; reuse it afterwards."""
        if self._container_id:
            return
        result = subprocess.run([
            "docker", "run", "-d",
            "--name", f"hermes-{self._session_id}",
            "--cap-drop", "ALL",                    # Drop all capabilities
            "--security-opt", "no-new-privileges",  # Prevent privilege escalation
            "--pids-limit", "256",                   # Prevent fork bombs
            "--memory", "512m",                      # Memory cap
            self._image, "sleep", "infinity",        # Keep container running
        ], capture_output=True, text=True)
        self._container_id = result.stdout.strip()

    def _run_bash(self, cmd_string, *, timeout):
        self._ensure_container()
        return subprocess.Popen(
            ["docker", "exec", "-i", self._container_id,
             "bash", "-c", cmd_string],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    def cleanup(self):
        if self._container_id:
            subprocess.run(["docker", "rm", "-f", self._container_id],
                           capture_output=True)
```

Why use a long-running container instead of `docker run` for every command? Because snapshot files live in the container's filesystem. If the container is destroyed, the snapshot is lost, and state breaks.

Security parameters explained:

| Parameter | What it prevents |
|-----------|------------------|
| `--cap-drop ALL` | Agent can't mount filesystems or modify network rules |
| `--no-new-privileges` | Setuid programs in the container can't escalate privileges |
| `--pids-limit 256` | Fork bombs can only create 256 processes |
| `--memory 512m` | Memory exhaustion only affects the container, not the host |

### SSH backend

```python
class SSHBackend(BaseEnvironment):

    def __init__(self, host, user, key_path=None, **kwargs):
        super().__init__(**kwargs)
        self._host = host
        self._user = user
        self._key_path = key_path
        self._control_socket = f"/tmp/hermes-ssh/{user}@{host}.sock"

    def _ssh_args(self):
        args = [
            "ssh",
            "-o", "ControlMaster=auto",           # Connection multiplexing
            "-o", f"ControlPath={self._control_socket}",
            "-o", "ControlPersist=300",            # Disconnect after 5 minutes idle
            "-o", "BatchMode=yes",                 # No interactive prompts
        ]
        if self._key_path:
            args += ["-i", self._key_path]
        args.append(f"{self._user}@{self._host}")
        return args

    def _run_bash(self, cmd_string, *, timeout):
        return subprocess.Popen(
            self._ssh_args() + ["bash", "-c", shlex.quote(cmd_string)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    def cleanup(self):
        subprocess.run(
            ["ssh", "-O", "exit",
             "-o", f"ControlPath={self._control_socket}",
             f"{self._user}@{self._host}"],
            capture_output=True)
```

`ControlMaster` enables SSH connection multiplexing. The first command establishes the TCP connection and authentication; subsequent commands reuse the same connection. Without it, 30 commands means 30 handshakes + authentications.

### Backend selection

One line in config.yaml switches the backend; the tool code doesn't change:

```yaml
terminal:
  backend: docker    # "local" | "docker" | "ssh"
  docker_image: python:3.11-slim
```

```python
def create_backend(config):
    backend_type = config.get("terminal", {}).get("backend", "local")
    if backend_type == "docker":
        return DockerBackend(image=..., cwd="/workspace")
    elif backend_type == "ssh":
        return SSHBackend(host=..., user=..., cwd="~")
    else:
        return LocalBackend(cwd=os.getcwd())
```

### How remote backends read the cwd file

The local backend's snapshot and cwd files are in the local `/tmp`, directly readable. Docker and SSH backends have these files in the container or on the remote machine, requiring an extra step:

```text
Local backend:    Read /tmp/hermes-cwd-xxx.txt directly
Docker backend:   docker exec cat /tmp/hermes-cwd-xxx.txt
SSH backend:      ssh cat /tmp/hermes-cwd-xxx.txt (reuses ControlMaster, nearly zero overhead)
```

Transparent to the layer above -- after `execute()` returns, `self.cwd` is always up to date.

## How it connects to the main loop

```text
Core loop
  |  tool_call: terminal("pip install numpy")
  v
terminal tool
  |  -> Permission check (s09)
  |  -> backend.execute("pip install numpy")
  v
BaseEnvironment (currently DockerBackend)
  |  Wrap: source snap -> cd -> pip install numpy -> export -p -> pwd
  |  Execute: docker exec hermes-a1b2c3 bash -c "..."
  v
Docker container
  |  Output + return code
  v
terminal tool
  |  tool_result: "Successfully installed numpy-1.26.4"
  v
Core loop (continues to next iteration)
```

The core loop only sees that the terminal tool returned some text. It doesn't know the command ran in Docker.

## Most common beginner mistakes

### 1. Forgetting to filter API keys

The local backend passes all environment variables to the subprocess. The agent runs `env | grep KEY` and sees your secrets.

**Fix: Filter the secret blocklist from subprocess environment variables. Docker and SSH don't need this -- containers/remote machines don't have these variables by nature.**

### 2. Not adding resource limits to Docker

The agent runs a memory-hungry script, and the host machine goes down with it.

**Fix: `--memory` and `--pids-limit` must be configured.**

### 3. SSH creates a new connection for every command

30 commands = 30 TCP connections + authentications.

**Fix: Use ControlMaster for connection multiplexing.**

### 4. Chaining the wrapper script with `&&`

`source snap && cd ... && user command && export -p` -- if the user's command returns non-zero, `export -p` doesn't execute. The snapshot breaks, and all subsequent commands lose their environment state.

**Fix: Use `;` to separate commands, or save the exit code before exporting (see the `_exit=$?` pattern in the implementation).**

## Scope of this chapter

This chapter only covers the backend abstraction for the **terminal tool**. `read_file`, `write_file`, and similar tools don't go through this layer -- they operate on the filesystem directly via Python code, no snapshot mechanism needed.

Why does terminal need this while read_file doesn't? Because terminal has **cross-command state** -- the agent's `cd` and `export` must take effect in subsequent commands. That's the core problem snapshots solve. `read_file` is stateless: given a path, return the contents, no need to remember what was read last time. Under Docker, changing `open(path)` to `docker exec cat path` is a one-line modification.

Three things covered:

1. **Why backend abstraction is needed** -- Derived from the pain of if-else
2. **How snapshots make state persist across commands** -- Walk through three commands
3. **Three backend implementations** -- Local (key filtering), Docker (long-running container + security parameters), SSH (ControlMaster)

Not covered:

- Modal / Daytona / Singularity -> same pattern as Docker
- Background process management -> a terminal tool feature, not a backend responsibility
- File synchronization (how SSH transfers local files to remote) -> an SSH backend enhancement
- Idle environment reclamation -> production optimization

## How this chapter relates to later chapters

- **s02** registered the terminal tool -> this chapter defines its underlying execution environment
- **s09**'s permission system intercepts dangerous commands -> before they reach the backend
- **s13**'s adapter abstraction and this chapter's backend abstraction follow the same approach -- encapsulate differences so the layer above doesn't care
- **s15**'s scheduled tasks also execute commands -> they reuse the same backend

## After this chapter, you should be able to answer

- The agent ran `cd /tmp` then `pwd` -- why does it output `/tmp`? Doesn't each command run in a new bash?
- Why not maintain a long-running bash process?
- Does the local backend need to filter API keys? Does the Docker backend? Why or why not?
- Why does the Docker backend use a long-running container instead of `docker run` for every command?
- Switching from `local` to `docker` in config.yaml -- how many lines of tool code need to change?

---

**In one sentence: A backend only needs to implement "how to start bash" and "how to clean up." Snapshots make environment variables and working directories seamlessly persist across new bash processes.**
