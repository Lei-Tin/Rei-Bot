FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev git ffmpeg curl unzip libopus0 libogg0 \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://deno.land/install.sh | sh -s v2.8.2
ENV PATH="/root/.deno/bin:${PATH}"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    'discord.py[voice]==2.7.1' 'curl_cffi==0.15.0'
# YouTube changes frequently: refresh the stable extractor on each CI build.
# CI publishes latest; restarting the Azure revision pulls the new image.
RUN pip install --no-cache-dir --upgrade 'yt-dlp[default]'
COPY Rei ./Rei
COPY deploy ./deploy
# Credentials are provided by Azure only when the container starts.
ENTRYPOINT ["python", "/app/deploy/entrypoint.py"]
CMD ["python", "./Rei/rei.py"]
