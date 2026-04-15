# Model Configuration

Baloo supports multiple LLM providers and models. You can use short names for convenience or specify full `provider/model` strings.

## Model Registry

| Short Name | Provider | Model ID | Max Turns | Tier |
|---|---|---|---|---|
| `flash` | Google | gemini-2.5-flash | 10 | Economy |
| `haiku` | Anthropic | claude-haiku-4-5 | 10 | Economy |
| `sonnet` | Anthropic | claude-sonnet-4-6 | 20 | Standard |
| `gemini-pro` | Google | gemini-2.5-pro | 20 | Standard |
| `opus` | Anthropic | claude-opus-4-6 | 30 | Premium |

## Choosing a Model

- **Economy** (`flash`, `haiku`) — Good for simple PRs (docs, deps, configs). Fast and cheap. Also used internally for FP verification.
- **Standard** (`sonnet`, `gemini-pro`) — The default. Handles most code reviews well. Best cost/quality balance.
- **Premium** (`opus`) — Best for complex PRs with deep logic, security-sensitive code, or architectural changes.

## Configuration

```bash
# Use a short name
AGENT_MODEL=sonnet

# Or a full provider/model string
AGENT_MODEL=anthropic/claude-sonnet-4-6

# Premium model for highest quality
AGENT_MODEL=opus
```

## Automatic Fallback

If the primary model fails (rate limit, timeout, availability), Baloo automatically retries with a fallback model:

```bash
AGENT_FALLBACK_MODEL=google/gemini-2.5-flash
```

The fallback uses a different provider to maximize availability. Set to empty to disable fallback.

When fallback is used, the review metadata includes:
- `fallback_used: true`
- `primary_model` — which model failed
- `primary_error` — why it failed

## API Keys

Each provider needs its own API key:

| Provider | Environment Variable |
|---|---|
| Anthropic | `ANTHROPIC_API_KEY` |
| Google | `GEMINI_API_KEY` |

## Thinking Level

Controls the depth of reasoning the model uses:

```bash
PI_THINKING_LEVEL=medium  # off, minimal, low, medium, high
```

Higher thinking = better analysis but slower and more expensive. `medium` is the default and recommended for most use cases.

## Cost Estimates

Approximate cost per review (typical 5-file PR):

| Model | Cost per Review |
|---|---|
| `flash` | ~$0.005 |
| `haiku` | ~$0.01 |
| `sonnet` | ~$0.03–0.08 |
| `gemini-pro` | ~$0.05–0.15 |
| `opus` | ~$0.15–0.40 |

Actual costs depend on PR size, number of agent turns, and thinking level.
