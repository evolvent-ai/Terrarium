# Workspace Capability API

A bare Docker container with filesystem and shell access. The image defaults to `ubuntu:24.04` but is overridden by the agent (e.g., `terrarium/claude-code` for ClaudeCodeAgent).

Workspace is automatically included for sandbox-based agents even if not listed in capabilities.

## connection_info

```python
info = env.workspace.connection_info
# {
#     "hostname": "<container_hostname>",
#     "image": "terrarium/claude-code:latest",
# }
```

## Filesystem (env.workspace.fs)

### read_file()

```python
env.workspace.fs.read_file(path: str) -> bytes
```

Read a file from the container filesystem.

**Parameters:**
- `path` — absolute path inside the container

**Returns:** file contents as bytes.

```python
content = env.workspace.fs.read_file("/root/output.txt")
text = content.decode()
```

### write_file()

```python
env.workspace.fs.write_file(path: str, content: bytes) -> None
```

Write a file to the container filesystem. Creates or overwrites the file.

**Parameters:**
- `path` — absolute path inside the container
- `content` — file contents as bytes

```python
env.workspace.fs.write_file("/root/config.json", b'{"key": "value"}')
```

### upload()

```python
env.workspace.fs.upload(local_path: str, sandbox_path: str) -> None
```

Upload a file or directory from the host machine to the container.

**Parameters:**
- `local_path` — path on the host (must be absolute or resolvable)
- `sandbox_path` — destination path inside the container

```python
from pathlib import Path
RESOURCES = Path(__file__).resolve().parent / "resources"

env.workspace.fs.upload(str(RESOURCES / "notes"), "/root/notes")       # directory
env.workspace.fs.upload(str(RESOURCES / "data.csv"), "/root/data.csv") # file
```

### download()

```python
env.workspace.fs.download(sandbox_path: str, local_path: str) -> None
```

Download a file or directory from the container to the host machine.

**Parameters:**
- `sandbox_path` — path inside the container
- `local_path` — destination path on the host

### exists()

```python
env.workspace.fs.exists(path: str) -> bool
```

Check if a file or directory exists in the container.

**Parameters:**
- `path` — absolute path inside the container

**Returns:** `True` if the path exists, `False` otherwise.

```python
if env.workspace.fs.exists("/root/notes.md"):
    # agent created the file
```

### list_dir()

```python
env.workspace.fs.list_dir(path: str) -> list[str]
```

List entries in a directory.

**Parameters:**
- `path` — absolute path to a directory inside the container

**Returns:** list of filenames (not full paths). Raises `SandboxError` if the directory doesn't exist.

```python
files = env.workspace.fs.list_dir("/root/results")
# ["result_epoch_50.txt", "result_epoch_100.txt"]
```

### make_dir()

```python
env.workspace.fs.make_dir(path: str) -> None
```

Create a directory recursively (like `mkdir -p`).

**Parameters:**
- `path` — absolute path to create

### remove()

```python
env.workspace.fs.remove(path: str) -> None
```

Remove a file or directory recursively (like `rm -rf`).

**Parameters:**
- `path` — absolute path to remove

## Shell (env.workspace.shell)

### exec()

```python
env.workspace.shell.exec(command: str | list[str], timeout: float | None = None) -> ExecResult
```

Execute a shell command inside the container. The command is run via `sh -c`.

**Parameters:**
- `command` — shell command as a string, or list of strings (joined with spaces)
- `timeout` — optional timeout in seconds

**Returns:** `ExecResult` with three fields:
- `exit_code: int` — 0 for success
- `stdout: str` — standard output
- `stderr: str` — standard error

```python
result = env.workspace.shell.exec("cat /root/output.txt")
assert result.exit_code == 0
print(result.stdout)

result = env.workspace.shell.exec("python3 /root/script.py", timeout=30.0)
if result.exit_code != 0:
    print(result.stderr)
```
