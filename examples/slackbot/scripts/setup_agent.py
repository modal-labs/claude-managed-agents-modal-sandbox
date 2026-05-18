"""Set up the Slackbot's Claude Managed Agent (and its skills) on Claude Platform.

Uploads (or revs) every skill in `skills/`, then creates or updates the agent
with all of them attached. ANTHROPIC_AGENT_ID is written to .env on first run;
subsequent runs reuse it and update the existing agent in place.

Run from examples/slackbot: `uv run scripts/setup_agent.py`.
"""

from pathlib import Path

import anthropic
import dotenv
from anthropic.lib import files_from_dir
from anthropic.types.beta import (
    BetaManagedAgentsAgentToolset20260401Params,
    BetaManagedAgentsCustomSkillParams,
)


ROOT = Path(__file__).parents[1]
ENV_PATH = ROOT / ".env"
SKILLS_DIR = ROOT / "skills"

dotenv.load_dotenv(ROOT / ".env.local")

NAME = "Modal Slackbot Example"
MODEL = "claude-opus-4-7"
SYSTEM = (
    "You are Maude, a helpful Slack assistant powered by Claude Managed Agents "
    "running tools inside a Modal Sandbox. Keep replies concise and friendly!"
)
TOOLS: list[BetaManagedAgentsAgentToolset20260401Params] = [
    {"type": "agent_toolset_20260401"}
]

client = anthropic.Anthropic()

existing_skills = {s.display_title: s for s in client.beta.skills.list(source="custom")}

skills: list[BetaManagedAgentsCustomSkillParams] = []
for skill_dir in sorted(SKILLS_DIR.iterdir()):
    if not (skill_dir.is_dir() and (skill_dir / "SKILL.md").exists()):
        continue
    title = skill_dir.name.replace("-", " ").title()
    if existing := existing_skills.get(title):
        version = client.beta.skills.versions.create(
            existing.id, files=files_from_dir(str(skill_dir))
        )
        skill_id = existing.id
        print(f"Created version {version.version} of skill {skill_id} ({title!r})")
    else:
        skill = client.beta.skills.create(
            display_title=title, files=files_from_dir(str(skill_dir))
        )
        skill_id = skill.id
        print(f"Created skill {skill_id} ({title!r})")
    skills.append({"type": "custom", "skill_id": skill_id, "version": "latest"})

existing_id = dotenv.dotenv_values(ENV_PATH).get("ANTHROPIC_AGENT_ID")
if existing_id and existing_id != "agent_xxx":
    current = client.beta.agents.retrieve(existing_id)
    agent = client.beta.agents.update(
        existing_id,
        version=current.version,
        name=NAME,
        model=MODEL,
        system=SYSTEM,
        tools=TOOLS,
        skills=skills,
    )
    print(f"Updated {agent.id} to version {agent.version}")
else:
    agent = client.beta.agents.create(
        name=NAME, model=MODEL, system=SYSTEM, tools=TOOLS, skills=skills
    )
    dotenv.set_key(ENV_PATH, "ANTHROPIC_AGENT_ID", agent.id, quote_mode="never")
    print(f"Created {agent.id}")
