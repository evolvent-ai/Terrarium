FROM node:24

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Pin to 0.98.0: last version before Codex split platform binaries into
# aliased optional deps (0.99+), which hits npm/cli#7961 and silently
# breaks `npm install -g` in containers (openai/codex#13555).
RUN npm install -g @openai/codex@0.98.0

WORKDIR /root
CMD ["tail", "-f", "/dev/null"]
