# Tools

Run every script from the repository root (`python tools/<folder>/<script>.py`).
Scripts locate the repository from their own path, so the folder depth matters
when moving them.

For releases without a manifest, the updater prefers the portable Windows ZIP
and reads the checksum attached to that ZIP's filename.

| Folder | Contents |
| --- | --- |
| `automation/` | Live testing and agents: `gamectl.py` (start/stop/drive the client and server), `multibox.py` (1–4 tiled clients), `mcp_server.py` (MCP stdio server, see `.mcp.json`), `test_data.py` (test characters in a scratch database for `gamectl start --data-dir`, including chosen gathering and crafting professions from `--skill`), `headless_client.py` (scripted protocol client used by the tests), `tail_wire.py`, `capture_server.py`. |
| `launcher/` | Player-facing launcher and release pipeline: `launcher.py` + `launcher_app/` (Tk UI), `updater.py` (GitHub release self-updater), `patcher.py`, `dashboard.py` (character web dashboard), `export_diagnostics.py`, `build_release.py` (release ZIP / PyInstaller). Changelog categories recognize breaking-change prefixes such as `feat(lobby)!`. |
| `codegen/` | Generators and their client-side extractors: `gen_messages.py` (schemas → message dataclasses), `gen_progress.py`, `gen_opcode_registry.py`, `gen_gm_reference.py`, `extract_opcodes.py`, `extract_result_codes.py`, `extract_schemas.py`. CI runs the `--check` modes. |
| `client_data/` | Game data pipeline: `jpk_extractor.py` / `jpk_pack.py` (JPK archives), `build_client_data.py` (private workspace), `luac51_dump.py`, `export_assets.py`, `import_cash_shop.py`, `extract_gtargets.py` (town map objects → `assets/gtargets.tsv`, `--check`), `dbmesh.py` (mesh/animation parser and OBJ exporter, see `docs/MODEL_FORMAT.md`). |
| `reverse/` | Binary analysis: `decomp.ps1` + `ghidra/` scripts, `client_inspect.py` (strings at VAs, localized texts, callers, decompiles), `gen_symbols.py`, `opcode_xrefs.py`, `dump_stubs.py` / `resolve_stubs.py`, `image_to_pe.py`, `debug_client.c` (`build_debugger.bat`). |
| `model_viewer/` | Blender-like 3D viewer (`py -3.13 tools/model_viewer`; `pip install -r tools/model_viewer/requirements.txt`). Modules: `app` (entry), `window`, `panels`, `viewport`, `style`, `renderer` + `shaders` + `camera` (moderngl), `scene` (pose, skinning), `textures` (TGA/DDS variants Pillow cannot read). |

When reading the release changelog from GitHub, the launcher skips commits
with empty messages and continues to the remaining entries. The updater keeps
the prior release's files until the new version and manifest are written.

Saving launcher settings preserves extra sections and keys already present in
`darkblood_options.ini`.

Cross-folder imports add the needed folder to `sys.path` explicitly (for example
`launcher.py` imports `automation/gamectl.py`); `tests/common.py` adds every folder.

## Release updates

The updater reports an invalid ZIP before staging files. The installed release
and its version remain intact.

## Release packaging

Run `python tools/launcher/build_release.py --version <tag>` from the checkout
you want to package. The generated release notes cover the commits since the
closest previous release tag in that checkout's history. Build metadata such
as `+build.5` is accepted in version tags and does not affect update ordering.
