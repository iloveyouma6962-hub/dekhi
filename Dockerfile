FROM python:3.10-slim

# FFmpeg ইনস্টলেশন (অডিও-ভিডিও মার্জ করার জন্য)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway এর dynamic PORT হ্যান্ডেল করার জন্য
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
