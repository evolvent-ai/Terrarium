FROM node:24

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN npm install -g openclaw@latest

WORKDIR /root
CMD ["tail", "-f", "/dev/null"]
