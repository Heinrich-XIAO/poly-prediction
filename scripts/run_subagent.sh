#!/bin/bash
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT"

echo "=== Starting Polymarket strategy sub-agent ==="
echo "Project: $PROJECT"
echo "Model:   opencode/deepseek-v4-flash-free"
echo

opencode run \
  --model opencode/deepseek-v4-flash-free \
  --file PROMPT.md \
  --title "Polymarket strategy agent" \
  --dangerously-skip-permissions \
  "Read the attached PROMPT.md and follow every step to create a profitable Polymarket strategy. Start with Step 1 and proceed sequentially. Do not stop until you complete all steps."
