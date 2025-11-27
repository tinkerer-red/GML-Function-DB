# GML Function Catalog

This repository stores a normalized catalog of GameMaker Language (GML) functions for use by modding interpreters and tooling. Each function entry carries compact, precise flags for **safety** and **sandbox** analysis.

---

## Layout

* One JSON file per **category path**.
* Directory structure mirrors the manual categories.

Example:

```
catalog/
  Asset Management/
    Audio.json
  Drawing/
    GPU Control.json
  Maths And Numbers/
    Number Functions.json
```

Each file maps `function_name -> record`.

---

## Function record schema (key order is fixed)

```json
{
  "function_name": {
    "review_version": "2025.10" | null,
    "category_path": "Category/Subcategory" | null,
    "url": "https://manual.gamemaker.io/.../function.htm" | null,
    "peer_reviewed": true | false | null,

    "is_deprecated": true | false,
    "is_safe": true | false | null,
    "is_sandboxed": true | false | null,

    "is_file_io": true | false | null,
    "is_network_io": true | false | null,
    "is_personal_data": true | false | null,
    "is_platform_specific": true | false | null,

    "is_getter": true | false | null,
    "is_setter": true | false | null,
    "is_global_effect": true | false | null,
    "is_asset_reflection": true | false | null,
    "is_os_dialog": true | false | null,
    "is_os_directive": true | false | null
  }
}
```

**Tri-state convention**

* `true` = confirmed present/applicable
* `false` = confirmed absent/not applicable
* `null` = unknown or not yet verified

---

## Flag definitions (tight and unambiguous)

### Metadata

* **review_version** - Tag of the last manual or policy review that touched this entry (string or null).
* **category_path** - Manual category path for the function (no rollups). Null only if unknown.
* **url** - Manual page URL for the function (anchor form when applicable).
* **peer_reviewed** - `true` if a second reviewer confirmed the flags; `false` if self-reviewed; `null` if not yet reviewed.

### Top-level gates

* **is_deprecated** - Function is marked as deprecated in the spec/manual.
* **is_safe** - Function is acceptable for arbitrary mod use.
  Must be **false** if any of the following is `true`:
  `is_file_io`, `is_network_io`, `is_personal_data`, `is_os_dialog`.
  Also treat **inference** of personal information as unsafe (e.g., date/time APIs used to derive local time zone). Use `is_personal_data=true` for both direct access and reliable inference pathways.
* **is_sandboxed** - Function cannot access or reveal non-exposed project data and cannot impact global engine state outside exposed handles.
  Must be **false** if `is_asset_reflection=true` or `is_global_effect=true`.

### Capability and scope

* **is_file_io** - Reads/writes files, folders, or paths, or launches OS file pickers.
* **is_network_io** - Performs HTTP, sockets, matchmaking, platform network APIs, analytics, cloud, or any network traffic.
* **is_personal_data** - Accesses or can reliably infer user/system information, including environment variables, clipboard, usernames, system identifiers, **or time zone inference via date/time APIs**.
* **is_platform_specific** - Function is tied to a platform or service (e.g., HTML5, UWP, Xbox, PlayStation, Steam, GX.games).

### Behavioral hints

* **is_getter** - Primarily returns state without mutation (e.g., `get`, `is`, `has`).
* **is_setter** - Primarily mutates state (e.g., `set`, `add`, `replace`).
* **is_global_effect** - Mutates engine-wide or game-wide global state, (e.g., `gpu_set_*`, `window_*`, `physics_world_*`, `room_*`, `random_set_seed`).
  (Additionally anything which touches those globals like getter functions will always be `is_sandboxed=false`)
* **is_asset_reflection** - Enumerates or resolves assets by name/index or reveals asset metadata beyond explicitly exposed handles (e.g., `asset_*`, `*_get_index`, `*_get_name`, `get_ids`).
  (Additionally unfortunately this will also include all surfaces and buffers as they are mearly indexes and not handles, as well as most `script_execute` like functions, as all built in functions are internally just indexes)
* **is_os_dialog** - Triggers an OS/modal UI dialog (e.g., `show_message`, `show_question`, file/directory pickers).
* **is_os_directive** - Sends a directive to the OS/driver layer (e.g., `window_*`, `display_*`, `gpu_set_*`, `mouse_set_*`, `keyboard_set_*`, `external_define`).

---

## Interpreting **safe** vs **sandboxed**

* **Safe** answers: “Can mods call this freely without touching disk, network, personal data (including inference), or popping OS dialogs?”
  If **any** of `is_file_io`, `is_network_io`, `is_personal_data`, `is_os_dialog` is `true`, then `is_safe=false`.

* **Sandboxed** answers: “Can this function escape the exposed surface?”
  If a function can reveal non-exposed assets or mutate global engine state that affects non-exposed content, set `is_sandboxed=false`.

These axes are independent: a function can be safe but not sandboxed, or sandboxed but not safe.

---

## Examples

* **Pure math** (e.g., `clamp`):
  `is_safe=true`, `is_sandboxed=true`; all capability flags `null` or `false`.

* **File picker** (e.g., `get_open_filename`):
  `is_safe=true`, `is_sandboxed=false`; in this case that data was opted into exposing by the end user, this is perfect for peer reviews to discuss.

* **Asset lookup** (e.g., `asset_get_index`):
  `is_asset_reflection=true` -> `is_sandboxed=false`; still `is_safe=true` if no disk/network/personal data/dialogs.

* **GPU state change** (e.g., `gpu_set_blendmode`):
  `is_global_effect=true`, `is_os_directive=true` -> `is_sandboxed=false`; usually still `is_safe=true`.

* **Date/time exposure** (e.g., `date_current_datetime`):
  This is usable to infer local time zone or similar personal/environment info, so `is_personal_data=true` -> `is_safe=false`.

---

## Contributing

* Prefer small, targeted edits to category files to reduce conflicts.
* Keep key order exactly as defined above.
* Set flags to `true` only with high confidence; otherwise leave `null`.
* When you verify an entry yourself, set `peer_reviewed=false`. A second reviewer sets it to `true`.
* If a function(s) is missing a category, update the category JSON(s), then commit.
* Use ASCII only in JSON files. Avoid changes that reorder keys or entries unnecessarily.
