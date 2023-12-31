FROM python:3.12.0-alpine3.18

WORKDIR /app
COPY . .

RUN apk add build-base

RUN pip install -r requirements.txt
RUN apk add ffmpeg
RUN apk add opus
RUN apk add libffi-dev

RUN echo "Successfully setup the environment!"

ARG token=""

RUN echo "${token}" >> ./Rei/discord_token

CMD [ "python", "./Rei/rei.py"]