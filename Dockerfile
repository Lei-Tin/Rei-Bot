FROM python:3.9.18-alpine3.18

WORKDIR /app
COPY . .

RUN pip install -r requirements.txt
RUN apk add ffmpeg
RUN apk add opus

RUN echo "Successfully setup the environment!"

ARG token=""

RUN echo "${token}" >> ./Rei/discord_token

CMD [ "python", "./Rei/rei.py"]