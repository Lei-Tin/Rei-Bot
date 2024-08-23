FROM python:3.12.0-alpine3.18

WORKDIR /app
COPY . .

RUN apk add build-base

RUN pip install -r requirements.txt

# Install OAuth2 plugin
RUN python3 -m pip install -U https://github.com/coletdjnz/yt-dlp-youtube-oauth2/archive/refs/heads/master.zip

# For obtaining
RUN echo "Waiting for OAuth2"
RUN yt-dlp --username 'oauth2' --password '' --skip-download https://youtu.be/dQw4w9WgXcQ?si=bj7kO-C3zGc7dAAc

RUN apk add ffmpeg
RUN apk add opus
RUN apk add libffi-dev

RUN echo "Successfully setup the environment!"

ARG token=""

RUN echo "${token}" >> ./Rei/discord_token

CMD [ "python", "./Rei/rei.py"]