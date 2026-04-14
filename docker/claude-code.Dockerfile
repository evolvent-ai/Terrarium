FROM node:20

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

WORKDIR /root
CMD ["tail", "-f", "/dev/null"]
