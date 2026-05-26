FROM python:3.12-slim

ENV HERMES_HOME=/terrarium/hermes

RUN apt-get update && apt-get install -y curl git xz-utils && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

WORKDIR /root
CMD ["tail", "-f", "/dev/null"]
