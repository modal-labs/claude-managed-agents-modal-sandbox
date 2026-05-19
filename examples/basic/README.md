# Maude CLI

A remote coding agent that uses [Modal Sandboxes](https://modal.com/docs/guide/sandbox) as the execution environment for [Claude Managed Agents](https://docs.anthropic.com/en/docs/claude-code/managed-agents), which you can interact with via a demonstration CLI. Both the agent loop and the sandbox executions are all happening remotely to the machine running this CLI, so you can disconnect and continue the session at any time in the future.

<p align="center">
  <img src="docs/screenshot.png" alt="Maude CLI" width="720">
</p>

## Setup

### Preparation

* Copy the dotenv files

```bash
cd examples/basic
cp .env.example .env
cp .env.local.example .env.local
```

### Modal

* Set up [uv](https://docs.astral.sh/uv/)
* Set up the local venv: `uv sync`
* (Optional) Create and/or activate a Modal environment for this example.

```bash
uv run modal environment create claude-managed-agents
uv run modal config set-environment claude-managed-agents
```

* Deploy the webhook

```bash
uv run modal deploy src/claude_webhook_handler.py
```

You should see something like this in your logs.

```
Created web function webhook => https://<workspace>-<environment>--<app>-<id>.modal.run
```

You should take note of this webhook URL, we'll need it later in the setup process.
Your webhook isn't fully functional yet. We'll do a redeploy later in the setup process.

### Claude

* Create and/or activate a non-default workspace in [Claude Platform](https://platform.claude.com). All the Claude resources should be created inside this workspace.

* Note your **Workspace ID**:
   * Open any page inside your workspace in [Claude Platform](https://platform.claude.com)
   * In the browser address bar, copy the segment after `/workspaces/` (looks like `wrkspc_...`)
   * Set `ANTHROPIC_WORKSPACE_ID` in `.env`. The CLI uses this to make
     the Claude Agent, Environment, and Session IDs clickable; if you omit it,
     everything still works but the links won't appear.

* Generate an **API key**
   * Call it 'Modal Basic Example'
   * Copy the key and set `ANTHROPIC_API_KEY` in `.env.local`

* Create an **Agent**
   * Choose blank agent template as the starting point
   * Set name as 'Modal Basic Example' in the YAML
   * Copy the id (under the title) and set `ANTHROPIC_AGENT_ID` in `.env`

* Create an **Environment**:
   * Call it 'Modal Basic Example'
   * Choose 'Self-hosted' as hosting type
   * Copy the id (under the title) and set `ANTHROPIC_ENVIRONMENT_ID` in `.env`

* Create an **Environment Key**:
   * Open 'Installation Instructions' on the environment above
   * Click 'Generate Secret Key'
   * Call it 'Modal Basic Example'
   * Copy the key and set `ANTHROPIC_ENVIRONMENT_KEY` in `.env`

* Create a **Webhook**:
   * Use the URL contained within the `modal deploy` logs above
   * Set name as 'Modal Basic Example'
   * Subscribe only to `Session lifecycle -> Run started`.
   * Copy the secret and set `ANTHROPIC_WEBHOOK_SECRET` in `.env`, then deploy again.

* With all the .env variables updated, let's redeploy so our Modal app picks them up.

```bash
uv run modal deploy src/claude_webhook_handler.py
```

## Usage

```bash
uv run src/cli.py
```

The CLI prints `sandbox.started` and `sandbox.stopped` panels when the Modal
Sandbox for the session appears or exits. By default, the CLI creates a
Sandbox Connect Token preview link for port 8080 when it sees a running
sandbox. To disable preview links, run:

```bash
uv run src/cli.py --no-preview
```

To demo Sandbox Connect Tokens, ask the agent to start a server on port 8080:

```text
Start a Python HTTP server on port 8080 that serves a small HTML page with the current working directory and a timestamp.
```

The CLI also prints a `sandbox.preview` panel with a fresh connect-token URL
whenever it sees a new running sandbox, without
requiring an extra Claude message.
