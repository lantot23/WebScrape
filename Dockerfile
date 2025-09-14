FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    HEADLESS=true \
    CHROME_PATH=/usr/bin/chromium

# Install Chromium + dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    xvfb \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libatspi2.0-0 \
    libxrandr2 \
    libgbm1 \
    fonts-liberation \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxtst6 \
    libpangocairo-1.0-0 \
    libgtk-3-0 \
    wget \
    curl \
    unzip \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY checkscrape.py .
COPY CloudflareBypasser.py .

CMD ["python", "checkscrape.py"]
