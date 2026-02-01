FROM python:3.11-slim

WORKDIR /app

# Install git for submodules
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Initialize submodules
RUN git submodule update --init --recursive

# Create data directory for TinyDB
RUN mkdir -p /app/data

# Expose port
EXPOSE 5000

# Run with waitress
CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=5000", "--threads=4", "run:app"]
