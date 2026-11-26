# Mesh / animation format (`.x`, `.prt`, `.ani`)

**Status, 2026-11-26:** recovered from the client loader by disassembly (build in
[STATUS.md](STATUS.md)) and checked against the extracted data: `tools/dbmesh.py`
reads all 6,575 `.x`/`.prt`/`.ani` entries and consumes every byte of each file.
The only exceptions are 15 effect files with the DirectX `xof 0303bzip0032` magic
(compressed DirectX X, a different format, not handled).

Despite the `.x` suffix, unit meshes are **not** DirectX X files. They are a
JSerBuffer serialization of the D3DX skinned-mesh objects (`JSkinnedMeshSys`,
`JSkinnedMesh.cpp`). Files are written untagged, so the serializer's type-tag
bytes (`0x00A48AF0`) never appear. Varints are JSerBuffer varints: seven-bit
groups, the **last** byte has bit 7 set. A string is `varint length + bytes`; a
vector is `varint count + elements`.

## Layout

| Client function | Reads |
| --- | --- |
| JPK `.j` wrapper | sub-buffer `varint length, u8 flag, bytes` (removed by the extractor) |
| `0x00B1DDB0` (top level) | sub-buffer (`0x00B35E50`): `varint length, u8 flag, bytes` = **mesh stream**; then the frame tree (below) from the outer stream; then `u32 x4` passed to `D3DXCreateAnimationController` (max outputs, sets, tracks, events); then animation sets (`0x00B1CD60`) |
| `0x00B1D6E0` (frame, recursive) | `string name`, `f32[16]` TransformationMatrix (row-major, D3D row vectors), `bool has_mesh`, `bool has_sibling`, `bool has_child`; if `has_mesh` a mesh container is read from the mesh stream; then the child frame (stored at D3DXFRAME `+0x4C`) if `has_child`, then the sibling (`+0x48`) if `has_sibling` |
| mesh container (mesh stream) | `bool present`, `i32` *unknown*, `bool valid`, `bool has_skin`, `u32 vertex_count`, `u32 face_count` → `D3DXCreateMeshFVF(faces, vertices, 0x220 MANAGED, FVF 0x112)` |
| `0x00B1D530` | vertex bytes `vertex_count * 32` (FVF 0x112 = `XYZ, NORMAL, TEX1`: pos f32[3], normal f32[3], uv f32[2]); `u16` indices `face_count * 3`; `u32` attribute id per face; `vector<D3DXATTRIBUTERANGE>` (`AttribId, FaceStart, FaceCount, VertexStart, VertexCount`) |
| `0x00B1D6E0` cont. | `u32 material_count`, `string` *unknown* (usually empty), `D3DMATERIAL9[material_count]` (68 bytes: Diffuse, Ambient, Specular, Emissive f32[4], Power), `vector<string>` texture file names (`0x008FA810`, one per material, resolved case-insensitively next to the mesh), `u32 adjacency[face_count * 3]` |
| skin (if `has_skin`) | `i32 bone_count` → `D3DXCreateSkinInfoFVF(vertices, 0x112, bones)`; `0x00B1D2E0`: `f32` min bone influence (`SetMinBoneInfluence`), then per bone `string name`, `u32` influence count, `vector<u32>` vertices, `vector<f32>` weights, `f32[16]` offset matrix (`SetBoneName`, `SetBoneInfluence`, `SetBoneOffsetMatrix`) |
| `0x00B1CD60` (animations) | `i32 set_count`; per set `string name`, `f64 ticks_per_second` (4800 observed), `i32` playback type, `i32 animation_count` → `D3DXCreateKeyframedAnimationSet`; per animation `string frame_name`, `i32 x3` key counts, then raw keys in this order: rotation (`f32 time, quaternion x y z w`), translation (`f32 time, xyz`), scale (`f32 time, xyz`) → `RegisterAnimationSRTKeys` |

`.ani` files use the same top-level layout with an empty mesh stream (`0x80`)
and a frame tree without meshes. A few `.x` files (34) are also skeleton-only.

## Conventions verified on data

- The three key counts were equal in every file, so which count belongs to which
  key type is not settled; the data order rotation/translation/scale is.
- Stored quaternions are the **conjugate** of the D3DX rotation: converting the
  conjugate with `D3DXMatrixRotationQuaternion` reproduces the `.ani` frame
  matrices to 1e-7; the plain quaternion does not.
- Key times are ticks (4800 per second); keys are spaced 160 ticks = 30 fps.
- Skinning is standard D3DX: `bone = offset[b] * combined[frame named b]`.
  Skinned vertices are in model space; rigid meshes use their frame's combined
  matrix.
- Characters are assembled from a class skeleton (`unit/character/<class>/<class>.x`,
  whose own mesh is the fallback body) plus equipment parts (`part/<m?>/<slot>/*.prt`)
  whose skin bones bind by name to that skeleton; class animations live next to the
  skeleton (`mf_*.ani` for `fighter`).

## Tools

- `python tools/dbmesh.py info <file-or-dir>` — summary; `export <file-or-dir> --out DIR` — OBJ/MTL + textures (bind pose, right-handed).
- `py -3.13 tools/model_viewer [files…]` — Qt/OpenGL viewer: asset browser, outliner,
  textured/solid/wireframe/weight-paint shading, armature, animation playback and
  equipment attachment. Requires `pip install -r tools/model_viewer/requirements.txt`
  (Python 3.10+). The viewer reads the private client-data workspace
  (`../darkblood-client-data/files` or `$DARKBLOOD_CLIENT_DATA/files`); game data never
  enters this repository.
