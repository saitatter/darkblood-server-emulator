# Tools

Run every script from the repository root (`python tools/<folder>/<script>.py`).
Scripts locate the repository from their own path, so the folder depth matters
when moving them.

| Folder | Contents |
| --- | --- |
| `automation/` | Live testing and agents: `gamectl.py` (start/stop/drive the client and server), `multibox.py` (1–4 tiled clients), `mcp_server.py` (MCP stdio server, see `.mcp.json`), `headless_client.py` (scripted protocol client used by the tests), `tail_wire.py`, `capture_server.py`. |
| `launcher/` | Player-facing launcher and release pipeline: `launcher.py` + `launcher_app/` (Tk UI), `updater.py` (GitHub release self-updater), `patcher.py`, `dashboard.py` (character web dashboard), `export_diagnostics.py`, `build_release.py` (release ZIP / PyInstaller). |
| `codegen/` | Generators and their client-side extractors: `gen_messages.py` (schemas → message dataclasses), `gen_progress.py`, `gen_opcode_registry.py`, `gen_gm_reference.py`, `extract_opcodes.py`, `extract_result_codes.py`, `extract_schemas.py`. CI runs the `--check` modes. |
| `client_data/` | Game data pipeline: `jpk_extractor.py` / `jpk_pack.py` (JPK archives), `build_client_data.py` (private workspace), `luac51_dump.py`, `export_assets.py`, `import_cash_shop.py`, `dbmesh.py` (mesh/animation parser and OBJ exporter, see `docs/MODEL_FORMAT.md`). |
| `reverse/` | Binary analysis: `decomp.ps1` + `ghidra/` scripts, `gen_symbols.py`, `opcode_xrefs.py`, `dump_stubs.py` / `resolve_stubs.py`, `image_to_pe.py`, `debug_client.c` (`build_debugger.bat`). |
| `model_viewer/` | Blender-like 3D viewer (`py -3.13 tools/model_viewer`; `pip install -r tools/model_viewer/requirements.txt`). Modules: `app` (entry), `window`, `panels`, `viewport`, `style`, `renderer` + `shaders` + `camera` (moderngl), `scene` (pose, skinning), `textures` (TGA/DDS variants Pillow cannot read). |

When reading the release changelog from GitHub, the launcher skips commits
with empty messages and continues to the remaining entries.

Cross-folder imports add the needed folder to `sys.path` explicitly (for example
`launcher.py` imports `automation/gamectl.py`); `tests/common.py` adds every folder.
