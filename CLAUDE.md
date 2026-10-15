# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project overview

`ollama2gguf.py` is a single-file, stdlib-only Python 3 CLI. It reads Ollama's on-disk manifests and creates hardlinks (or symlinks/copies) with readable `.gguf` names in a directory that llama.cpp consumes. See `README.md` for user-facing docs.

## Layout

- `ollama2gguf.py`: the entire tool
- `README.md`: usage and troubleshooting
- `CLAUDE.md`: this file

## Ollama storage format (key background)

```
<models>/
  manifests/<host>/<namespace>/<model>/<tag>   # JSON, no extension
  blobs/sha256-<hex>                           # content-addressed files
```

- Manifest `layers[]` entries have `mediaType` and `digest` (`sha256:<hex>`).
- Digest `sha256:abc` maps to blob filename `sha256-abc` (colon becomes dash).
- `application/vnd.ollama.image.model` is the GGUF weights.
- `application/vnd.ollama.image.projector` is the vision projector (mmproj).
- Other layers (template, params, system, license) are ignored.
- Default registry host is `registry.ollama.ai`; namespace `library` is the official set and is omitted from output names.

## Design rules

- **Stdlib only.** Do not add third-party dependencies.
- **Never modify or delete Ollama's own files** (manifests or blobs). The script only creates/removes entries in the user-supplied destination.
- **Idempotent.** Re-running must be safe; existing correct links are reported as already linked.
- **`--dry-run` must not touch the filesystem**, including not creating the destination directory.
- **`--prune` is conservative.** It only removes `.gguf` entries that are symlinks or have `st_nlink > 1`. Never delete regular standalone files.
- **Hardlink failures give an actionable error** (different filesystem, `fs.protected_hardlinks`) pointing to `--symlink`/`--copy`.
- Skip and report (don't crash on) unreadable manifests and missing blobs. Exit code is nonzero if any problem occurred.
- Output names go through `safe()` so they are filesystem-friendly on all platforms.

## Testing

No test suite yet. To verify changes manually, build a fake Ollama tree:

```bash
mkdir -p /tmp/fake/manifests/registry.ollama.ai/library/tiny /tmp/fake/blobs
echo gguf > /tmp/fake/blobs/sha256-aaa
cat > /tmp/fake/manifests/registry.ollama.ai/library/tiny/1b <<'EOF'
{"layers":[{"mediaType":"application/vnd.ollama.image.model","digest":"sha256:aaa"}]}
EOF
python3 ollama2gguf.py /tmp/out --models-src /tmp/fake --dry-run
python3 ollama2gguf.py /tmp/out --models-src /tmp/fake
ls -li /tmp/out /tmp/fake/blobs   # inode numbers should match
```

If adding tests, prefer `pytest` with `tmp_path` fixtures building the same fake tree, covering: naming for library/namespaced/`hf.co` models, mmproj linking, missing blob, re-run idempotency, `--prune`, and `--dry-run` making no changes.

## Style

- Python 3.8+ compatible (no `match`, no `X | Y` type unions).
- Keep it a single file unless it grows substantially.
- Print one status line per file; keep output scannable.
