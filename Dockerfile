FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy
WORKDIR /app
RUN pip install --no-cache-dir playwright==1.49.0 edge-tts imageio-ffmpeg
COPY record.py .
COPY examples ./examples
# scripts + output live in /work (mounted from your PC)
WORKDIR /work
ENTRYPOINT ["python", "/app/record.py"]
