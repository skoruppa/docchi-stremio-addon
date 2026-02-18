FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create data directory for TinyDB
RUN mkdir -p /app/data

# Expose port
EXPOSE 5000

# Run with waitress
CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=5000", "--threads=4", "run:app"]
