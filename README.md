# ollama2gguf

Expose [Ollama](https://ollama.com) models as properly named `.gguf` files so [llama.cpp](https://github.com/ggml-org/llama.cpp) can use them directly, without downloading anything twice.

Ollama stores models as extensionless, content-addressed blobs (`blobs/sha256-<hash>`). This script reads Ollama's manifests, finds the GGUF weights (and vision projector, if any), and creates hardlinks with readable names in a directory of your choice. No extra disk space is used.

## Requirements

- Python 3.8+
- No third-party packages
- Ollama models already pulled on the same machine

## Quick start

```bash
# Preview what would happen
python3 ollama2gguf.py /path/to/llama-models --dry-run

# Create the links
python3 ollama2gguf.py /path/to/llama-models

# Use them with llama.cpp
llama-server --models-dir /path/to/llama-models
# or a single model:
llama-server -m /path/to/llama-models/llama3.2-3b.gguf
```

## Naming

| Ollama model | Link created |
|---|---|
| `llama3.2:3b` | `llama3.2-3b.gguf` |
| `someuser/foo:latest` | `someuser_foo-latest.gguf` |
| `hf.co/bartowski/Foo-GGUF:Q4_K_M` | `hf.co_bartowski_Foo-GGUF-Q4_K_M.gguf` |
| vision projector of `llava:7b` | `llava-7b.mmproj.gguf` |

Vision models need the projector passed to llama.cpp: `--mmproj llava-7b.mmproj.gguf`.

## Options

| Flag | Description |
|---|---|
| `dest` | Directory llama.cpp reads GGUFs from (created if missing) |
| `--models-src PATH` | Ollama models dir (the one containing `manifests/` and `blobs/`). Auto-detected if omitted |
| `--symlink` | Use symlinks instead of hardlinks |
| `--copy` | Copy files instead of linking |
| `--no-mmproj` | Skip vision projector files |
| `--prune` | Remove links in `dest` that no longer match an Ollama model |
| `--dry-run`, `-n` | Show what would happen without changing anything |

## Where it looks for Ollama models

In order:

1. `--models-src`
2. `$OLLAMA_MODELS`
3. `~/.ollama/models`
4. `/usr/share/ollama/.ollama/models` (Linux systemd install)
5. `/var/lib/ollama/models`

## Notes and troubleshooting

- **Same filesystem required for hardlinks.** If `dest` is on a different drive or mount than the Ollama blobs, hardlinking fails. Use `--symlink` (no extra space) or `--copy`.
- **"Operation not permitted" on Linux.** With the systemd install, blobs are owned by the `ollama` user and `fs.protected_hardlinks` blocks hardlinking files you don't own or can't write. Options:
  - Add your user to the `ollama` group and make the blobs group-writable
  - Use `--symlink` (only needs read access)
  - Run with `sudo`
- **Re-running is safe.** Links already in place are skipped, so run it again after each `ollama pull`.
- **`ollama rm` and hardlinks.** Removing a model in Ollama deletes its blob name, but your hardlink keeps the data alive until you delete the link too. Use `--prune` to clean up links for removed models; note that it only removes the stale link, and disk space is freed once all links are gone.
- **`--prune` is conservative.** It only removes `.gguf` entries that are symlinks or hardlinked files. Standalone GGUFs you downloaded yourself are left alone.
- **Missing blobs** (partial downloads) are reported and skipped.

## License

Use however you like.
