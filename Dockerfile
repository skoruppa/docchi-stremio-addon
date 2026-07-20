FROM python:3.12-slim

WORKDIR /app

# Install git for submodule init and gcc for native extensions
RUN apt-get update && apt-get install -y --no-install-recommends git gcc libc6-dev && rm -rf /var/lib/apt/lists/*

# Copy requirements first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application (including .git and .gitmodules)
COPY . .

# Initialize submodules if .git is available (CI/local), skip on platforms that pre-clone (Render)
RUN if [ -d .git ]; then git submodule update --init --recursive; fi

# Recompile native PoW solver for target architecture (overrides pre-built x86_64)
RUN if [ -f /app/app/players/pow_solver.c ]; then \
      gcc -O3 -shared -fPIC -o /app/app/players/pow_solver.so /app/app/players/pow_solver.c; \
    fi

# Create data directory
RUN mkdir -p /app/data

# Cleanup git to reduce image size
RUN rm -rf .git app/players/.git data/anime-lists/.git

# Expose port
EXPOSE 5000

# Run with uvicorn
CMD ["uvicorn", "run:app", "--host", "0.0.0.0", "--port", "5000", "--workers", "1", "--proxy-headers"]
