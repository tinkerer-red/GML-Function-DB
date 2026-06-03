# GML Function Catalog

This repository stores a normalized catalog of GameMaker Language (GML) functions for modding interpreters, allowlist builders, and related tooling. Each function record describes safety, sandbox scope, platform concerns, and interpreter hints.

## Layout

The `db/` directory mirrors the GameMaker manual category structure. Each JSON file maps `function_name` to a record.

```text
db/
  Asset Management/
    Audio.json
  Drawing/
    GPU Control.json
  Maths And Numbers/
    Number Functions.json
```

Supporting rules and metadata live under `src/`:

* `src/schema/fields.json` defines allowed fields, key order, value types, and defaults.
* `src/rules/facts.json` defines no-exception validation rules.
* `src/rules/heuristics.json` defines review queues for suspicious or underclassified records.
* `src/resources/GmlSpec.xml` is a bundled GameMaker language-spec snapshot used as review metadata.

## Record Model

Records are intentionally sparse. Required review fields are always present, while optional fields are only written when they differ from their default.

```json
{
  "function_name": {
    "review_version": "2024.1400.5.1027",
    "category_path": "Maths And Numbers/Number Functions",
    "url": "https://manual.gamemaker.io/.../function.htm",
    "peer_reviewed": false,
    "is_safe": true,
    "is_sandboxed": true,
    "is_compile_time_possible": true
  }
}
```

No undeclared fields are allowed. Add new fields to `src/schema/fields.json` before using them in `db/`.

## Review Values

Fields that allow `null` use this convention:

* `true` means confirmed present or applicable.
* `false` means confirmed absent or not applicable.
* `null` means unknown or not yet reviewed.

Optional flags default to `false` when omitted. Consumers should read the schema or use the resolved export instead of treating missing optional fields as unknown.

Current optional flags:

* `is_deprecated`
* `is_file_io`
* `is_network_io`
* `is_personal_data`
* `is_platform_specific`
* `is_getter`
* `is_setter`
* `is_global_reflection`
* `is_asset_reflection`
* `is_os_dialog`
* `is_os_reflection`
* `is_lifecycle_state`
* `is_async_reflection`
* `is_callback_invoker`
* `is_return_pure`
* `is_compile_time_possible`

`notes` is optional and source-only. It is for reviewer context and is omitted from resolved exports.

## Flag Definitions

### Metadata

* **review_version** - Tag or version of the last manual or policy review.
* **category_path** - Manual category path. Use `null` only when unknown.
* **url** - Manual page URL. Anchor URLs are preferred when available.
* **peer_reviewed** - `true` after a second reviewer confirms the record, `false` after self-review, and `null` when not reviewed.

### Safety Gates

* **is_deprecated** - The function is deprecated in the spec or manual.
* **is_safe** - The function is acceptable for arbitrary mod use. It must be `false` when `is_file_io`, `is_network_io`, `is_personal_data`, `is_os_dialog`, `is_os_reflection`, or `is_callback_invoker` is `true`.
* **is_sandboxed** - The function cannot access non-exposed project data and cannot read or mutate runner-global or host-global state. It must be `false` for file IO, network IO, OS dialogs, asset reflection, global reflection, OS reflection, or callback invocation.

### Capabilities

* **is_file_io** - Reads or writes files, folders, paths, or launches OS file pickers.
* **is_network_io** - Performs HTTP, sockets, matchmaking, cloud, analytics, platform network APIs, or any other network traffic.
* **is_personal_data** - Accesses or can reliably infer user or system information, including clipboard contents, environment details, usernames, system identifiers, or local time zone inference.
* **is_platform_specific** - Depends on a platform or service such as HTML5, UWP, Xbox, PlayStation, Steam, GX.games, Android, iOS, Windows, macOS, or Linux.
* **is_os_dialog** - Opens an OS or modal dialog, such as message boxes, questions, file pickers, or directory pickers.
* **is_os_reflection** - Reads, reveals, or mutates OS, device, window, browser, native extension, or host environment state. Examples include `os_get_info`, `window_get_caption`, `window_set_caption`, `keyboard_check_direct`, `keyboard_virtual_show`, `gamepad_get_guid`, `gamepad_set_vibration`, `clipboard_get_text`, `external_define`, extension metadata queries, and URL or browser helpers.

Do not use `is_os_reflection` for ordinary runner input polling whose purpose is to let mods read keyboard, mouse, touch, or controller state, such as `keyboard_check`, `mouse_check_button`, or `gamepad_button_check`. Do not use it for renderer-only runtime state such as GPU texture settings, texture groups, surfaces, shaders, vertex submission, videos, screenshots, or debug overlay logging.

### Scope

* **is_global_reflection** - Reads or mutates runner-wide state that exists regardless of what the host exposes, such as GPU state, window state, the physics world, room transitions, random seed state, gesture settings, input remaps, or `global.*` variables.
* **is_asset_reflection** - Creates, enumerates, resolves, or reveals project-level assets beyond explicitly exposed handles, such as asset lookups by name or index, `*_get_name`, `*_add`, or APIs that expose script/function indexes.
* **is_lifecycle_state** - Participates in an ordered workflow where calls must be paired or sequenced, such as primitive drawing, vertex building, INI open/read/close, file text open/read/close, ZIP create/add/save, or begin/end APIs.
* **is_async_reflection** - Starts, participates in, or observes an asynchronous runner workflow whose result is delivered later through async state or events, such as HTTP requests, async loads, async dialogs, audio group loading, async buffer groups, or async unzip.
* **is_callback_invoker** - Invokes, schedules, stores, or later calls a supplied function, script, or method callback. Examples include array/string/struct callback iteration, `call_later`, `time_source_create`, script hooks, `json_parse` filters, and `script_execute`.

### Behavioral Hints

* **is_getter** - Primarily returns state directly without mutating caller-provided output storage.
* **is_setter** - Primarily mutates persistent engine, asset, instance, handle, file, network, platform, or OS state.

Do not mark a function as a getter when its useful output is written into a caller-provided buffer, DS map, or DS list instead of being returned. For example, `buffer_get_surface(buffer, surface, offset)` writes into a buffer, and `skeleton_bone_data_get(bone, map)` populates a map.

Do not mark a function as a setter only because it returns a modified copy or mutates a temporary value. For example, `string_delete()` returns a new string rather than mutating persistent state.

### Interpreter Hints

* **is_return_pure** - The return value is the meaningful effect of the call. An interpreter or compiler may warn, error, or remove the call when the result is unused and doing so preserves target semantics.
* **is_compile_time_possible** - The function can be reduced to a pure return at compile time when every argument is a compile-time literal. This also requires `is_safe=true`, `is_sandboxed=true`, and `is_return_pure=true`.

## Safe And Sandboxed

`is_safe` answers whether arbitrary mod code may call the function freely. Disk, network, personal data, OS dialogs, OS reflection, and callback invocation are not safe by default.

`is_sandboxed` answers whether the function can escape the host's exposed surface. Asset reflection, runner-global state, OS reflection, file IO, network IO, dialogs, and callback invocation are sandbox boundaries.

The sandbox has three main layers:

* **Asset layer** - The host decides which assets to expose. Once an asset handle is exposed, ordinary operations on that handle stay inside the asset layer.
* **Runner layer** - Runner state is always present and cannot be selectively exposed per mod environment. Reading or mutating it is global reflection.
* **OS layer** - Disk, network, user environment, OS dialogs, browser/window state, OS-level input UI, hardware/device metadata or output, and native extensions are host-environment boundaries.

These axes are independent. A function can be safe but not sandboxed, or sandboxed but not safe.

## Policy Notes

* Functions accepting the `all` keyword in place of an object or instance reference are not sandboxed. This does not automatically imply global reflection.
* String-or-handle resource arguments, such as `String|Id.Layer`, can resolve non-exposed resources by name and should be reviewed as sandbox escapes.
* Modern GML resources often use typed refs, and accepting or returning an exposed handle is not automatically asset reflection. Mark `is_asset_reflection` only when a function can create, enumerate, resolve, or reveal project/runtime resources beyond explicitly exposed handles. Some APIs still accept legacy numeric IDs, so handle families should be reviewed individually when numeric coercion can bypass the intended exposed set.
* Some old APIs still use numeric runner-global IDs. `physics_fixture_create()` returns a plain numeric index into the global fixture table, so `physics_fixture_*` APIs are global reflection and not sandboxed.
* Ordinary input polling is allowed input access, not OS reflection. Direct hardware checks, virtual keyboard UI, controller metadata, controller mappings, and hardware output are OS or device reflection.

## Examples

* **Pure math**, such as `clamp`: `is_safe=true`, `is_sandboxed=true`.
* **File picker**, such as `get_open_filename`: `is_file_io=true`, `is_os_dialog=true`, `is_safe=false`, `is_sandboxed=false`.
* **Asset lookup**, such as `asset_get_index`: `is_asset_reflection=true`, `is_sandboxed=false`, and still possibly `is_safe=true`.
* **Runner state**, such as `random_set_seed`: `is_global_reflection=true`, `is_sandboxed=false`, and possibly `is_safe=true`.
* **Window state**, such as `window_set_caption`: `is_global_reflection=true`, `is_os_reflection=true`, `is_safe=false`, `is_sandboxed=false`.
* **Date/time exposure**, such as `date_current_datetime`: `is_personal_data=true`, `is_os_reflection=true`, `is_safe=false`, `is_sandboxed=false`.
* **Compile-time candidate**, such as `point_distance`: `is_compile_time_possible=true` only when literal arguments can produce the same result.

## Contributing

* Keep edits small and category-focused.
* Keep key order exactly as defined by `src/schema/fields.json`.
* Omit optional flags when the default `false` applies.
* Use `null` only on required review fields that allow unknown state.
* Set `peer_reviewed=false` when you verify an entry yourself. A second reviewer sets it to `true`.
* Add a short `notes` value only when a flag choice is not obvious from the manual or policy.

## Advanced Users

Validate the source database:

```sh
python src/validate.py
```

Normalize source files to contract order and remove optional fields equal to their default:

```sh
python src/validate.py --normalize --write
```

Export a resolved single-file database:

```sh
python src/builder.py
```

The default export writes `build/functions_resolved.json`. It is keyed by function name and includes every optional default. Each record also includes `function_name` for consumers that iterate over values.

Build filtered outputs:

```sh
python src/builder.py --include is_safe=true --exclude is_deprecated --format names --out build/safe_functions.txt
python src/builder.py --include is_safe=true --include is_sandboxed=true --format json --out build/sandboxed.json
python src/builder.py --list-fields
```

Review heuristic queues:

```sh
python src/validate.py --heuristics
python src/validate.py --list-heuristics
python src/validate.py --heuristic spec_function_missing_db --format table
```

Heuristics are report-only by default. Investigate them one at a time. When a heuristic becomes a no-exception rule, promote it into `src/rules/facts.json`.

`src/resources/GmlSpec.xml` is a review aid, not the catalog source of truth. When updating it, check the `spec_function_missing_db` heuristic for newly exposed functions.

GitHub workflows:

* `.github/workflows/validate.yml` validates, checks normalization, and verifies that an export can be generated.
* `.github/workflows/heuristics.yml` is manually triggered and reports heuristic queues.
