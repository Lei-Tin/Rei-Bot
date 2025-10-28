FROM python:3.12-slim

WORKDIR /app
COPY . .

RUN apt-get update && apt-get install -y build-essential libffi-dev git ffmpeg curl
RUN apt-get install -y opus-tools libopus0 libogg0

# Adding git to install discord.py from github source instead of pypi
RUN apt-get install -y git

# Install Deno for yt-dlp
RUN curl -fsSL https://deno.land/install.sh | sh

RUN pip install -U pip

# So that this installs the latest versions of the yt-dlp package
RUN pip install -U -r requirements.txt

# OAuth login method is no longer working (as of November 2024)
# Install OAuth2 plugin
# RUN python3 -m pip install -U https://github.com/coletdjnz/yt-dlp-youtube-oauth2/archive/refs/heads/master.zip

RUN echo "Successfully setup the environment!"

ARG token=""
ARG yt_cookies=""
ARG bilibili_cookies=""

# Using cookies now to authenticate
RUN echo "${token}" >> ./Rei/discord_token
RUN echo "${yt_cookies}" >> ./Rei/cookies.txt
RUN echo "${bilibili_cookies}" >> ./Rei/cookies.txt

CMD [ "python", "./Rei/rei.py"]