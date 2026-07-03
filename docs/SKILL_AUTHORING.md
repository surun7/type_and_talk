# Skill Authoring Guide

## YAML Schema Overview

Skills are YAML files with the following top-level fields (full schema in
[`src/agent_uia/skills/schema.py`](../src/agent_uia/skills/schema.py)):

| Field        | Type     | Required | Description |
|-------------|----------|----------|-------------|
| `id`        | string   | yes      | Unique skill id (`[a-zA-Z0-9][a-zA-Z0-9_-]*`) |
| `name`      | string   | yes      | Human-readable name shown in the UI |
| `description` | string | yes      | Short description of what the skill does |
| `author`    | string   | yes      | Creator identifier |
| `version`   | integer  | yes      | Version number (bump on changes) |
| `inputs`    | list     | no       | Input parameter definitions |
| `steps`     | list     | yes      | Ordered list of step definitions |

### Step Kinds

Each step has a `kind` field:

- **`tool`** — executes a registered tool (e.g. `click`, `type_text`). Fields:
  `tool`, `args`, `depends_on`, `retry`, `continue_on_error`, `timeout_s`.
- **`decision`** — evaluates an expression to choose a branch. Fields:
  `if` (list of `{match, target}`), `default`, `depends_on`.
- **`complete`** — marks the end of a path. Fields: `depends_on` only.

## Worked Examples

### 1. Single Tool Step

```yaml
id: notepad-quick
name: Open Notepad
description: Launch Notepad and wait for its window.
author: tnt
version: 1
steps:
  - id: launch
    kind: tool
    tool: launch_app
    args:
      executable: notepad.exe
    depends_on: []
```

### 2. Tool with depends_on

```yaml
id: type-in-notepad
name: Type in Notepad
description: Open Notepad and type a message.
author: tnt
version: 1
inputs:
  - name: message
    type: string
    description: The text to type
steps:
  - id: launch
    kind: tool
    tool: launch_app
    args:
      executable: notepad.exe
    depends_on: []
  - id: wait
    kind: tool
    tool: wait_for_window
    args:
      title_contains: "Untitled"
    depends_on: [launch]
  - id: type
    kind: tool
    tool: type_text
    args:
      control_id: "{wait.window.id}"
      text: "{message}"
    depends_on: [wait]
```

### 3. Decision Step

```yaml
id: confirm-delete
name: Confirm and Delete
description: Ask the user to confirm, then delete.
author: tnt
version: 1
inputs:
  - name: target
    type: string
    description: Control to delete
steps:
  - id: confirm
    kind: tool
    tool: request_user_confirmation
    args:
      action_type: delete
      target: "{target}"
      risk_explanation: This will delete the control.
    depends_on: []
  - id: decide
    kind: decision
    if:
      - match: "{{confirm.confirmed}}"
        target: perform_delete
    default: abort
    depends_on: [confirm]
  - id: perform_delete
    kind: tool
    tool: click
    args:
      control_id: "{target}"
    depends_on: [decide]
  - id: abort
    kind: complete
    depends_on: [decide]
```

## Testing Locally

Run a skill from the CLI:

```bash
tnt skills run <skill-id>
```

To pass inputs:

```bash
tnt skills run click-fill-form --inputs '{"field_id": "txt1", "value": "hello"}'
```

List installed skills:

```bash
tnt skills list
```

## Security Guarantees

- Skills can only invoke **documented tools** (see `tools/`). Arbitrary code
  or shell execution is impossible from a skill YAML.
- Decision step expressions are evaluated in a **sandboxed asteval
  interpreter** that blocks `__import__`, `eval`, `exec`, `open`, and all
  dunder attribute access.
- Tool arguments are rendered through a **Jinja-like template engine** that
  cannot escape the sandbox.
- Tool dispatch goes through the same safety gate used by the LLM planner.

## Publishing

1. Write your skill YAML and test it locally with `tnt skills run`.
2. Host the YAML file at a public HTTPS URL.
3. Users install via:

   ```bash
   tnt skills install https://example.com/skills/my-skill.yaml
   ```

4. Optionally submit to the community skill registry (coming soon).
