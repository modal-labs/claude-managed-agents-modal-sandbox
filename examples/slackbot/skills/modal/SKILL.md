---
name: modal
description: >
  This skill provides guidance for building and deploying applications on the
  Modal cloud platform. Use this skill whenever the user mentions Modal or has
  code that imports the `modal` SDK. This skill should also trigger when the
  user needs to run Python code with horizontal scalability (e.g. batch
  jobs), needs access to GPUs (e.g. AI/ML workloads including training and
  inference) or needs to execute processes in a sandboxed environment.
---

# Overview

This skill provides high-level guidance for working with the Modal cloud platform.

Modal is a cloud platform for AI / ML workloads. It offers highly-scalable serverless compute (including GPUs) with minimal configuration.

# Documentation

Modal's documentation is outlined at https://modal.com/llms.txt.

The official docs are the best source for up-to-date information on using Modal. Make use of them when planning, debugging, or answering questions!

*Always read the contents https://modal.com/llms.txt into your main context when starting work on a Modal task and use it to find relevant information.*

The docs are divided into three sections:

- Fetch _Guide_ pages for in-depth explanations of Modal features, primitives, and workflows
- Fetch _Examples_ pages to see how different AI applications look on Modal
- Fetch _API Reference_ pages for signatures and docstrings for components of the Python SDK

All docs pages can be fetched with an `.md` extension to get a plain text version of the content.

For broader context, https://modal.com/llms-full.txt aggregates all docs in a single very large file. Do *not* read this into your main context, but it may be useful for searching.

# Getting up to date

You have significant knowledge about Modal from your training data but may not be aware of new features or recent changes to the API. Fetching relevant docs while planning can help you discover the most up-to-date way to accomplish a task on Modal.

The Modal CLI provides a `modal changelog` command that can also be useful for learning about recent changes. There are several options for querying the changelog. E.g., running `modal changelog --since [DATE]` will show all changes made between that date (e.g., your knowledge cutoff) and the release of the SDK version that is in use.

Run `modal --version` to see the SDK version that is in use. Note that the online docs may reference features that are available only in recent versions.

# Using the CLI

The `modal` CLI can be used to run or deploy code, manage resources, and observe running Apps. It is a key tool for interacting with Modal.

Run `modal --help` to see all available CLI commands.

You can see more detailed information about each command by running `modal [command] --help`. If you are unsure of how to accomplish a task through the CLI (or if you get an error when trying), read the `--help` rather than guessing.

Tip: many CLI commands accept a `--json` flag to make their output more easily parseable, e.g. with `jq`.

The `modal` CLI is part of the Python SDK and executes in a Python runtime. Depending on the user's preferred Python development workflow, you may need to prefix `modal` CLI invocations with, e.g. `uv run` to ensure a consistent Python environment.

# Auth

Modal is a cloud platform. Using the CLI or running code that depends on the `modal` library requires internet access and an authorization token. There is no "local development mode" with Modal.

You can use the `modal token` CLI to create a new token (note: the token creation workflow requires human user involvement) or to debug authorization issues. Token setup only needs to happen once, so assume it is configured unless you encounter issues.

# Async Python

When writing async Python use Modal's `.aio()` interface (e.g. `modal.Sandbox.create.aio(...)`, `modal.Function.remote.aio(...)`) so that Modal yields the event loop while waiting on network I/O.

# Other languages

Python is currently the only runtime language for Modal Functions, but there are Modal SDKs in both JavaScript (TypeScript) and Go:

- Javascript SDK: https://github.com/modal-labs/modal-client/blob/main/js/README.md
- Go SDK: https://github.com/modal-labs/modal-client/blob/main/go/README.md

The Go / JS SDKs are not as mature as the Python SDK and may be missing features. The current scope for the Go / JS SDKs includes (1) creating and interacting with Sandboxes and (2) calling into deployed Modal Functions (i.e., Functions defined in Python).

They are primarily documented through examples hosted on GitHub rather than through the main Modal docs. You likely have much less knowledge of these SDKs from your training, so rely on these examples.
