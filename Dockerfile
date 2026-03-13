FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY bulk_sender.py .

# The following files should be mounted at runtime:
# - .env (configuration)
# - newsletter.png (image for email body)
# - newsletter.pdf (attachment)

CMD ["python", "bulk_sender.py"]


