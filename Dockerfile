FROM python:3.12-slim

WORKDIR /app

# Install git for submodule init
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Copy requirements first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application (including .git and .gitmodules)
COPY . .

# Initialize submodules if not already present
RUN git submodule update --init --recursive

# Create data directory
RUN mkdir -p /app/data

# Cleanup git to reduce image size
RUN rm -rf .git app/players/.git data/anime-lists/.git

# Expose port
EXPOSE 5000

# Run with waitress
CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=5000", "--threads=4", "run:app"]
