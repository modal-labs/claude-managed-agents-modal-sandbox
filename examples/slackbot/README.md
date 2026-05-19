# Maude Slackbot

A Slack app that maps Slack threads to [Claude Managed Agent](https://docs.anthropic.com/en/docs/claude-code/managed-agents) sessions, with [Modal Sandboxes](https://modal.com/docs/guide/sandbox) as the self-hosted worker environment.

## Setup

### Preparation

* Copy the dotenv files

```bash
cd examples/slackbot
cp .env.example .env
cp .env.local.example .env.local
```

Only user-specific Anthropic and Slack values go in the dotenv files. Demo-owned
defaults such as Modal app names, sandbox paths, and timeouts live in
`src/config.py`.

### Modal

* Set up [uv](https://docs.astral.sh/uv/)
* Set up the local venv: `uv sync`
* (Optional) Create and/or activate a Modal environment for this example.

```bash
uv run modal environment create claude-managed-agents
uv run modal config set-environment claude-managed-agents
```

* Build the sandbox image and deploy the Anthropic and Slack webhooks

```bash
make deploy
```

This runs `uv run modal run src/sandbox_image.py` (which builds the sandbox image and writes `SANDBOX_IMAGE_ID` into `.env`) and then `uv run modal deploy src/main.py`.

You should see web function URLs for the Anthropic session webhook and the Slack events endpoint.

```
Created web function webhook => https://<workspace>-<environment>--<app>-<id>.modal.run
Created web function slack_events => https://<workspace>-<environment>--<app>-<id>.modal.run
```

Take note of both URLs. The Anthropic webhook URL is used in Claude Platform; the Slack events URL is used in Slack Event Subscriptions.

### Claude

* Create and/or activate a non-default workspace in [Claude Platform](https://platform.claude.com). All the Claude resources should be created inside this workspace.
* Use resources dedicated to this Slackbot example.
* Avoid reusing the resources from `examples/basic`; both
  examples can deploy to separate Modal apps, but shared Claude resources can
  route the same work to both webhooks.

* Note your **Workspace ID**:
   * Open [Workspaces](https://platform.claude.com/settings/workspaces) and copy the ID for your workspace.
   * Or open any page inside your workspace in [Claude Platform](https://platform.claude.com), inspect the browser address bar, copy the segment after `/workspaces/` (looks like `wrkspc_...`)
   * Set `ANTHROPIC_WORKSPACE_ID` in `.env`. The Slackbot uses this to post a clickable session link into the Slack thread; if you omit it, everything still works but the link won't appear.

* Generate an **API key**
   * Call it 'Modal Slackbot Example'
   * Copy the key and set `ANTHROPIC_API_KEY` in `.env.local`

* Create an **Agent**
   * Choose blank agent template as the starting point
   * Set name as 'Modal Slackbot Example' in the YAML
   * Copy the ID (under the title) and set `ANTHROPIC_AGENT_ID` in `.env`

   > Or run `uv run scripts/setup_agent.py` instead — it creates the agent
   > (writing `ANTHROPIC_AGENT_ID` to `.env`), uploads every skill under
   > `skills/`, and attaches them. Re-running updates the existing agent and
   > pushes new skill versions in place, so it's safe to use whenever you edit
   > a `SKILL.md` or change the agent's system prompt. Requires
   > `ANTHROPIC_API_KEY` in `.env.local` (above).

* Create an **Environment**:
   * Call it 'Modal Slackbot Example'
   * Choose 'Self-hosted' as hosting type
   * Copy the ID (under the title) and set `ANTHROPIC_ENVIRONMENT_ID` in `.env`

* Create an **Environment Key**:
   * Open the environment detail page
   * Click 'Generate Secret Key'
   * Call it 'Modal Slackbot Example'
   * Copy the key and set `ANTHROPIC_ENVIRONMENT_KEY` in `.env`

* Create a **Webhook**:
   * Use the URL contained within the `modal deploy` logs above
   * Set name as 'Modal Slackbot Example'
   * Subscribe only to `Session lifecycle -> Run started`.
   * Copy the secret and set `ANTHROPIC_WEBHOOK_SECRET` in `.env`.

### Slack

* Create a Slack app in your workspace.
* Enable Agents & AI Apps if you want Slack assistant thread events.
* Add bot scopes:
   * `assistant:write`
   * `chat:write`
   * `im:history`
   * `app_mentions:read`
* Install or reinstall the app.
* Obtain a 'Signing Secret' from 'Basic Information'
* Obtain a 'Bot User OAuth Token' from 'Install App'
* Add the signing secret and bot token to `.env`:
   * `SLACK_SIGNING_SECRET`
   * `SLACK_BOT_TOKEN`

* After updating the `.env` variables, redeploy so Modal can pick them up.

```bash
make deploy
```

* In 'Event Subscriptions', use the Modal `slack_events` URL and subscribe to:
   * `assistant_thread_started`
   * `assistant_thread_context_changed`
   * `message.im`
   * `app_mention`

* If it doesn't verify the first time, try again.

* Install it in your Slack workspace

## Usage

* Choose a Slack channel and make sure @Maude is added to it
* Write a message in the channel that starts with @Maude: e.g. "@Maude What's 1+1? Verify your answer."

## Event flow

@Maude will send you a link to the Session on Claude Platform where you can see the event trace. Some of the most important events are shown below, and 👀 indicates which events are visible in the Slack thread by default. You could make more events visible with minor changes to the code: e.g. to show tool call inputs.

```
├─ session.status_running
├─ thread run
│  ├─ session.thread_status_running
│  ├─ user.message ("What's 1+1?") 👀
│  ├─ model span
│  │  ├─ span.model_request_start
│  │  ├─ agent.thinking
│  │  ├─ agent.tool_use (bash: python3 -c "print(1+1)")
│  │  └─ span.model_request_end
│  └─ session.thread_status_idle (requires_action) ──┐
└─ session.status_idle                               │
── Modal Sandbox runs `python3 -c "print(1+1)"`      │
── user.tool_result ("2")  ◀─────────────────────────┘
├─ session.status_running
├─ thread run
│  ├─ session.thread_status_running
│  ├─ model span
│  │  ├─ span.model_request_start
│  │  ├─ agent.message ("The answer is 2!") 👀
│  │  └─ span.model_request_end
│  └─ session.thread_status_idle (end_turn)
└─ session.status_idle
```
