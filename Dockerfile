FROM python:3.12.0-alpine3.18

WORKDIR /app
COPY . .

RUN apk add build-base

RUN pip install -r requirements.txt

# Install OAuth2 plugin
RUN python3 -m pip install -U https://github.com/coletdjnz/yt-dlp-youtube-oauth2/archive/refs/heads/master.zip

RUN apk add ffmpeg
RUN apk add opus
RUN apk add libffi-dev

RUN echo "Successfully setup the environment!"

ARG token=""

RUN echo "${token}" >> ./Rei/discord_token

RUN echo "${cookies}" >> ./Rei/cookies

CMD [ "python", "./Rei/rei.py"]