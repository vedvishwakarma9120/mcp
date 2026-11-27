# GitHub MCP Server

A Python [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for searching GitHub repositories and reading issues, pull requests, and files from an MCP client. The client launches the server locally over standard input and output (stdio). Public repositories work without a GitHub token, and the server is read-only by default.

## Quick start

1. Install [Git](https://git-scm.com/downloads) and [uv](https://docs.astral.sh/uv/getting-started/installation/). Open a new terminal and check that `git --version` and `uv --version` work. The commands below use Python 3.12, which uv can download if needed.
2. Copy the repository's HTTPS URL from **Code → HTTPS** on GitHub. In the examples below, replace `https://github.com/OWNER/REPO.git` with that URL and keep the `git+` prefix.
3. Add the configuration for your client below. The first start downloads the server and its dependencies. After it connects, try asking **“List five open issues in fastapi/fastapi.”**

### VS Code

Create `.vscode/mcp.json` in the workspace where you want to use the server. Add this entry under `servers`, start **github** from the MCP configuration, then use it in chat. [VS Code MCP setup](https://code.visualstudio.com/docs/agent-customization/mcp-servers)

```json
{
  "servers": {
    "github": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--python", "3.12", "--from", "git+https://github.com/OWNER/REPO.git", "github-mcp-server"]
    }
  }
}
```

### Cursor and Claude Desktop

- **Cursor** reads `~/.cursor/mcp.json` for all projects or `.cursor/mcp.json` for the current project. [Cursor MCP configuration](https://cursor.com/docs/mcp)
- **Claude Desktop** opens `claude_desktop_config.json` from **Settings → Developer → Edit Config**. Fully quit and reopen Claude Desktop after saving. [Claude Desktop local-server setup](https://modelcontextprotocol.io/docs/develop/connect-local-servers)

Add this entry under `mcpServers`. If the file already has servers, merge the `github` entry into the existing object.

```json
{
  "mcpServers": {
    "github": {
      "command": "uvx",
      "args": ["--python", "3.12", "--from", "git+https://github.com/OWNER/REPO.git", "github-mcp-server"]
    }
  }
}
```

### Install a persistent command

Use this if you prefer to install the server once and launch its installed command from your client. [uv tool installation](https://docs.astral.sh/uv/guides/tools/)

```sh
uv tool install --python 3.12 "git+https://github.com/OWNER/REPO.git"
uv tool update-shell
```

Restart your terminal and client, then set the server's `command` to `github-mcp-server` and its `args` to `[]`. The executable waits for MCP messages over stdio, so use it through a client or Inspector.

## GitHub access and optional settings

Public reads work with the sample configuration. Set `GITHUB_TOKEN` for private repositories or higher API limits. Create a fine-grained personal access token, choose the resource owner and repositories, and grant the permissions for the operations you need. [GitHub token setup](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)

| Setting | When to set it |
| --- | --- |
| `GITHUB_TOKEN` | Use **Contents: Read** for files and READMEs, **Issues: Read** for issues and comments, and **Pull requests: Read** for pull requests and diffs. |
| `ENABLE_WRITE_TOOLS` | Set to `true` to register `create_issue`. The token also needs **Issues: Read and write** on the target repository. |
| `LLM_API_KEY` | Enables AI pull request summaries when paired with the two settings below. |
| `LLM_BASE_URL` | OpenAI-compatible API base URL, for example `http://localhost:11434/v1` for Ollama. |
| `LLM_MODEL` | Model ID from your provider or from `ollama list` for a local model. |

For a GitHub install, use your client's secret input or set the variables in the `github` entry's `env` object in a private user-level configuration. For a local checkout, copy [`.env.example`](.env.example) to `.env` in the repository root and edit the values there. Keep credentials out of committed client configs. Restart the server after changing its settings.

The summary tool sends pull request metadata and up to 12,000 characters of its diff to the configured provider. This also applies to private pull requests. Leave the AI settings empty to disable summaries, or use a local provider for code you need to keep on your device. Ollama still requires a nonempty `LLM_API_KEY` setting, such as `ollama`.

## Clone and run locally

Replace the example URL with the repository's GitHub URL. This installs the versions in `uv.lock` along with the optional development tools.

```sh
git clone https://github.com/OWNER/REPO.git github-mcp-server
cd github-mcp-server
uv sync --locked --python 3.12 --extra dev
uv run --no-sync python examples/client.py
```

The demo lists the available tools. With `GITHUB_TOKEN` configured, it also runs a sample repository search. To launch this checkout from a desktop client, use the absolute path to its Python executable as `command` and `["-m", "github_mcp.server"]` as `args`. The executable is under `.venv/Scripts/python.exe` on Windows and `.venv/bin/python` on macOS or Linux. Use forward slashes in Windows paths in JSON, or escape each backslash.

To create the optional `.env` file from a terminal in the repository root, run `Copy-Item .env.example .env` in Windows PowerShell or `cp .env.example .env` on macOS or Linux.

### Test with MCP Inspector

From the cloned repository, use [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector) with a supported Node.js version.

```sh
npx -y @modelcontextprotocol/inspector uv run --no-sync python -m github_mcp.server
```

Open the local URL printed in the terminal and connect over **STDIO**. Under **Tools**, choose `list_open_issues` and use `fastapi` for both `owner` and `repo`, with `limit` set to `5`.

```sh
uv run --no-sync pytest
uv run --no-sync ruff check .
```

## Tools and resource

| Name | What it does |
| --- | --- |
| `search_repositories(query, limit=5)` | Searches GitHub repositories by keyword or GitHub search qualifiers. |
| `list_open_issues(owner, repo, limit=10)` | Lists open issues and filters out pull requests. |
| `list_pull_requests(owner, repo, state="open", limit=10)` | Lists pull requests in the `open`, `closed`, or `all` state. |
| `find_stale_issues(owner, repo, days=30)` | Finds inactive open issues among up to 100 oldest-updated results. |
| `get_issue_details(owner, repo, number)` | Reads the issue body and up to 10 recent comments. |
| `get_file_contents(owner, repo, path)` | Reads a repository text file, up to 12,000 characters. |
| `summarize_pull_request(owner, repo, number)` | Uses the optional AI provider to summarize the purpose, changes, and risks. |
| `create_issue(owner, repo, title, body)` | Creates an issue when write tools are enabled. |
| `repo://{owner}/{repo}/readme` | Exposes the repository README as an MCP resource. |

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Client cannot find `uvx` or `github-mcp-server` | Restart the desktop client so it picks up PATH changes, or use the full executable path. Find it with `Get-Command uvx` on Windows or `command -v uvx` on macOS or Linux. |
| First run fails to fetch the source | Check that the URL opens in GitHub, keep the `git+` prefix in the uv command, and verify `git --version`. Installing from a private source repository also requires Git access to that repository. |
| GitHub returns 401, 403, or 404 | Check the owner and repository name, token expiry, repository selection, and permissions. GitHub can also return 403 for a rate limit. |
| Issue creation is unavailable | Set `ENABLE_WRITE_TOOLS=true`, restart the server, and check that the token has issue write permissions. |
| Summaries say AI is unconfigured | Set `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL`, then restart the server. |
