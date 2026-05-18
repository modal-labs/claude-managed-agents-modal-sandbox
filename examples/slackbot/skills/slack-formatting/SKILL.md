---
name: slack-formatting
description: Format replies using Slack mrkdwn syntax (not standard markdown). Use whenever composing a reply that will be posted to a Slack thread — which, in this app, is every reply.
---

# Slack Formatting

Replies from this agent are posted directly into a Slack thread, so they must
use Slack's `mrkdwn` syntax — *not* CommonMark / GitHub Markdown.

## Differences from standard markdown

| What you want   | Slack mrkdwn           | Don't use              |
| --------------- | ---------------------- | ---------------------- |
| Bold            | `*bold*`               | `**bold**`             |
| Italic          | `_italic_`             | `*italic*`             |
| Strikethrough   | `~strike~`             | `~~strike~~`           |
| Inline code     | `` `code` ``           | (same)                 |
| Code block      | ```` ```text``` ````   | language tag (ignored) |
| Blockquote      | `> quoted`             | (same)                 |
| Link            | `<https://… \| label>` | `[label](https://…)`   |
| Bullets         | literal `•` per line   | `-` / `*`              |
| Headings        | use *bold* instead     | `#`, `##` (ignored)    |

## Slack-only tokens

- User mention: `<@U12345>`
- Channel reference: `<#C12345|channel-name>`
- Date with locale formatting: `<!date^…|fallback>`

## Style guidance

- Keep replies short; Slack readers scan, they don't read.
- Prefer one short paragraph over a bulleted list when the response is one or
  two points.
- Reserve code blocks for actual code, command output, or structured data.
